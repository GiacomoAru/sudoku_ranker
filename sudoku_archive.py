

import hashlib
import json
import random
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import sudoku_data_structure as sds
import sudoku_solver as ss

# ---------------------------------------------------------------------------
# Configurazione archivio
# ---------------------------------------------------------------------------

SUDOKU_DATA_DIR = Path("sudoku_data")
SUDOKU_PUZZLES_DIR = SUDOKU_DATA_DIR / "puzzles"
SUDOKU_ANALYSES_DIR = SUDOKU_DATA_DIR / "analyses"

PUZZLE_SCHEMA_VERSION = 1

# Incrementare questo numero quando cambia il funzionamento del solver
# o il formato dell'analisi. Le vecchie analisi verranno ricalcolate.
ANALYSIS_VERSION = 8

# La modalità canonica resta deep. Le altre varianti vengono salvate
# separatamente, senza sovrascrivere l analisi completa.
DEFAULT_ANALYSIS_MODE = "deep"

# Evita anche letture ripetute dal disco durante la stessa esecuzione.
# La chiave è (puzzle_id, analysis_variant), non soltanto puzzle_id.
_ANALYSIS_MEMORY_CACHE = {}


# ---------------------------------------------------------------------------
# Funzioni interne
# ---------------------------------------------------------------------------

def _ensure_sudoku_directories():
    SUDOKU_PUZZLES_DIR.mkdir(parents=True, exist_ok=True)
    SUDOKU_ANALYSES_DIR.mkdir(parents=True, exist_ok=True)


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


def _analysis_directory(puzzle_id):
    return SUDOKU_ANALYSES_DIR / puzzle_id


def _normalise_analysis_request(
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=None,
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
        mode = str(analysis_mode or DEFAULT_ANALYSIS_MODE).strip().lower()
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
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=None,
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
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=None,
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
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=None,
):
    """Restituisce un file distinto per ogni variante di analisi."""
    variant = _analysis_variant(
        analysis_mode,
        profile_difficulty_window,
    )

    # Mantiene il nome storico per la deep, che resta il default.
    filename = (
        "analysis.json"
        if variant == "deep"
        else f"analysis_{variant}.json"
    )

    return _analysis_directory(puzzle_id) / filename


