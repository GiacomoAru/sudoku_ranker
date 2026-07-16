

import hashlib
import json
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
ANALYSIS_VERSION = 2

# Evita anche letture ripetute dal disco durante la stessa esecuzione.
_ANALYSIS_MEMORY_CACHE = {}


# ---------------------------------------------------------------------------
# Funzioni interne
# ---------------------------------------------------------------------------

def _ensure_sudoku_directories():
    SUDOKU_PUZZLES_DIR.mkdir(parents=True, exist_ok=True)
    SUDOKU_ANALYSES_DIR.mkdir(parents=True, exist_ok=True)


def _current_timestamp():
    return datetime.now(timezone.utc).isoformat()


def _normalise_sudoku_grid(grid):
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
    grid = _normalise_sudoku_grid(grid)
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


def _analysis_path(puzzle_id):
    return _analysis_directory(puzzle_id) / "analysis.json"


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
            restored[field] = _normalise_sudoku_grid(restored[field])

    for field in ("candidates_before", "candidates_after"):
        if field in restored:
            restored[field] = _restore_candidates(restored[field])

    return restored


def _restore_analysis(data):
    analysis = dict(data)

    analysis["original"] = _normalise_sudoku_grid(
        analysis["original"]
    )

    analysis["solved_grid"] = _normalise_sudoku_grid(
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

    grid = _normalise_sudoku_grid(grid)
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
        "grid": _normalise_sudoku_grid(payload["grid"]),
        "path": path,
    }


def list_sudokus():
    """Restituisce l'elenco sintetico dei Sudoku salvati."""
    _ensure_sudoku_directories()

    results = []

    for path in SUDOKU_PUZZLES_DIR.glob("*.json"):
        payload = _read_json(path)
        puzzle_id = payload["id"]

        results.append({
            "id": puzzle_id,
            "name": payload.get("name"),
            "clues": payload.get("clues"),
            "analysed": _analysis_path(puzzle_id).exists(),
            "updated_at": payload.get("updated_at"),
        })

    return sorted(
        results,
        key=lambda item: (
            str(item["name"]).casefold(),
            item["id"],
        ),
    )


def parse_sudoku(text):
    cleaned = "".join(text.split()).replace(".", "0")

    if len(cleaned) != 81:
        raise ValueError(
            f"Il Sudoku deve contenere 81 celle, trovate {len(cleaned)}."
        )

    if not cleaned.isdigit():
        raise ValueError(
            "Il Sudoku può contenere solo cifre e punti."
        )

    grid = np.array(
        [int(char) for char in cleaned],
        dtype=int,
    ).reshape(9, 9)

    return grid

# ---------------------------------------------------------------------------
# Salvataggio e caricamento delle analisi
# ---------------------------------------------------------------------------

def save_analysis(analysis):
    """Salva l'analisi nella cartella dedicata al Sudoku."""
    original = _normalise_sudoku_grid(analysis["original"])
    puzzle_id = sudoku_id(original)

    save_sudoku(
        original,
        name=analysis.get("name"),
    )

    payload = {
        "schema_version": 1,
        "analysis_version": ANALYSIS_VERSION,
        "puzzle_id": puzzle_id,
        "created_at": _current_timestamp(),
        "analysis": _to_json_value(analysis),
    }

    path = _analysis_path(puzzle_id)
    _write_json(path, payload)

    _ANALYSIS_MEMORY_CACHE[puzzle_id] = analysis

    return path


def load_analysis(reference):
    """
    Carica l'analisi associata a un Sudoku.

    reference può essere l'identificatore, il nome o il percorso del Sudoku.
    """
    puzzle = load_sudoku(reference)
    puzzle_id = puzzle["id"]
    path = _analysis_path(puzzle_id)

    if not path.exists():
        raise FileNotFoundError(
            f"Il Sudoku {puzzle['name']!r} non è ancora stato analizzato."
        )

    payload = _read_json(path)

    if payload.get("puzzle_id") != puzzle_id:
        raise ValueError("L'analisi non appartiene al Sudoku richiesto.")

    if payload.get("analysis_version") != ANALYSIS_VERSION:
        raise ValueError(
            "L'analisi è stata prodotta con una versione precedente "
            "del solver e deve essere ricalcolata."
        )

    analysis = _restore_analysis(payload["analysis"])
    _ANALYSIS_MEMORY_CACHE[puzzle_id] = analysis

    return analysis


# ---------------------------------------------------------------------------
# Funzione principale
# ---------------------------------------------------------------------------

def analyse_puzzle_cached(
    puzzle,
    name=None,
    metadata=None,
    force=False,
):
    """
    Restituisce l'analisi di un Sudoku seguendo questo ordine:

    1. usa l'analisi già presente in memoria;
    2. altrimenti carica l'analisi salvata;
    3. altrimenti esegue analyse_puzzle;
    4. salva automaticamente Sudoku e analisi.

    puzzle può essere:
    - una stringa di 81 caratteri;
    - una griglia 9x9;
    - un SudokuState;
    - il nome o l'identificatore di un Sudoku già salvato.

    Con force=True l'analisi viene sempre ricalcolata.
    """
    _ensure_sudoku_directories()

    if isinstance(puzzle, str) and not _looks_like_grid_string(puzzle):
        stored_puzzle = load_sudoku(puzzle)
        grid = stored_puzzle["grid"]

        if name is None:
            name = stored_puzzle["name"]

        puzzle_id = stored_puzzle["id"]

    else:
        grid = _normalise_sudoku_grid(puzzle)

        stored_puzzle = save_sudoku(
            grid,
            name=name,
            metadata=metadata,
        )

        puzzle_id = stored_puzzle["id"]
        name = stored_puzzle["name"]

    if not force:
        cached = _ANALYSIS_MEMORY_CACHE.get(puzzle_id)

        if cached is not None:
            return cached

        path = _analysis_path(puzzle_id)

        if path.exists():
            payload = _read_json(path)

            analysis_is_current = (
                payload.get("puzzle_id") == puzzle_id
                and payload.get("analysis_version") == ANALYSIS_VERSION
            )

            if analysis_is_current:
                analysis = _restore_analysis(payload["analysis"])
                _ANALYSIS_MEMORY_CACHE[puzzle_id] = analysis
                return analysis

    analysis = ss.analyse_puzzle(
        grid,
        name=name,
    )

    save_analysis(analysis)

    return analysis