

import hashlib
import json
import random
import shutil
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from ..core import canonicalization as sc
from ..core import data_structure as sds
from ..core import difficulty as difficulty_model
from ..core import solver as ss
from ..core import technique_catalog

# ---------------------------------------------------------------------------
# Configurazione archivio
# ---------------------------------------------------------------------------

PROJECT_ROOT = Path(__file__).resolve().parents[2]
ARCHIVES_ROOT = PROJECT_ROOT / "archives"

ARCHIVE_PROFILE_PATHS = {
    "offline": ARCHIVES_ROOT / "offline",
    "online": ARCHIVES_ROOT / "online",
}
ACTIVE_ARCHIVE_PROFILE = "offline"

SUDOKU_DATA_DIR = ARCHIVE_PROFILE_PATHS[ACTIVE_ARCHIVE_PROFILE]
SUDOKU_PUZZLES_DIR = SUDOKU_DATA_DIR / "puzzles"
SUDOKU_ANALYSES_DIR = SUDOKU_DATA_DIR / "analyses"
SUDOKU_CANONICAL_DIR = SUDOKU_DATA_DIR / "canonical"

PUZZLE_SCHEMA_VERSION = 3
CANONICAL_CLASS_SCHEMA_VERSION = 1

# Incrementare questo numero quando cambia il funzionamento del solver
# o il formato dell'analisi. Le vecchie analisi verranno ricalcolate.
ANALYSIS_VERSION = 30
ANALYSIS_SCHEMA_VERSION = 18

# Evita anche letture ripetute dal disco durante la stessa esecuzione.
# La chiave è (puzzle_id, analysis_variant), non soltanto puzzle_id.
_ANALYSIS_MEMORY_CACHE = {}


# ---------------------------------------------------------------------------
# Funzioni interne
# ---------------------------------------------------------------------------

def configure_archive(profile="offline", data_dir=None):
    """
    Seleziona l'archivio usato dal processo corrente.

    ``offline`` è il profilo predefinito e usa ``archives/offline``.
    ``online`` usa ``archives/online``. Entrambi sono ancorati alla radice del
    progetto e non alla directory da cui Python è stato avviato. ``data_dir``
    permette di fornire una radice esplicita, utile per server e test.

    La selezione è di processo: va eseguita all'avvio, prima di servire
    richieste o avviare analisi concorrenti.
    """
    global ACTIVE_ARCHIVE_PROFILE
    global SUDOKU_DATA_DIR
    global SUDOKU_PUZZLES_DIR
    global SUDOKU_ANALYSES_DIR
    global SUDOKU_CANONICAL_DIR

    profile = str(profile).strip().casefold()

    if profile not in ARCHIVE_PROFILE_PATHS:
        allowed = ", ".join(sorted(ARCHIVE_PROFILE_PATHS))
        raise ValueError(
            f"Profilo archivio non valido: {profile!r}. "
            f"Valori ammessi: {allowed}."
        )

    root = (
        Path(data_dir)
        if data_dir is not None
        else ARCHIVE_PROFILE_PATHS[profile]
    )

    ACTIVE_ARCHIVE_PROFILE = profile
    SUDOKU_DATA_DIR = root
    SUDOKU_PUZZLES_DIR = root / "puzzles"
    SUDOKU_ANALYSES_DIR = root / "analyses"
    SUDOKU_CANONICAL_DIR = root / "canonical"
    _ANALYSIS_MEMORY_CACHE.clear()
    _ensure_sudoku_directories()
    return archive_configuration()


def archive_configuration():
    """Restituisce il profilo e i percorsi dell'archivio attivo."""
    return {
        "profile": ACTIVE_ARCHIVE_PROFILE,
        "data_dir": SUDOKU_DATA_DIR,
        "puzzles_dir": SUDOKU_PUZZLES_DIR,
        "analyses_dir": SUDOKU_ANALYSES_DIR,
        "canonical_dir": SUDOKU_CANONICAL_DIR,
    }


def _ensure_sudoku_directories():
    SUDOKU_PUZZLES_DIR.mkdir(parents=True, exist_ok=True)
    SUDOKU_ANALYSES_DIR.mkdir(parents=True, exist_ok=True)
    SUDOKU_CANONICAL_DIR.mkdir(parents=True, exist_ok=True)


def _current_timestamp():
    return datetime.now(timezone.utc).isoformat()


def normalise_sudoku_grid(grid):
    """Converte stringhe, array e SudokuState in un array NumPy 9x9."""
    if isinstance(grid, sds.SudokuState):
        grid = grid.grid

    if isinstance(grid, str):
        text = "".join(grid.split()).replace(".", "0")

        if len(text) != 81:
            raise ValueError(
                f"Una griglia testuale deve contenere 81 cifre, non {len(text)}."
            )

        if any(character not in "0123456789" for character in text):
            raise ValueError(
                "La griglia può contenere solo cifre da 0 a 9 oppure '.'."
            )

        grid = [int(character) for character in text]

    array = np.asarray(grid, dtype=int)

    if array.size != 81:
        raise ValueError(
            f"Una griglia Sudoku deve contenere 81 valori, non {array.size}."
        )

    array = array.reshape(9, 9)

    if np.any((array < 0) | (array > 9)):
        raise ValueError("La griglia può contenere solamente valori da 0 a 9.")

    return array.copy()


def validate_unique_sudoku(grid):
    """Valida l'invariante fondamentale dell'archivio: una sola soluzione."""
    grid = normalise_sudoku_grid(grid)
    for unit in sds.UNITS:
        values = [
            int(grid[row, column])
            for row, column in unit
            if int(grid[row, column]) != 0
        ]
        if len(values) != len(set(values)):
            raise ValueError(
                "La griglia iniziale contiene cifre duplicate in una "
                "riga, colonna o box."
            )

    solution_count = sds.count_solutions(grid, limit=2)
    if solution_count == 0:
        raise ValueError("Il Sudoku non ha alcuna soluzione valida.")
    if solution_count > 1:
        raise ValueError(
            "Il Sudoku deve avere una soluzione unica; ne esiste più di una."
        )
    return grid


def _grid_to_string(grid):
    grid = normalise_sudoku_grid(grid)
    return "".join(str(int(value)) for value in grid.flat)


def sudoku_id(grid):
    """
    Restituisce un identificatore stabile derivato dalla griglia iniziale.

    Due Sudoku con la stessa griglia avranno sempre lo stesso identificatore.
    """
    grid_string = _grid_to_string(grid)

    return hashlib.sha256(
        grid_string.encode("utf-8")
    ).hexdigest()[:20]


def canonical_sudoku_id(grid):
    """Restituisce l'identità della classe isomorfa della griglia."""
    return sc.canonical_id(normalise_sudoku_grid(grid))


def _looks_like_grid_string(value):
    if not isinstance(value, str):
        return False

    text = "".join(value.split()).replace(".", "0")

    return (
        len(text) == 81
        and all(character in "0123456789" for character in text)
    )


def _puzzle_path(puzzle_id):
    return SUDOKU_PUZZLES_DIR / f"{puzzle_id}.json"


def _canonical_path(canonical_id):
    return SUDOKU_CANONICAL_DIR / f"{canonical_id}.json"


def _analysis_directory(puzzle_id):
    return SUDOKU_ANALYSES_DIR / puzzle_id


def _normalise_analysis_request(
    analysis_mode=ss.DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=ss.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
):
    """Normalizza la variante di analisi richiesta all archivio."""
    normaliser = getattr(ss, "_normalise_analysis_mode", None)

    if callable(normaliser):
        mode = normaliser(analysis_mode)
    else:
        aliases = getattr(ss, "ANALYSIS_MODE_ALIASES", {})
        allowed = getattr(
            ss,
            "ANALYSIS_MODES",
            {"deep", "profile", "superficial"},
        )
        mode = str(analysis_mode or ss.DEFAULT_ANALYSIS_MODE).strip().lower()
        mode = aliases.get(mode, mode)

        if mode not in allowed:
            raise ValueError(
                f"Modalità di analisi non valida: {analysis_mode!r}."
            )

    if mode == "profile":
        if profile_difficulty_window is None:
            profile_difficulty_window = getattr(
                ss,
                "DEFAULT_PROFILE_DIFFICULTY_WINDOW",
                1.0,
            )

        window = float(profile_difficulty_window)

        if window < 0:
            raise ValueError(
                "profile_difficulty_window deve essere maggiore "
                "o uguale a zero."
            )
    else:
        window = None

    return mode, window


