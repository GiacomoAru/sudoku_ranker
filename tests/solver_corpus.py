"""Parser e associazioni del corpus permanente di regressione del solver."""

from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np

from sudoku_app.core.data_structure import UNIQUENESS_VERIFIED, SudokuState


CORPUS_ROOT = Path(__file__).resolve().parent / "fixtures" / "solver_corpus"
HODOKU_CASES_PATH = CORPUS_ROOT / "hodoku_regression.txt"
PUZZLE_CASES_PATH = CORPUS_ROOT / "puzzles.json"


@dataclass(frozen=True)
class TechniqueBinding:
    detector_id: str
    technique_id: str


@dataclass(frozen=True)
class HoDoKuCase:
    source_code: str
    focus_candidates: tuple[int, ...]
    pattern: str
    deleted_candidates: tuple[tuple[int, int, int], ...]
    expected_eliminations: tuple[tuple[int, int, int], ...]
    expected_placements: tuple[tuple[int, int, int], ...]
    extra: str

    @property
    def base_code(self):
        return self.source_code.split("-", 1)[0]

    def build_state(self):
        current, initial = _parse_hodoku_pattern(self.pattern)
        state = SudokuState(
            current,
            initial_grid=initial,
            uniqueness_status=UNIQUENESS_VERIFIED,
        )
        for row, column, value in self.deleted_candidates:
            state.eliminate(row, column, value)
        return state


# Un solo caso esterno gold per famiglia/variante implementata. Il secondo
# valore impedisce che un detector generico passi producendo la tecnica errata.
ACTIVE_TECHNIQUE_BINDINGS = {
    "0000": TechniqueBinding("last_value", "single.last_value"),
    "0002": TechniqueBinding("hidden_single", "single.hidden.line"),
    "0003": TechniqueBinding("naked_single", "single.naked"),
    "0100": TechniqueBinding("locked_candidates", "intersection.pointing"),
    "0101": TechniqueBinding("locked_candidates", "intersection.claiming"),
    "0200": TechniqueBinding("naked_subset:2", "subset.naked.2"),
    "0201": TechniqueBinding("naked_subset:3", "subset.naked.3"),
    "0202": TechniqueBinding("naked_subset:4", "subset.naked.4"),
    "0210": TechniqueBinding("hidden_subset:2", "subset.hidden.2"),
    "0211": TechniqueBinding("hidden_subset:3", "subset.hidden.3"),
    "0212": TechniqueBinding("hidden_subset:4", "subset.hidden.4"),
    "0300": TechniqueBinding("fish", "fish.basic.2"),
    "0301": TechniqueBinding("fish", "fish.basic.3"),
    "0302": TechniqueBinding("fish", "fish.basic.4"),
    "0310": TechniqueBinding("fish", "fish.finned.2"),
    "0311": TechniqueBinding("fish", "fish.finned.3"),
    "0312": TechniqueBinding("fish", "fish.finned.4"),
    "0320": TechniqueBinding("fish", "fish.sashimi.2"),
    "0321": TechniqueBinding("fish", "fish.sashimi.3"),
    "0322": TechniqueBinding("fish", "fish.sashimi.4"),
    "0331": TechniqueBinding("fish", "fish.franken.3"),
    "0362": TechniqueBinding("fish", "fish.mutant.finned.4"),
    "0400": TechniqueBinding("skyscraper", "sdp.skyscraper"),
    "0401": TechniqueBinding("two_string_kite", "sdp.two_string_kite"),
    "0402": TechniqueBinding("empty_rectangle", "sdp.empty_rectangle"),
    "0500": TechniqueBinding("coloring", "color.simple.trap"),
    "0501": TechniqueBinding("coloring", "color.simple.wrap"),
    "0503": TechniqueBinding("coloring", "color.multi.type2"),
    "0600": TechniqueBinding("ur_type_1", "unique.ur.1"),
    "0601": TechniqueBinding("ur_type_2", "unique.ur.2"),
    "0602": TechniqueBinding("ur_type_3", "unique.ur.3"),
    "0603": TechniqueBinding("ur_type_4", "unique.ur.4"),
    "0604": TechniqueBinding("ur_type_5", "unique.ur.5"),
    "0605": TechniqueBinding("ur_type_6", "unique.ur.6"),
    "0606": TechniqueBinding(
        "hidden_rectangle",
        "unique.hidden_rectangle",
    ),
    "0607": TechniqueBinding("avoidable_rectangle:1", "unique.avoidable.1"),
    "0608": TechniqueBinding("avoidable_rectangle:2", "unique.avoidable.2"),
    "0610": TechniqueBinding("bug_plus_one", "unique.bug.1"),
    "0702": TechniqueBinding("xy_chain", "chain.xy"),
    "0703": TechniqueBinding("xy_chain", "chain.remote_pair"),
    "0800": TechniqueBinding("y_wing", "wing.xy"),
    "0801": TechniqueBinding("xyz_wing", "wing.xyz"),
    "0803": TechniqueBinding("w_wing", "wing.w"),
    "1101": TechniqueBinding(
        "sue_de_coq",
        "intersection.sue_de_coq.extended",
    ),
}