def _analysis_payload_is_current(
    payload,
    puzzle_id,
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=None,
):
    """Verifica versione, Sudoku e variante richiesta."""
    if (
        payload.get("puzzle_id") != puzzle_id
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
        stored_analysis.get("analysis_mode", DEFAULT_ANALYSIS_MODE),
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
                analysis.get("analysis_mode", DEFAULT_ANALYSIS_MODE),
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


def _write_json(path, data):
    """Scrive un JSON in modo atomico per evitare file parziali."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    temporary_path = path.with_suffix(path.suffix + ".tmp")

    temporary_path.write_text(
        json.dumps(
            data,
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    temporary_path.replace(path)


def _read_json(path):
    path = Path(path)

    with path.open("r", encoding="utf-8") as file:
        return json.load(file)


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


def _restore_move(move):
    """Ripristina i tipi usati dalle funzioni di visualizzazione."""
    restored = dict(move)

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
        "primary": [
            tuple(int(value) for value in cell)
            for cell in highlight.get("primary", [])
        ],
        "secondary": [
            tuple(int(value) for value in cell)
            for cell in highlight.get("secondary", [])
        ],
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

    grading = dict(analysis.get("grading", {}))

    grading["histogram"] = {
        int(level): int(count)
        for level, count in grading.get("histogram", {}).items()
    }

    grading["se_histogram"] = {
        float(score): int(count)
        for score, count in grading.get("se_histogram", {}).items()
    }

    analysis["grading"] = grading

    return analysis


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

def save_sudoku(grid, name=None, metadata=None):
    """
    Salva un Sudoku nella cartella puzzles.

    Se il Sudoku esiste già, aggiorna solamente nome e metadati.
    """
    _ensure_sudoku_directories()

    grid = normalise_sudoku_grid(grid)
    puzzle_id = sudoku_id(grid)
    path = _puzzle_path(puzzle_id)

    existing = _read_json(path) if path.exists() else {}

    stored_metadata = dict(existing.get("metadata", {}))

    if metadata:
        stored_metadata.update(metadata)

    stored_name = (
        name
        or existing.get("name")
        or f"sudoku_{puzzle_id[:8]}"
    )

    payload = {
        "schema_version": PUZZLE_SCHEMA_VERSION,
        "id": puzzle_id,
        "name": stored_name,
        "grid": _grid_to_string(grid),
        "clues": int(np.count_nonzero(grid)),
        "metadata": _to_json_value(stored_metadata),
        "created_at": existing.get(
            "created_at",
            _current_timestamp(),
        ),
        "updated_at": _current_timestamp(),
    }

    _write_json(path, payload)

    return {
        **payload,
        "grid": grid,
        "path": path,
    }


def save_with_standard_nomenclature(
    grid,
    provenience,
    tag,
    difficulty,
    metadata=None,
):
    """
    Salva un Sudoku con nome:

        provenience_difficulty_index

    L'indice viene calcolato esclusivamente dai nomi già esistenti.

    Se la stessa griglia è già salvata, restituisce il record esistente
    senza modificarne nome o metadati.
    """
    _ensure_sudoku_directories()

    puzzle_id = sudoku_id(grid)
    existing_path = _puzzle_path(puzzle_id)

    if existing_path.exists():
        return load_sudoku(existing_path)

    prefix = f"{provenience}_{difficulty}_"
    highest_index = -1

    for path in SUDOKU_PUZZLES_DIR.glob("*.json"):
        payload = _read_json(path)
        name = str(payload.get("name", ""))

        if not name.startswith(prefix):
            continue

        index_text = name[len(prefix):]

        if index_text.isdigit():
            highest_index = max(
                highest_index,
                int(index_text),
            )

    index = highest_index + 1
    name = f"{provenience}_{difficulty}_{index}"

    complete_metadata = dict(metadata or {})
    complete_metadata.update({
        "provenience": provenience,
        "tag": tag,
        "difficulty": difficulty,
        "index": index,
    })

    return save_sudoku(
        grid,
        name=name,
        metadata=complete_metadata,
    )
    

def load_sudoku(reference):
    """
    Carica un Sudoku tramite identificatore, nome o percorso.

    Restituisce un dizionario con griglia NumPy e metadati.
    """
    path = _resolve_puzzle_path(reference)
    payload = _read_json(path)

    if payload.get("schema_version") != PUZZLE_SCHEMA_VERSION:
        raise ValueError(
            f"Versione del file Sudoku non supportata: "
            f"{payload.get('schema_version')}."
        )

    return {
        **payload,
        "grid": normalise_sudoku_grid(payload["grid"]),
        "path": path,
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
        return list_sudokus(number, "perceived_difficulty", 99)

    if method == "easiest":
        return list_sudokus(number, "perceived_difficulty", 0)

    results = []

    for path in SUDOKU_PUZZLES_DIR.glob("*.json"):
        payload = _read_json(path)
        puzzle_id = payload["id"]
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
            "name": payload.get("name"),
            "clues": payload.get("clues"),
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

# ---------------------------------------------------------------------------
# Salvataggio e caricamento delle analisi
# ---------------------------------------------------------------------------

def save_analysis(analysis):
    """Salva una variante di analisi senza sovrascrivere le altre."""
    original = normalise_sudoku_grid(analysis["original"])
    puzzle_id = sudoku_id(original)

    mode, window = _normalise_analysis_request(
        analysis.get("analysis_mode", DEFAULT_ANALYSIS_MODE),
        analysis.get("profile_difficulty_window"),
    )

    analysis = dict(analysis)
    variant = _analysis_variant(mode, window)
    analysis["puzzle_id"] = puzzle_id
    analysis["analysis_variant"] = variant
    analysis["analysis_mode"] = mode
    analysis["profile_difficulty_window"] = window

    save_sudoku(
        original,
        name=analysis.get("name"),
    )

    payload = {
        "schema_version": 2,
        "analysis_version": ANALYSIS_VERSION,
        "puzzle_id": puzzle_id,
        "analysis_variant": variant,
        "analysis_mode": mode,
        "profile_difficulty_window": window,
        "created_at": _current_timestamp(),
        "analysis": _to_json_value(analysis),
    }

    path = _analysis_path(puzzle_id, mode, window)
    _write_json(path, payload)

    cache_key = _analysis_cache_key(puzzle_id, mode, window)
    _ANALYSIS_MEMORY_CACHE[cache_key] = analysis

    return path


def load_analysis(
    reference,
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=None,
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
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=None,
    max_steps=10000,
    verbose=False,
):
    """
    Restituisce e persiste la variante di analisi richiesta.

    Le varianti ``deep``, ``profile`` e ``superficial`` hanno file e chiavi
    di cache distinti. La ``deep`` resta il default e continua a usare
    ``analysis.json``.
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

    cache_key = _analysis_cache_key(puzzle_id, mode, window)

    if not force:
        cached = _ANALYSIS_MEMORY_CACHE.get(cache_key)

        if cached is not None:
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
    analysis["analysis_variant"] = _analysis_variant(mode, window)

    save_analysis(analysis)
    return analysis