def _profile_window_token(value):
    """Converte una finestra numerica in una parte di nome stabile."""
    text = format(float(value), ".12g")
    return text.replace("-", "m").replace(".", "p")


def _analysis_variant(
    analysis_mode=ss.DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=ss.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
):
    mode, window = _normalise_analysis_request(
        analysis_mode,
        profile_difficulty_window,
    )

    if mode == "profile":
        return f"profile_{_profile_window_token(window)}"

    return mode


def _analysis_cache_key(
    puzzle_id,
    analysis_mode=ss.DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=ss.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
):
    return (
        str(puzzle_id),
        _analysis_variant(
            analysis_mode,
            profile_difficulty_window,
        ),
    )


def _analysis_path(
    puzzle_id,
    analysis_mode=ss.DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=ss.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
):
    """Restituisce un file distinto per ogni variante di analisi."""
    variant = _analysis_variant(
        analysis_mode,
        profile_difficulty_window,
    )

    # Mantiene il nome storico per la deep; il default profile usa invece
    # un file esplicito che include la finestra nel nome.
    filename = (
        "analysis.json"
        if variant == "deep"
        else f"analysis_{variant}.json"
    )

    return _analysis_directory(puzzle_id) / filename


def _analysis_payload_is_current(
    payload,
    puzzle_id,
    analysis_mode=ss.DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=ss.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
):
    """Verifica versione, Sudoku e variante richiesta."""
    if (
        payload.get("puzzle_id") != puzzle_id
        or payload.get("schema_version") != ANALYSIS_SCHEMA_VERSION
        or payload.get("analysis_version") != ANALYSIS_VERSION
    ):
        return False

    requested_mode, requested_window = _normalise_analysis_request(
        analysis_mode,
        profile_difficulty_window,
    )

    stored_analysis = payload.get("analysis", {})
    stored_mode = payload.get(
        "analysis_mode",
        stored_analysis.get("analysis_mode", ss.DEFAULT_ANALYSIS_MODE),
    )
    stored_window = payload.get(
        "profile_difficulty_window",
        stored_analysis.get("profile_difficulty_window"),
    )

    try:
        stored_mode, stored_window = _normalise_analysis_request(
            stored_mode,
            stored_window,
        )
    except (TypeError, ValueError):
        return False

    if stored_mode != requested_mode:
        return False

    if requested_mode == "profile":
        return abs(float(stored_window) - float(requested_window)) <= 1e-12

    return True