# Casi già vendorizzati per le patch successive. Quando una famiglia diventa
# stabile il suo codice si sposta nella mappa ACTIVE_TECHNIQUE_BINDINGS.
PLANNED_HODOKU_CODES = frozenset({
    "0341",
    "0502",
    "0701", "0706", "0707", "0708", "0709", "0710", "0711",
    "0901", "0902", "0903", "0904", "1201", "1202",
})


def _parse_candidate_tokens(value):
    if not value:
        return ()
    parsed = []
    for token in value.split():
        if len(token) != 3 or not token.isdigit():
            raise ValueError(f"Token candidato HoDoKu non valido: {token!r}")
        digit, row, column = (int(character) for character in token)
        if not all(1 <= item <= 9 for item in (digit, row, column)):
            raise ValueError(f"Token candidato HoDoKu fuori range: {token!r}")
        parsed.append((row - 1, column - 1, digit))
    return tuple(parsed)


def _parse_hodoku_pattern(pattern):
    current = []
    initial = []
    cursor = 0
    while cursor < len(pattern):
        character = pattern[cursor]
        if character == ".":
            current.append(0)
            initial.append(0)
            cursor += 1
        elif character == "+":
            if cursor + 1 >= len(pattern) or not pattern[cursor + 1].isdigit():
                raise ValueError("Valore già piazzato HoDoKu non valido.")
            current.append(int(pattern[cursor + 1]))
            initial.append(0)
            cursor += 2
        elif character.isdigit():
            current.append(int(character))
            initial.append(int(character))
            cursor += 1
        else:
            raise ValueError(f"Carattere griglia HoDoKu non valido: {character!r}")
    if len(current) != 81:
        raise ValueError(
            f"La griglia HoDoKu contiene {len(current)} celle invece di 81."
        )
    return (
        np.array(current, dtype=int).reshape(9, 9),
        np.array(initial, dtype=int).reshape(9, 9),
    )


def parse_hodoku_line(line):
    fields = line.strip().split(":")
    if len(fields) != 8 or fields[0]:
        raise ValueError(f"Riga HoDoKu non valida: {line!r}")
    source_code, focus, pattern, deleted, eliminated, placed, extra = fields[1:8]
    return HoDoKuCase(
        source_code=source_code,
        focus_candidates=tuple(int(value) for value in focus),
        pattern=pattern,
        deleted_candidates=_parse_candidate_tokens(deleted),
        expected_eliminations=_parse_candidate_tokens(eliminated),
        expected_placements=_parse_candidate_tokens(placed),
        extra=extra,
    )


def load_hodoku_cases(path=HODOKU_CASES_PATH):
    return tuple(
        parse_hodoku_line(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )


def load_puzzle_cases(path=PUZZLE_CASES_PATH):
    document = json.loads(path.read_text(encoding="utf-8"))
    if document.get("schema_version") != 1:
        raise ValueError("Versione del corpus puzzle non supportata.")
    return tuple(document["cases"])


def canonical_outcome(state, eliminations, placements):
    """Normalizza eliminazioni equivalenti a un piazzamento forzato.

    HoDoKu esprime BUG+1 eliminando gli altri candidati della cella; il solver
    inserisce direttamente il candidato extra. Entrambe le conclusioni portano
    allo stesso stato e devono essere considerate la stessa regressione.
    """
    canonical_placements = set(placements)
    remaining_eliminations = set(eliminations)
    by_cell = {}
    for row, column, value in eliminations:
        by_cell.setdefault((row, column), set()).add(value)
    for (row, column), values in by_cell.items():
        candidates = set(state.candidates[row][column])
        remaining = candidates - values
        if len(remaining) == 1:
            canonical_placements.add((row, column, next(iter(remaining))))
            remaining_eliminations.difference_update(
                (row, column, value) for value in values
            )
    return (
        frozenset(remaining_eliminations),
        frozenset(canonical_placements),
    )