def _current_analysis_payloads(puzzle_id):
    """Restituisce le varianti correnti già presenti per un Sudoku."""
    directory = _analysis_directory(puzzle_id)

    if not directory.exists():
        return {}

    variants = {}

    for path in directory.glob("analysis*.json"):
        try:
            payload = _read_json(path)
            analysis = payload.get("analysis", {})
            mode = payload.get(
                "analysis_mode",
                analysis.get("analysis_mode", ss.DEFAULT_ANALYSIS_MODE),
            )
            window = payload.get(
                "profile_difficulty_window",
                analysis.get("profile_difficulty_window"),
            )
            mode, window = _normalise_analysis_request(mode, window)
        except (
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            continue

        if not _analysis_payload_is_current(
            payload,
            puzzle_id,
            mode,
            window,
        ):
            continue

        variant = _analysis_variant(mode, window)
        variants[variant] = {
            "path": path,
            "payload": payload,
            "analysis_mode": mode,
            "profile_difficulty_window": window,
        }

    return variants


def _write_json(path, data, compact=False):
    """Scrive un JSON in modo atomico per evitare file parziali."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    temporary_path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=None if compact else 2,
            separators=(",", ":") if compact else None,
        ),
        encoding="utf-8",
    )

    temporary_path.replace(path)


def _read_json(path):
    path = Path(path)

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


def _canonical_fields(grid, existing=None):
    """Costruisce i campi canonici, riusando un record già aggiornato."""
    existing = existing or {}

    if (
        existing.get("canonicalization_version")
        == sc.CANONICALIZATION_VERSION
        and existing.get("canonical_id")
        and existing.get("canonical_grid")
        and existing.get("canonical_transform")
    ):
        return {
            "canonicalization_version": sc.CANONICALIZATION_VERSION,
            "canonical_id": existing["canonical_id"],
            "canonical_grid": existing["canonical_grid"],
            "canonical_transform": existing["canonical_transform"],
            "is_canonical": bool(existing.get("is_canonical", False)),
            "canonical_equivalent_minimum_count": int(
                existing.get("canonical_equivalent_minimum_count", 1)
            ),
        }

    details = sc.canonicalize_details(grid)
    grid_string = _grid_to_string(grid)

    return {
        "canonicalization_version": sc.CANONICALIZATION_VERSION,
        "canonical_id": sc.canonical_id_from_string(
            details.canonical_string
        ),
        "canonical_grid": details.canonical_string,
        "canonical_transform": details.transform.to_dict(),
        "is_canonical": grid_string == details.canonical_string,
        "canonical_equivalent_minimum_count": (
            details.equivalent_minimum_count
        ),
    }


def _canonical_members_from_puzzles(canonical_id, canonical_grid):
    """
    Ricostruisce a basso costo i membri già migrati se manca parte dell'indice.

    I record legacy senza ``canonical_id`` vengono gestiti dalla migrazione
    esplicita: canonicalizzarli tutti durante un singolo salvataggio renderebbe
    imprevedibile la latenza dell'operazione.
    """
    members = set()

    for path in SUDOKU_PUZZLES_DIR.glob("*.json"):
        payload = _read_json(path)

        if payload.get("canonical_id") == canonical_id:
            if payload.get("canonical_grid") != canonical_grid:
                raise RuntimeError(
                    "Collisione dell'indice canonico rilevata nei puzzle: "
                    f"{canonical_id}."
                )
            members.add(str(payload["id"]))

    return members


def _register_canonical_variant(puzzle_payload):
    """Aggiorna atomicamente l'indice della classe isomorfa."""
    canonical_id = puzzle_payload["canonical_id"]
    canonical_grid = puzzle_payload["canonical_grid"]
    puzzle_id = puzzle_payload["id"]
    path = _canonical_path(canonical_id)
    existing = _read_json(path) if path.exists() else {}

    if (
        existing
        and existing.get("canonical_grid") != canonical_grid
    ):
        raise RuntimeError(
            "Collisione dell'indice canonico: due forme MinLex diverse "
            f"hanno prodotto {canonical_id}."
        )

    members = set(existing.get("variant_ids", []))
    members.update(
        _canonical_members_from_puzzles(canonical_id, canonical_grid)
    )
    members.add(puzzle_id)
    members = sorted(members)
    timestamp = _current_timestamp()

    canonical_payload = {
        "schema_version": CANONICAL_CLASS_SCHEMA_VERSION,
        "canonicalization_version": sc.CANONICALIZATION_VERSION,
        "canonical_id": canonical_id,
        "canonical_grid": canonical_grid,
        "primary_puzzle_id": members[0],
        "variant_ids": members,
        "variant_count": len(members),
        "created_at": existing.get("created_at", timestamp),
        "updated_at": timestamp,
    }
    _write_json(path, canonical_payload)
    return canonical_payload


def _unregister_canonical_variant(puzzle_payload):
    """
    Rimuove una variante dall'indice canonico e lo ricostruisce dai puzzle.

    La scansione dei record ancora presenti evita di conservare riferimenti
    orfani qualora un vecchio indice fosse già incompleto o non aggiornato.
    """
    canonical_id = puzzle_payload["canonical_id"]
    canonical_grid = puzzle_payload["canonical_grid"]
    puzzle_id = str(puzzle_payload["id"])
    path = _canonical_path(canonical_id)
    existing = _read_json(path) if path.exists() else {}

    if (
        existing
        and existing.get("canonical_grid") != canonical_grid
    ):
        raise RuntimeError(
            "Collisione dell'indice canonico durante la cancellazione: "
            f"{canonical_id}."
        )

    members = _canonical_members_from_puzzles(
        canonical_id,
        canonical_grid,
    )
    members.discard(puzzle_id)
    members = sorted(members)

    if not members:
        if path.exists():
            path.unlink()
        return None

    timestamp = _current_timestamp()
    canonical_payload = {
        "schema_version": CANONICAL_CLASS_SCHEMA_VERSION,
        "canonicalization_version": sc.CANONICALIZATION_VERSION,
        "canonical_id": canonical_id,
        "canonical_grid": canonical_grid,
        "primary_puzzle_id": members[0],
        "variant_ids": members,
        "variant_count": len(members),
        "created_at": existing.get("created_at", timestamp),
        "updated_at": timestamp,
    }
    _write_json(path, canonical_payload)
    return canonical_payload


def _canonical_class_info(payload):
    """Aggiunge al record informazioni dinamiche sui duplicati isomorfi."""
    canonical_id = payload.get("canonical_id")

    if not canonical_id:
        return {}

    path = _canonical_path(canonical_id)

    if path.exists():
        canonical_class = _read_json(path)
        members = sorted(set(canonical_class.get("variant_ids", [])))
    else:
        members = [str(payload["id"])]

    puzzle_id = str(payload["id"])

    if puzzle_id not in members:
        members.append(puzzle_id)
        members.sort()

    primary = members[0]

    return {
        "primary_variant_id": primary,
        "isomorphic_variant_ids": members,
        "isomorphic_variant_count": len(members),
        "is_isomorphic_duplicate": len(members) > 1,
        "duplicate_of": primary if puzzle_id != primary else None,
        "canonical_path": path,
    }


def _to_json_value(value):
    """Converte ricorsivamente array, tuple e insiemi in valori JSON."""
    if isinstance(value, np.ndarray):
        return value.tolist()

    if isinstance(value, np.generic):
        return value.item()

    if isinstance(value, (set, frozenset)):
        return sorted(_to_json_value(item) for item in value)

    if isinstance(value, tuple):
        return [_to_json_value(item) for item in value]

    if isinstance(value, list):
        return [_to_json_value(item) for item in value]

    if isinstance(value, dict):
        return {
            str(key): _to_json_value(item)
            for key, item in value.items()
        }

    if value is None or isinstance(value, (str, int, float, bool)):
        return value

    raise TypeError(
        f"Impossibile salvare il tipo {type(value).__name__} nel JSON."
    )


def _restore_candidates(candidates):
    if candidates is None:
        return None

    return [
        [set(int(value) for value in cell) for cell in row]
        for row in candidates
    ]


def _migrate_legacy_complete_tree_move(move):
    """Rinomina solo le prove esaustive prodotte prima di P04."""
    migrated = dict(move)
    logic = dict(migrated.get("logic", {}) or {})

    if logic.get("kind") != "nested-complete-contradiction":
        return migrated

    definition = technique_catalog.resolve_legacy_technique(
        migrated.get("technique", "Nested Forcing Chain")
    )
    migrated.update({
        "technique_id": definition.id,
        "technique": definition.canonical_name,
        "family": technique_catalog.TECHNIQUE_FAMILY[
            definition.canonical_name
        ],
        "strategy": technique_catalog.TECHNIQUE_STRATEGY[
            definition.canonical_name
        ],
        "parent_id": definition.parent_id,
        "se_equivalent_parent_id": definition.se_equivalent_parent_id,
        "rating_kind": definition.rating_kind,
        "detector_id": definition.detector_id,
        "engine_type": definition.engine_type,
        "inference_engine": definition.inference_engine,
        "fallback_tier": definition.fallback_tier,
        "base_difficulty": definition.base_difficulty,
    })
    logic["kind"] = "complete-forcing-tree-contradiction"
    logic["exhaustive"] = True
    migrated["logic"] = logic
    return migrated


def _migrate_catalog_identity(move):
    """Allinea ID e assi strutturali senza ritarare i valori storici."""
    migrated = dict(move)
    technique_id = migrated.get("technique_id")
    try:
        if technique_id:
            definition = technique_catalog.resolve_legacy_technique_id(
                technique_id
            )
        else:
            definition = technique_catalog.resolve_technique(
                migrated["technique"]
            )
    except (KeyError, TypeError, ValueError):
        return migrated

    migrated.update({
        "technique_id": definition.id,
        "technique": definition.canonical_name,
        "family": technique_catalog.TECHNIQUE_FAMILY[
            definition.canonical_name
        ],
        "strategy": technique_catalog.TECHNIQUE_STRATEGY[
            definition.canonical_name
        ],
        "parent_id": definition.parent_id,
        "se_equivalent_parent_id": definition.se_equivalent_parent_id,
        "rating_kind": definition.rating_kind,
        "detector_id": definition.detector_id,
        "engine_type": definition.engine_type,
        "inference_engine": definition.inference_engine,
        "fallback_tier": definition.fallback_tier,
    })
    return migrated


def _restore_move(move):
    """Ripristina i tipi usati dalle funzioni di visualizzazione."""
    restored = _migrate_catalog_identity(
        _migrate_legacy_complete_tree_move(move)
    )

    restored["placements"] = [
        tuple(int(value) for value in placement)
        for placement in restored.get("placements", [])
    ]

    restored["eliminations"] = [
        tuple(int(value) for value in elimination)
        for elimination in restored.get("eliminations", [])
    ]

    highlight = restored.get("highlight", {})

    restored["highlight"] = {
        key: [
            tuple(int(value) for value in cell)
            for cell in highlight.get(key, [])
        ]
        for key in ("implication", "effect", "primary", "secondary")
    }

    for field in ("grid_before", "grid_after"):
        if restored.get(field) is not None:
            restored[field] = normalise_sudoku_grid(restored[field])

    for field in ("candidates_before", "candidates_after"):
        if field in restored:
            restored[field] = _restore_candidates(restored[field])

    return restored


def _restore_analysis(data):
    analysis = dict(data)

    analysis["original"] = normalise_sudoku_grid(
        analysis["original"]
    )

    analysis["solved_grid"] = normalise_sudoku_grid(
        analysis["solved_grid"]
    )

    analysis["chain"] = [
        _restore_move(move)
        for move in analysis.get("chain", [])
    ]

    return analysis


_STORED_MOVE_FIELDS = (
    "technique_id",
    "technique",
    "family",
    "strategy",
    "parent_id",
    "se_equivalent_parent_id",
    "rating_kind",
    "detector_id",
    "engine_type",
    "inference_engine",
    "fallback_tier",
    "base_difficulty",
    "difficulty_extra",
    "difficulty_metrics",
    "technical_difficulty",
    "resolution_load",
    "move_discovery_difficulty",
    "description",
    "explanation",
    "placements",
    "eliminations",
    "highlight",
    "visual_evidence",
    "logic",
    "fish_pattern",
    "fish_size",
    "base_set_count",
    "cover_set_count",
    "fin_count",
    "endo_fin_count",
    "cannibalistic_count",
    "als_pattern",
    "als_parent_technique_id",
    "als_node_count",
    "rcc_count",
    "template_pattern",
    "template_count",
    "template_digit",
    "kraken_pattern",
    "kraken_branch_count",
    "coloring_pattern",
    "color_digit",
    "color_component_count",
    "color_node_count",
    "color_link_count",
    "proof_count",
    "conclusion_count",
    "step",
    "grid_before",
    "grid_after",
    "candidates_before",
    "candidates_after",
    "available_move_count",
    "frontier_move_count",
    "effective_move_count",
    "available_by_technique",
    "frontier_by_technique",
    "fallback_tier_used",
    "fallback_stage",
    "fallback_reason",
    "nested_fallback_attempted",
    "nested_fallback_used",
    "complete_tree_fallback_attempted",
    "complete_tree_fallback_used",
    "move_inventory_censored",
    "effective_move_count_is_lower_bound",
    "move_discovery_difficulty_is_upper_bound",
    "capped_techniques",
)

def _compact_analysis_for_storage(analysis):
    """
    Produce il formato JSON semplice usato su disco.

    Le griglie diventano stringhe da 81 cifre e ogni mossa conserva soltanto
    i campi necessari a player, rating e heatmap.
    """
    compact = _to_json_value(analysis)

    for field in ("original", "solved_grid"):
        if compact.get(field) is not None:
            compact[field] = _grid_to_string(compact[field])

    original = normalise_sudoku_grid(compact["original"])
    if sds.count_solutions(original, limit=2) != 1:
        raise ValueError(
            "Impossibile migrare un'analisi di un Sudoku non univoco."
        )
    compact["unique_solution"] = True
    compact["uniqueness_status"] = sds.UNIQUENESS_VERIFIED
    compact["solved_grid"] = _grid_to_string(
        sds.backtracking_solve(original)
    )

    for field in ("puzzle_id", "canonical_id", "analysis_variant"):
        compact.pop(field, None)

    migrated_chain = []
    for source_move in compact.get("chain", []):
        move = _migrate_catalog_identity(
            _migrate_legacy_complete_tree_move(source_move)
        )
        if "technical_difficulty" in move:
            technical_difficulty = float(
                move["technical_difficulty"]
            )
        elif "difficulty" in move:
            technical_difficulty = float(
                move["difficulty"]
            )
        else:
            technical_difficulty = (
                difficulty_model.technique_difficulty(
                    move["technique"]
                )
            )

        resolution_load = (
            difficulty_model.step_resolution_load(
                technical_difficulty
            )
        )


        availability = move.get("availability", {})
        available_entries = availability.get("by_technique", {})
        frontier_entries = availability.get(
            "frontier",
            {},
        ).get("by_technique", {})

        def old_metric_map(entries):
            result = {}
            for technique, values in entries.items():
                if isinstance(values, dict):
                    value = values.get(
                        "distinct_outcome_count",
                        values.get("conclusion_count", 0),
                    )
                else:
                    value = values
                value = min(int(value), ss.MAX_MOVES_PER_TECHNIQUE)
                if value > 0:
                    result[str(technique)] = value
            return result

        available_by_technique = old_metric_map(
            move.get("available_by_technique", {})
            or move.get("applicable_by_technique", {})
            or available_entries
        )
        frontier_by_technique = old_metric_map(
            move.get("frontier_by_technique", {})
            or move.get("best_applicable_by_technique", {})
            or frontier_entries
        )
        available_move_count = max(
            1,
            int(
                move.get(
                    "available_move_count",
                    move.get(
                        "n_distinct_outcomes",
                        move.get("n_alternatives", 1),
                    ),
                )
            ),
        )
        frontier_move_count = max(
            1,
            int(
                move.get(
                    "frontier_move_count",
                    move.get(
                        "n_best_distinct_outcomes",
                        move.get("n_best_alternatives", 1),
                    ),
                )
            ),
        )
        effective_move_count = float(
            move.get(
                "effective_move_count",
                frontier_move_count,
            )
        )

        effective_move_count = max(
            1.0,
            effective_move_count,
        )

        move_discovery_difficulty = float(
            move.get(
                "move_discovery_difficulty",
                difficulty_model.step_move_discovery_difficulty(
                    effective_move_count=effective_move_count,
                    max_moves=ss.MAX_MOVES_PER_TECHNIQUE,
                ),
            )
        )
        
        
        migrated = {
            key: move[key]
            for key in _STORED_MOVE_FIELDS
            if key in move
        }
        migrated.update({
            "technical_difficulty": technical_difficulty,
            "resolution_load": resolution_load,
            "effective_move_count": effective_move_count,
            "move_discovery_difficulty": move_discovery_difficulty,
            "available_move_count": available_move_count,
            "frontier_move_count": frontier_move_count,
            "available_by_technique": available_by_technique,
            "frontier_by_technique": frontier_by_technique,
        })
        
        capped = set(move.get("capped_techniques", ()))
        capped.update(
            technique
            for technique, values in (
                move.get("applicable_by_technique", {})
                or available_entries
            ).items()
            if int(
                values.get("distinct_outcome_count", 0)
                if isinstance(values, dict)
                else values
            ) > ss.MAX_MOVES_PER_TECHNIQUE
        )
        if capped:
            migrated["capped_techniques"] = sorted(capped)

        if migrated.get("grid_after") is not None:
            migrated["grid_after"] = _grid_to_string(
                migrated["grid_after"]
            )
        migrated_chain.append(migrated)

    compact["chain"] = migrated_chain
    compact["grading"] = ss.grade_difficulty(
        migrated_chain,
        compact.get("status", "stuck"),
    )
    allowed_analysis_fields = {
        "name",
        "original",
        "solved_grid",
        "unique_solution",
        "uniqueness_status",
        "chain",
        "status",
        "grading",
        "analysis_mode",
        "profile_difficulty_window",
    }
    return {
        key: value
        for key, value in compact.items()
        if key in allowed_analysis_fields
    }


def compact_analysis_archive(dry_run=True):
    """
    Converte i file di analisi esistenti nel formato compatto corrente.

    Il contenuto logico e la versione del solver non cambiano. Con
    ``dry_run=True`` restituisce soltanto la stima delle dimensioni.
    """
    if not isinstance(dry_run, bool):
        raise TypeError("dry_run deve essere booleano.")

    _ensure_sudoku_directories()
    paths = sorted(SUDOKU_ANALYSES_DIR.glob("*/analysis*.json"))
    before_bytes = 0
    after_bytes = 0
    rewritten_files = 0
    invalid_files = []

    for path in paths:
        payload = _read_json(path)
        original_size = path.stat().st_size
        before_bytes += original_size
        compact_payload = dict(payload)
        compact_payload["schema_version"] = ANALYSIS_SCHEMA_VERSION
        compact_payload["analysis_version"] = ANALYSIS_VERSION
        try:
            compact_payload["analysis"] = _compact_analysis_for_storage(
                payload.get("analysis", {})
            )
        except (KeyError, TypeError, ValueError) as error:
            invalid_files.append({
                "path": str(path),
                "reason": str(error),
            })
            after_bytes += original_size
            continue
        encoded = json.dumps(
            compact_payload,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
        after_bytes += len(encoded)

        if not dry_run:
            _write_json(path, compact_payload, compact=True)
            rewritten_files += 1

    return {
        "dry_run": dry_run,
        "file_count": len(paths),
        "valid_file_count": len(paths) - len(invalid_files),
        "invalid_file_count": len(invalid_files),
        "invalid_files": invalid_files,
        "rewritten_file_count": rewritten_files,
        "before_bytes": before_bytes,
        "after_bytes": after_bytes,
        "saved_bytes": before_bytes - after_bytes,
        "saved_ratio": (
            (before_bytes - after_bytes) / before_bytes
            if before_bytes
            else 0.0
        ),
    }


def _resolve_puzzle_path(reference):
    """
    Trova un Sudoku tramite:
    - identificatore;
    - nome del file;
    - percorso completo;
    - nome assegnato al Sudoku.
    """
    _ensure_sudoku_directories()

    direct_path = Path(reference)

    if direct_path.is_file():
        return direct_path

    candidate = SUDOKU_PUZZLES_DIR / str(reference)

    if candidate.is_file():
        return candidate

    if candidate.suffix != ".json":
        candidate = candidate.with_suffix(".json")

    if candidate.is_file():
        return candidate

    reference_name = str(reference).casefold()
    matching_paths = []

    for path in SUDOKU_PUZZLES_DIR.glob("*.json"):
        data = _read_json(path)

        if str(data.get("name", "")).casefold() == reference_name:
            matching_paths.append(path)

    if len(matching_paths) == 1:
        return matching_paths[0]

    if len(matching_paths) > 1:
        raise ValueError(
            f"Esistono più Sudoku con il nome {reference!r}. "
            "Usa il loro identificatore."
        )

    raise FileNotFoundError(
        f"Sudoku non trovato: {reference!r}."
    )


# ---------------------------------------------------------------------------
# Salvataggio e caricamento dei Sudoku
# ---------------------------------------------------------------------------

_LEGACY_EMPTY_METADATA_VALUES = {
    "nessun_riferimento",
    "non_indicata",
    "non_indicato",
    "none",
    "null",
}


def _clean_optional_text(value):
    """Normalizza un testo facoltativo e converte i placeholder in None."""
    if value is None:
        return None

    text = str(value).strip()

    if not text or text.casefold() in _LEGACY_EMPTY_METADATA_VALUES:
        return None

    return text



def _normalise_puzzle_metadata(metadata):
    """Rimuove campi vuoti senza alterare numeri, booleani o strutture."""
    if not metadata:
        return {}

    cleaned = {}

    for key, value in dict(metadata).items():
        key = str(key).strip()

        if not key or value is None:
            continue

        if isinstance(value, str):
            value = _clean_optional_text(value)

            if value is None:
                continue

        elif isinstance(value, (list, tuple, set, dict)) and not value:
            continue

        cleaned[key] = value

    return cleaned


def _merge_puzzle_metadata(existing_metadata, incoming_metadata):
    """Unisce i metadati preservando la provenienza fotografica.

    I nuovi valori non vuoti sostituiscono quelli omonimi già salvati. I
    campi assenti non cancellano il contenuto precedente. Per il metodo di
    inserimento, ``photo`` ha priorità su ``manual``: un reinvio manuale non
    può perdere il collegamento alla foto, mentre una foto può promuovere un
    record nato manualmente.
    """
    stored = _normalise_puzzle_metadata(existing_metadata)
    incoming = _normalise_puzzle_metadata(incoming_metadata)

    # Il titolo autorevole vive nel campo principale ``name``.
    stored.pop("title", None)
    incoming.pop("title", None)

    stored_photo_id = _clean_optional_text(stored.get("photo_id"))
    incoming_photo_id = _clean_optional_text(incoming.get("photo_id"))

    # Un photo_id e' una prova piu' forte di input_method. Questo sistema
    # anche i record legacy che avevano photo_id ma non input_method e rende
    # innocue eventuali richieste contraddittorie photo_id + manual.
    if stored_photo_id:
        stored["photo_id"] = stored_photo_id
        stored["input_method"] = "photo"

    if incoming_photo_id:
        incoming["photo_id"] = incoming_photo_id
        incoming["input_method"] = "photo"

    previous_method = str(stored.get("input_method", "")).strip().casefold()
    incoming_method = str(incoming.get("input_method", "")).strip().casefold()

    if previous_method in {"manual", "photo"}:
        stored["input_method"] = previous_method
    if incoming_method in {"manual", "photo"}:
        incoming["input_method"] = incoming_method

    if previous_method == "photo" and incoming_method == "manual":
        incoming.pop("input_method", None)
        incoming.pop("photo_id", None)

    stored.update(incoming)

    # photo_id ha senso soltanto quando la provenienza effettiva e' photo.
    effective_method = str(stored.get("input_method", "")).strip().casefold()
    if effective_method == "photo":
        stored["input_method"] = "photo"
    else:
        if effective_method == "manual":
            stored["input_method"] = "manual"
        stored.pop("photo_id", None)

    return stored


def save_sudoku(grid, name=None, metadata=None):
    """
    Salva un Sudoku nella cartella puzzles.

    ``id`` identifica la disposizione concreta; ``canonical_id`` identifica
    la classe isomorfa. Se la stessa griglia esiste già, aggiorna solamente
    nome e metadati. Un nuovo isomorfo resta una variante distinta, ma viene
    collegato alla stessa classe canonica.
    """
    _ensure_sudoku_directories()

    grid = validate_unique_sudoku(grid)
    puzzle_id = sudoku_id(grid)
    path = _puzzle_path(puzzle_id)

    existing = _read_json(path) if path.exists() else {}
    canonical_fields = _canonical_fields(grid, existing)

    incoming_metadata = _normalise_puzzle_metadata(metadata)
    metadata_title = _clean_optional_text(
        incoming_metadata.get("title")
    )
    stored_metadata = _merge_puzzle_metadata(
        existing.get("metadata", {}),
        incoming_metadata,
    )

    stored_name = (
        _clean_optional_text(name)
        or metadata_title
        or existing.get("name")
        or f"sudoku_{puzzle_id[:8]}"
    )

    payload = {
        "schema_version": PUZZLE_SCHEMA_VERSION,
        "id": puzzle_id,
        "name": stored_name,
        "grid": _grid_to_string(grid),
        "clues": int(np.count_nonzero(grid)),
        "unique_solution": True,
        "metadata": _to_json_value(stored_metadata),
        **canonical_fields,
        "created_at": existing.get(
            "created_at",
            _current_timestamp(),
        ),
        "updated_at": _current_timestamp(),
    }

    _write_json(path, payload)

    # Verifica nel punto autorevole: il file appena scritto su disco.
    # Questo evita controlli falsi basati su oggetti intermedi del servizio
    # web, che possono essere sintetici o non ancora ricaricati.
    persisted = _read_json(path)
    if persisted.get("metadata", {}) != payload["metadata"]:
        raise RuntimeError(
            "I metadati del Sudoku non sono stati persistiti correttamente."
        )
    if persisted.get("name") != payload["name"]:
        raise RuntimeError(
            "Il nome del Sudoku non e stato persistito correttamente."
        )

    _register_canonical_variant(payload)

    return {
        **payload,
        **_canonical_class_info(payload),
        "grid": grid,
        "path": path,
    }


def save_with_standard_nomenclature(
    grid,
    provenience=None,
    tag=None,
    difficulty=None,
    metadata=None,
    name=None,
    input_method=None,
    photo_id=None,
):
    """
    Salva un Sudoku accettando anche i vecchi parametri della web API.

    Tutti i dati editoriali sono facoltativi. ``provenience``, ``tag`` e
    ``difficulty`` restano supportati per compatibilità, ma vengono salvati
    con nomi comprensibili: ``source``, ``source_reference`` e
    ``stated_difficulty``. I valori vuoti non vengono scritti nel JSON.

    Se la griglia esiste già, i nuovi metadati vengono uniti al record
    esistente invece di essere ignorati.
    """
    complete_metadata = _normalise_puzzle_metadata(metadata)

    source = _clean_optional_text(provenience)
    source_reference = _clean_optional_text(tag)
    stated_difficulty = _clean_optional_text(difficulty)
    legacy_input_method = _clean_optional_text(input_method)
    legacy_photo_id = _clean_optional_text(photo_id)

    if legacy_input_method:
        complete_metadata.setdefault(
            "input_method",
            legacy_input_method,
        )

    if legacy_photo_id:
        complete_metadata.setdefault("photo_id", legacy_photo_id)
        complete_metadata["input_method"] = "photo"

    # Il vecchio client usava "web" come provenienza tecnica. Ora questo
    # concetto è rappresentato da entry_channel e non viene confuso con la
    # vera fonte editoriale, salvo che il client invii esplicitamente source.
    if (
        source
        and not (
            source.casefold() == "web"
            and complete_metadata.get("entry_channel") == "web"
            and "source" not in complete_metadata
        )
    ):
        complete_metadata.setdefault("source", source)

    if source_reference:
        complete_metadata.setdefault(
            "source_reference",
            source_reference,
        )

    if stated_difficulty:
        complete_metadata.setdefault(
            "stated_difficulty",
            stated_difficulty,
        )

    requested_name = (
        _clean_optional_text(name)
        or _clean_optional_text(complete_metadata.get("title"))
    )

    return save_sudoku(
        grid,
        name=requested_name,
        metadata=complete_metadata,
    )

    

def load_sudoku(reference):
    """
    Carica un Sudoku tramite identificatore, nome o percorso.

    Restituisce un dizionario con griglia NumPy e metadati.
    """
    path = _resolve_puzzle_path(reference)
    payload = _read_json(path)

    if payload.get("schema_version", 1) not in (1, 2, PUZZLE_SCHEMA_VERSION):
        raise ValueError(
            f"Versione del file Sudoku non supportata: "
            f"{payload.get('schema_version')}."
        )

    grid = normalise_sudoku_grid(payload["grid"])
    payload["unique_solution"] = (
        sds.count_solutions(grid, limit=2) == 1
    )

    if not payload.get("canonical_id"):
        # Compatibilità di lettura con lo schema 1. La migrazione esplicita
        # persiste questi campi senza modificare date, nomi o analisi.
        payload = {
            **payload,
            **_canonical_fields(grid),
        }

    return {
        **payload,
        **_canonical_class_info(payload),
        "grid": grid,
        "path": path,
    }


def delete_sudoku(reference):
    """
    Elimina completamente un Sudoku concreto dall'archivio.

    ``reference`` accetta gli stessi identificatori di :func:`load_sudoku`:
    ID, nome assegnato oppure percorso del JSON interno all'archivio.

    Vengono eliminati il record del puzzle, tutte le sue analisi su disco e
    le corrispondenti entry della cache in memoria. L'indice canonico viene
    aggiornato sulle varianti isomorfe rimaste oppure rimosso se la classe
    resta vuota.

    Restituisce un rapporto con l'identità eliminata e lo stato finale della
    classe canonica. Un riferimento inesistente solleva ``FileNotFoundError``.
    """
    path = _resolve_puzzle_path(reference)
    resolved_path = path.resolve()
    puzzles_root = SUDOKU_PUZZLES_DIR.resolve()

    if resolved_path.parent != puzzles_root:
        raise ValueError(
            "È possibile eliminare solamente file contenuti nella cartella "
            "puzzles dell'archivio."
        )

    payload = _read_json(resolved_path)
    puzzle_id = resolved_path.stem
    stored_id = str(payload.get("id", puzzle_id))

    if stored_id != puzzle_id:
        raise ValueError(
            "Record Sudoku non coerente: l'ID interno non coincide con "
            "il nome del file."
        )

    grid = normalise_sudoku_grid(payload["grid"])

    if payload.get("canonical_id") and payload.get("canonical_grid"):
        canonical_fields = {
            "canonical_id": str(payload["canonical_id"]),
            "canonical_grid": str(payload["canonical_grid"]),
        }
    else:
        calculated = _canonical_fields(grid)
        canonical_fields = {
            "canonical_id": calculated["canonical_id"],
            "canonical_grid": calculated["canonical_grid"],
        }

    canonical_id = canonical_fields["canonical_id"]

    if (
        len(canonical_id) != 64
        or any(character not in "0123456789abcdef" for character in canonical_id)
    ):
        raise ValueError(
            "Record Sudoku non coerente: canonical_id non valido."
        )

    if sc.canonical_id_from_string(
        canonical_fields["canonical_grid"]
    ) != canonical_id:
        raise ValueError(
            "Record Sudoku non coerente: canonical_grid e canonical_id "
            "non corrispondono."
        )

    analysis_directory = _analysis_directory(puzzle_id)
    resolved_analysis_directory = analysis_directory.resolve()
    analyses_root = SUDOKU_ANALYSES_DIR.resolve()

    if resolved_analysis_directory.parent != analyses_root:
        raise RuntimeError(
            "Percorso delle analisi non sicuro; cancellazione interrotta."
        )

    deleted_analysis_file_count = 0

    if resolved_analysis_directory.exists():
        deleted_analysis_file_count = sum(
            1
            for item in resolved_analysis_directory.rglob("*")
            if item.is_file()
        )
        shutil.rmtree(resolved_analysis_directory)

    cache_keys = [
        key
        for key in _ANALYSIS_MEMORY_CACHE
        if key[0] == puzzle_id
    ]

    for key in cache_keys:
        _ANALYSIS_MEMORY_CACHE.pop(key, None)

    resolved_path.unlink()

    canonical_payload = _unregister_canonical_variant({
        **payload,
        **canonical_fields,
        "id": puzzle_id,
    })
    remaining_ids = (
        canonical_payload.get("variant_ids", [])
        if canonical_payload is not None
        else []
    )

    return {
        "deleted": True,
        "id": puzzle_id,
        "name": payload.get("name"),
        "canonical_id": canonical_id,
        "deleted_puzzle_path": resolved_path,
        "deleted_analysis_directory": resolved_analysis_directory,
        "deleted_analysis_file_count": deleted_analysis_file_count,
        "cleared_memory_cache_entry_count": len(cache_keys),
        "canonical_class_deleted": canonical_payload is None,
        "remaining_isomorphic_variant_ids": list(remaining_ids),
        "remaining_isomorphic_variant_count": len(remaining_ids),
    }


def load_last_sudoku():
    """
    Carica il Sudoku salvato o aggiornato più recentemente.

    Restituisce lo stesso dizionario prodotto da load_sudoku().
    """
    _ensure_sudoku_directories()

    latest_path = None
    latest_timestamp = None

    for path in SUDOKU_PUZZLES_DIR.glob("*.json"):
        payload = _read_json(path)
        timestamp = (
            payload.get("updated_at")
            or payload.get("created_at")
        )

        if timestamp is None:
            continue

        try:
            parsed_timestamp = datetime.fromisoformat(timestamp)
        except (TypeError, ValueError):
            continue

        if (
            latest_timestamp is None
            or parsed_timestamp > latest_timestamp
        ):
            latest_timestamp = parsed_timestamp
            latest_path = path

    if latest_path is None:
        raise FileNotFoundError(
            "Non è stato ancora salvato alcun Sudoku."
        )

    return load_sudoku(latest_path)


def list_sudokus(
    number=None,
    method="all",
    comparison_value=0,
):
    """
    Restituisce un elenco sintetico dei Sudoku salvati.

    ``analysed`` indica che esiste almeno una variante corrente. Sono inoltre
    esposti ``analysed_deep``, ``analysed_profile``,
    ``analysed_superficial`` e l elenco ``analysis_variants``.

    Le chiavi numeriche di grading sono prese preferibilmente dalla deep,
    poi da profile e infine da superficial.
    """
    _ensure_sudoku_directories()

    if number is not None:
        if isinstance(number, bool) or not isinstance(number, int):
            raise TypeError(
                "number deve essere un intero positivo oppure None."
            )

        if number <= 0:
            raise ValueError(
                "number deve essere maggiore di zero."
            )

    if not isinstance(method, str):
        raise TypeError("method deve essere una stringa.")

    method = method.casefold()

    if method == "hardest":
        return list_sudokus(
            number,
            "resolution_load",
            99,
        )

    if method == "easiest":
        return list_sudokus(
            number,
            "resolution_load",
            0,
        )

    results = []

    for path in SUDOKU_PUZZLES_DIR.glob("*.json"):
        payload = _read_json(path)
        puzzle_id = payload["id"]
        canonical_info = _canonical_class_info(payload)
        variants = _current_analysis_payloads(puzzle_id)

        modes = {
            item["analysis_mode"]
            for item in variants.values()
        }

        preferred_variant = None

        if "deep" in variants:
            preferred_variant = variants["deep"]
        else:
            profile_variants = [
                item
                for item in variants.values()
                if item["analysis_mode"] == "profile"
            ]

            if profile_variants:
                preferred_variant = sorted(
                    profile_variants,
                    key=lambda item: item[
                        "profile_difficulty_window"
                    ],
                    reverse=True,
                )[0]
            elif variants:
                preferred_variant = next(iter(variants.values()))

        grading = {}

        if preferred_variant is not None:
            grading = (
                preferred_variant["payload"]
                .get("analysis", {})
                .get("grading", {})
            )

        result = {
            "id": puzzle_id,
            "canonical_id": payload.get("canonical_id"),
            "name": payload.get("name"),
            "clues": payload.get("clues"),
            "technical_difficulty_label": grading.get(
                "technical_difficulty_label"
            ),
            "hardest_technique": grading.get("hardest_technique"),
            "move_discovery_difficulty_label": grading.get(
                "move_discovery_difficulty_label"
            ),
            "unique_solution": payload.get("unique_solution"),
            "is_canonical": payload.get("is_canonical"),
            "isomorphic_variant_count": canonical_info.get(
                "isomorphic_variant_count",
                1,
            ),
            "is_isomorphic_duplicate": canonical_info.get(
                "is_isomorphic_duplicate",
                False,
            ),
            "duplicate_of": canonical_info.get("duplicate_of"),
            "analysed": bool(variants),
            "analysed_deep": "deep" in modes,
            "analysed_profile": "profile" in modes,
            "analysed_superficial": "superficial" in modes,
            "analysis_modes": sorted(modes),
            "analysis_variants": sorted(variants),
            "created_at": payload.get("created_at"),
            "updated_at": payload.get("updated_at"),
        }

        result.update({
            key: value
            for key, value in grading.items()
            if isinstance(
                value,
                (int, float, np.integer, np.floating),
            )
            and not isinstance(value, bool)
        })

        results.append(result)

    if method == "random":
        random.shuffle(results)

    elif method == "latest":
        def timestamp_key(item):
            timestamp = (
                item.get("updated_at")
                or item.get("created_at")
                or ""
            )

            try:
                return datetime.fromisoformat(timestamp)
            except (TypeError, ValueError):
                return datetime.min.replace(tzinfo=timezone.utc)

        results.sort(key=timestamp_key, reverse=True)

    elif method == "all":
        results.sort(
            key=lambda item: (
                str(item["name"]).casefold(),
                item["id"],
            )
        )

    else:
        if isinstance(comparison_value, bool) or not isinstance(
            comparison_value,
            (int, float, np.integer, np.floating),
        ):
            raise TypeError("comparison_value deve essere numerico.")

        comparable_results = [
            item
            for item in results
            if method in item
        ]

        if not comparable_results:
            raise ValueError(
                f"Nessuna analisi contiene una chiave numerica "
                f"{method!r}."
            )

        target = float(comparison_value)
        comparable_results.sort(
            key=lambda item: (
                abs(float(item[method]) - target),
                float(item[method]),
                str(item["name"]).casefold(),
                item["id"],
            )
        )
        results = comparable_results

    if number is not None:
        results = results[:number]

    return results


def load_canonical_class(reference):
    """
    Carica la classe isomorfa di un ID canonico, Sudoku salvato o griglia.

    Il risultato contiene la forma MinLex autorevole e l'elenco sintetico
    delle varianti concrete, ognuna delle quali continua a essere caricabile
    e analizzabile tramite il proprio ``id``.
    """
    _ensure_sudoku_directories()

    if (
        isinstance(reference, str)
        and len(reference) == 64
        and all(character in "0123456789abcdef" for character in reference)
        and _canonical_path(reference).exists()
    ):
        canonical_id = reference
    elif isinstance(reference, str) and not _looks_like_grid_string(reference):
        canonical_id = load_sudoku(reference)["canonical_id"]
    else:
        canonical_id = canonical_sudoku_id(reference)

    path = _canonical_path(canonical_id)

    if not path.exists():
        raise FileNotFoundError(
            f"Classe canonica non indicizzata: {canonical_id}. "
            "Esegui migrate_canonical_archive(dry_run=False) per i record "
            "creati con lo schema precedente."
        )

    payload = _read_json(path)
    variants = []

    for puzzle_id in payload.get("variant_ids", []):
        puzzle_path = _puzzle_path(puzzle_id)

        if not puzzle_path.exists():
            continue

        puzzle = _read_json(puzzle_path)
        variants.append({
            "id": puzzle_id,
            "name": puzzle.get("name"),
            "grid": puzzle.get("grid"),
            "clues": puzzle.get("clues"),
            "metadata": puzzle.get("metadata", {}),
            "is_canonical": puzzle.get("is_canonical", False),
            "created_at": puzzle.get("created_at"),
            "updated_at": puzzle.get("updated_at"),
        })

    return {
        **payload,
        "variants": variants,
        "path": path,
    }


def find_isomorphic_sudokus(reference):
    """Restituisce tutti i record concreti appartenenti alla stessa classe."""
    canonical_class = load_canonical_class(reference)

    return [
        load_sudoku(puzzle_id)
        for puzzle_id in canonical_class.get("variant_ids", [])
        if _puzzle_path(puzzle_id).exists()
    ]


def migrate_canonical_archive(dry_run=True, workers=None):
    """
    Migra in modo non distruttivo i puzzle legacy allo schema canonico.

    ``dry_run=True`` calcola e restituisce il rapporto senza modificare file.
    Con ``False`` aggiorna ogni JSON in-place conservando ID, nome, griglia,
    metadati e timestamp, quindi costruisce gli indici di classe. ``workers``
    limita i calcoli MinLex paralleli; il valore automatico non supera quattro.
    """
    if not isinstance(dry_run, bool):
        raise TypeError("dry_run deve essere booleano.")

    _ensure_sudoku_directories()
    paths = sorted(SUDOKU_PUZZLES_DIR.glob("*.json"))
    payloads = [(path, _read_json(path)) for path in paths]

    if workers is None:
        workers = min(4, max(len(payloads), 1))

    if (
        isinstance(workers, bool)
        or not isinstance(workers, int)
        or workers < 1
    ):
        raise ValueError("workers deve essere un intero maggiore di zero.")

    def prepare_record(item):
        path, payload = item
        version = payload.get("schema_version", 1)

        if version not in (1, 2, PUZZLE_SCHEMA_VERSION):
            raise ValueError(
                f"Versione puzzle non supportata in {path}: {version}."
            )

        try:
            grid = validate_unique_sudoku(payload["grid"])
        except (TypeError, ValueError) as error:
            return {
                "valid": False,
                "path": path,
                "id": str(payload.get("id", path.stem)),
                "name": payload.get("name"),
                "reason": str(error),
            }
        canonical_fields = _canonical_fields(grid, payload)
        return {
            "valid": True,
            "path": path,
            "payload": payload,
            "updated": {
                **payload,
                "schema_version": PUZZLE_SCHEMA_VERSION,
                "unique_solution": True,
                **canonical_fields,
            },
        }

    if workers == 1 or len(payloads) < 2:
        prepared = [prepare_record(item) for item in payloads]
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            prepared = list(executor.map(prepare_record, payloads))

    invalid_puzzles = [
        {
            "id": item["id"],
            "name": item["name"],
            "path": str(item["path"]),
            "reason": item["reason"],
        }
        for item in prepared
        if not item["valid"]
    ]
    prepared_records = []
    classes = {}
    updated_files = 0

    for item in prepared:
        if not item["valid"]:
            continue
        path = item["path"]
        payload = item["payload"]
        updated = item["updated"]
        if updated != payload:
            updated_files += 1

        canonical_id = updated["canonical_id"]
        canonical_grid = updated["canonical_grid"]
        canonical_class = classes.setdefault(
            canonical_id,
            {
                "canonical_grid": canonical_grid,
                "records": [],
            },
        )

        if canonical_class["canonical_grid"] != canonical_grid:
            raise RuntimeError(
                "Collisione dell'indice canonico durante la migrazione: "
                f"{canonical_id}."
            )

        canonical_class["records"].append(updated)
        prepared_records.append((path, updated))

    timestamp = _current_timestamp()
    duplicate_classes = []
    class_payloads = []

    for canonical_id, canonical_class in sorted(classes.items()):
        records = canonical_class["records"]
        variant_ids = sorted(str(record["id"]) for record in records)
        existing_path = _canonical_path(canonical_id)
        existing = (
            _read_json(existing_path)
            if existing_path.exists()
            else {}
        )
        created_candidates = [
            record.get("created_at")
            for record in records
            if record.get("created_at")
        ]
        created_at = existing.get("created_at")

        if created_at is None:
            created_at = (
                min(created_candidates)
                if created_candidates
                else timestamp
            )

        class_payload = {
            "schema_version": CANONICAL_CLASS_SCHEMA_VERSION,
            "canonicalization_version": sc.CANONICALIZATION_VERSION,
            "canonical_id": canonical_id,
            "canonical_grid": canonical_class["canonical_grid"],
            "primary_puzzle_id": variant_ids[0],
            "variant_ids": variant_ids,
            "variant_count": len(variant_ids),
            "created_at": created_at,
            "updated_at": (
                existing.get("updated_at", timestamp)
                if dry_run
                else timestamp
            ),
        }
        class_payloads.append((existing_path, class_payload))

        if len(variant_ids) > 1:
            duplicate_classes.append({
                "canonical_id": canonical_id,
                "primary_puzzle_id": variant_ids[0],
                "variant_ids": variant_ids,
                "names": sorted(
                    str(record.get("name", record["id"]))
                    for record in records
                ),
            })

    if not dry_run:
        for path, payload in prepared_records:
            _write_json(path, payload)

        for path, payload in class_payloads:
            _write_json(path, payload)

    return {
        "dry_run": dry_run,
        "workers": workers,
        "puzzle_count": len(payloads),
        "valid_puzzle_count": len(prepared_records),
        "invalid_puzzle_count": len(invalid_puzzles),
        "invalid_puzzles": invalid_puzzles,
        "canonical_class_count": len(classes),
        "isomorphic_duplicate_count": (
            len(prepared_records) - len(classes)
        ),
        "duplicate_class_count": len(duplicate_classes),
        "updated_puzzle_file_count": updated_files,
        "canonical_index_file_count": len(class_payloads),
        "duplicate_classes": duplicate_classes,
    }


# ---------------------------------------------------------------------------
# Salvataggio e caricamento delle analisi
# ---------------------------------------------------------------------------

def save_analysis(analysis):
    """Salva una variante di analisi senza sovrascrivere le altre."""
    original = normalise_sudoku_grid(analysis["original"])
    puzzle_id = sudoku_id(original)

    mode, window = _normalise_analysis_request(
        analysis.get("analysis_mode", ss.DEFAULT_ANALYSIS_MODE),
        analysis.get("profile_difficulty_window"),
    )

    analysis = dict(analysis)
    variant = _analysis_variant(mode, window)
    analysis["puzzle_id"] = puzzle_id
    analysis["analysis_variant"] = variant
    analysis["analysis_mode"] = mode
    analysis["profile_difficulty_window"] = window

    stored_puzzle = save_sudoku(
        original,
        name=analysis.get("name"),
    )
    canonical_id = stored_puzzle["canonical_id"]
    analysis["canonical_id"] = canonical_id

    stored_analysis = _compact_analysis_for_storage(analysis)
    payload = {
        "schema_version": ANALYSIS_SCHEMA_VERSION,
        "analysis_version": ANALYSIS_VERSION,
        "puzzle_id": puzzle_id,
        "canonical_id": canonical_id,
        "analysis_variant": variant,
        "analysis_mode": mode,
        "profile_difficulty_window": window,
        "created_at": _current_timestamp(),
        "analysis": stored_analysis,
    }

    path = _analysis_path(puzzle_id, mode, window)
    _write_json(path, payload, compact=True)

    cache_key = _analysis_cache_key(puzzle_id, mode, window)
    cached_analysis = _restore_analysis(stored_analysis)
    cached_analysis["puzzle_id"] = puzzle_id
    cached_analysis["canonical_id"] = canonical_id
    cached_analysis["analysis_variant"] = variant
    _ANALYSIS_MEMORY_CACHE[cache_key] = cached_analysis

    return path


def load_analysis(
    reference,
    analysis_mode=ss.DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=ss.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
):
    """
    Carica la variante richiesta tramite ID, nome o percorso del Sudoku.
    """
    puzzle = load_sudoku(reference)
    puzzle_id = puzzle["id"]
    mode, window = _normalise_analysis_request(
        analysis_mode,
        profile_difficulty_window,
    )
    path = _analysis_path(puzzle_id, mode, window)

    if not path.exists():
        variant = _analysis_variant(mode, window)
        raise FileNotFoundError(
            f"Il Sudoku {puzzle['name']!r} non possiede ancora "
            f"l analisi {variant!r}."
        )

    payload = _read_json(path)

    if not _analysis_payload_is_current(
        payload,
        puzzle_id,
        mode,
        window,
    ):
        raise ValueError(
            "L analisi richiesta appartiene a una versione, un Sudoku "
            "o una variante differente e deve essere ricalcolata."
        )

    analysis = _restore_analysis(payload["analysis"])
    analysis.setdefault("puzzle_id", puzzle_id)
    analysis.setdefault("canonical_id", puzzle["canonical_id"])
    analysis.setdefault(
        "analysis_variant",
        _analysis_variant(mode, window),
    )
    cache_key = _analysis_cache_key(puzzle_id, mode, window)
    _ANALYSIS_MEMORY_CACHE[cache_key] = analysis

    return analysis


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def analyse_puzzle_cached(
    puzzle,
    name=None,
    metadata=None,
    force=False,
    analysis_mode=ss.DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=ss.DEFAULT_PROFILE_DIFFICULTY_WINDOW,
    max_steps=ss.MAX_SOLVER_STEPS,
    verbose=False,
):
    """
    Restituisce e persiste la variante di analisi richiesta.

    Le varianti ``deep``, ``profile`` e ``superficial`` hanno file e chiavi
    di cache distinti. ``profile`` con finestra 1.5 è il default; la ``deep``
    continua a usare il nome storico ``analysis.json``.
    """
    _ensure_sudoku_directories()

    mode, window = _normalise_analysis_request(
        analysis_mode,
        profile_difficulty_window,
    )

    if isinstance(puzzle, str) and not _looks_like_grid_string(puzzle):
        stored_puzzle = load_sudoku(puzzle)
        grid = stored_puzzle["grid"]

        if name is None:
            name = stored_puzzle["name"]

        puzzle_id = stored_puzzle["id"]

    else:
        grid = normalise_sudoku_grid(puzzle)
        stored_puzzle = save_sudoku(
            grid,
            name=name,
            metadata=metadata,
        )
        puzzle_id = stored_puzzle["id"]
        name = stored_puzzle["name"]

    canonical_id = stored_puzzle["canonical_id"]
    cache_key = _analysis_cache_key(puzzle_id, mode, window)

    if not force:
        cached = _ANALYSIS_MEMORY_CACHE.get(cache_key)

        if cached is not None:
            cached.setdefault("canonical_id", canonical_id)
            return cached

        path = _analysis_path(puzzle_id, mode, window)

        if path.exists():
            payload = _read_json(path)

            if _analysis_payload_is_current(
                payload,
                puzzle_id,
                mode,
                window,
            ):
                analysis = _restore_analysis(payload["analysis"])
                analysis.setdefault("puzzle_id", puzzle_id)
                analysis.setdefault("canonical_id", canonical_id)
                analysis.setdefault(
                    "analysis_variant",
                    _analysis_variant(mode, window),
                )
                _ANALYSIS_MEMORY_CACHE[cache_key] = analysis
                return analysis

    analysis = ss.analyse_puzzle(
        grid,
        name=name,
        analysis_mode=mode,
        profile_difficulty_window=(
            window
            if mode == "profile"
            else getattr(
                ss,
                "DEFAULT_PROFILE_DIFFICULTY_WINDOW",
                1.0,
            )
        ),
        max_steps=max_steps,
        verbose=verbose,
    )

    analysis["puzzle_id"] = puzzle_id
    analysis["canonical_id"] = canonical_id
    analysis["analysis_variant"] = _analysis_variant(mode, window)

    save_analysis(analysis)
    return _ANALYSIS_MEMORY_CACHE[cache_key]
