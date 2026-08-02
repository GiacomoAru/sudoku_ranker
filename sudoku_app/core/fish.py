"""Motore parametrico per i fish Sudoku.

Il modulo rappresenta righe, colonne e box come *base sets* e *cover sets*.
La ricerca segue la semantica descritta da HoDoKu: i candidati base non
coperti sono exo-fin, le intersezioni fra basi sono endo-fin e le
intersezioni fra cover sono possibili eliminazioni cannibalistiche.

``techniques.fish`` resta l'adattatore pubblico che converte le deduzioni in
Move; qui non vengono costruite descrizioni, rating o dettagli di interfaccia.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from itertools import combinations
from typing import Iterable, Iterator, TypeAlias

from .data_structure import UNITS, UNIT_KINDS, peers


Candidate: TypeAlias = tuple[int, int, int]

HOUSE_TYPES = frozenset({"row", "column", "box"})
HOUSE_TYPE_BY_ID = tuple(
    "column" if kind == "col" else kind
    for kind in UNIT_KINDS
)
HOUSE_CELLS = tuple(tuple(unit) for unit in UNITS)


def _cell_index(row: int, column: int) -> int:
    return int(row) * 9 + int(column)


def _cell_mask(row: int, column: int) -> int:
    return 1 << _cell_index(row, column)


HOUSE_MASKS = tuple(
    sum(_cell_mask(row, column) for row, column in cells)
    for cells in HOUSE_CELLS
)
PEER_MASKS = tuple(
    sum(_cell_mask(row, column) for row, column in peers(index // 9, index % 9))
    for index in range(81)
)

FISH_SIZE_NAMES = {2: "X-Wing", 3: "Swordfish", 4: "Jellyfish"}
FISH_CLASS_ORDER = {"basic": 0, "franken": 1, "mutant": 2}

# Limiti di enumerazione, non di validita' logica. Tre fin complessive e due
# endo-fin coprono le varianti P10 mantenendo utilizzabile il detector Python.
DEFAULT_MAX_FINS = 3
DEFAULT_MAX_ENDO_FINS = 2
DEFAULT_MAX_RAW_RESULTS = 512


@dataclass(frozen=True, slots=True)
class FishPattern:
    """Struttura logica autorevole di un singolo fish."""

    digit: int
    size: int
    base_sets: tuple[int, ...]
    cover_sets: tuple[int, ...]
    fins: frozenset[Candidate]
    endo_fins: frozenset[Candidate]
    cannibalistic_targets: frozenset[Candidate]
    fish_class: str

    def __post_init__(self):
        if self.digit not in range(1, 10):
            raise ValueError("La cifra del fish deve essere compresa tra 1 e 9.")
        if self.size not in FISH_SIZE_NAMES:
            raise ValueError("P10 supporta fish di dimensione 2, 3 o 4.")
        if len(self.base_sets) != self.size:
            raise ValueError("Il numero di base sets deve coincidere con size.")
        if len(self.cover_sets) != self.size:
            raise ValueError("Il numero di cover sets deve coincidere con size.")
        if len(set(self.base_sets)) != self.size:
            raise ValueError("I base sets devono essere distinti.")
        if len(set(self.cover_sets)) != self.size:
            raise ValueError("I cover sets devono essere distinti.")
        if set(self.base_sets) & set(self.cover_sets):
            raise ValueError("Una casa non puo' essere insieme base e cover.")
        if self.fish_class not in FISH_CLASS_ORDER:
            raise ValueError(f"Classe fish sconosciuta: {self.fish_class!r}.")

    @property
    def all_fins(self) -> frozenset[Candidate]:
        return self.fins | self.endo_fins

    @property
    def modifiers(self) -> tuple[str, ...]:
        values = []
        if self.endo_fins:
            values.append("endo-finned")
        if self.cannibalistic_targets:
            values.append("cannibalistic")
        return tuple(values)

    def to_dict(self) -> dict:
        return {
            "digit": self.digit,
            "size": self.size,
            "base_sets": list(self.base_sets),
            "cover_sets": list(self.cover_sets),
            "base_set_types": [HOUSE_TYPE_BY_ID[item] for item in self.base_sets],
            "cover_set_types": [HOUSE_TYPE_BY_ID[item] for item in self.cover_sets],
            "fins": [list(item) for item in sorted(self.fins)],
            "endo_fins": [list(item) for item in sorted(self.endo_fins)],
            "cannibalistic_targets": [
                list(item) for item in sorted(self.cannibalistic_targets)
            ],
            "fish_class": self.fish_class,
            "modifiers": list(self.modifiers),
        }


@dataclass(frozen=True, slots=True)
class FishDeduction:
    """Conclusione prodotta da un pattern, prima della conversione in Move."""

    pattern: FishPattern
    eliminations: frozenset[Candidate]
    body: frozenset[Candidate]
    potential_targets: frozenset[Candidate]
    sashimi: bool = False
    components: tuple[FishPattern, ...] = ()
    equivalent_pattern_count: int = 1

    @property
    def is_siamese(self) -> bool:
        return len(self.components) > 1

    @property
    def technique_name(self) -> str:
        if self.is_siamese:
            return "Siamese Fish"
        species = FISH_SIZE_NAMES[self.pattern.size]
        prefix = "Sashimi" if self.sashimi else "Finned"
        finned = bool(self.pattern.all_fins)
        if self.pattern.fish_class == "basic":
            return f"{prefix} {species}" if finned else species
        class_name = self.pattern.fish_class.capitalize()
        if not finned:
            return f"{class_name} {species}"
        return f"{prefix} {class_name} {species}"

    def to_dict(self) -> dict:
        payload = self.pattern.to_dict()
        payload.update({
            "sashimi": self.sashimi,
            "siamese": self.is_siamese,
            "body": [list(item) for item in sorted(self.body)],
            "potential_targets": [
                list(item) for item in sorted(self.potential_targets)
            ],
            "eliminations": [list(item) for item in sorted(self.eliminations)],
            "equivalent_pattern_count": self.equivalent_pattern_count,
        })
        if self.components:
            payload["siamese_components"] = [
                component.to_dict() for component in self.components
            ]
        return payload


def house_label(house_id: int) -> str:
    house_id = int(house_id)
    kind = HOUSE_TYPE_BY_ID[house_id]
    number = house_id + 1 if kind == "row" else (
        house_id - 8 if kind == "column" else house_id - 17
    )
    labels = {"row": "riga", "column": "colonna", "box": "box"}
    return f"{labels[kind]} {number}"


def classify_fish(base_sets: Iterable[int], cover_sets: Iterable[int]) -> str:
    """Classifica il fish dai tipi di casa, mai dal numero di candidati."""
    base_types = {HOUSE_TYPE_BY_ID[int(item)] for item in base_sets}
    cover_types = {HOUSE_TYPE_BY_ID[int(item)] for item in cover_sets}

    if (
        (base_types == {"row"} and cover_types == {"column"})
        or (base_types == {"column"} and cover_types == {"row"})
    ):
        return "basic"

    row_franken = (
        base_types in ({"row"}, {"row", "box"})
        and cover_types in ({"column"}, {"column", "box"})
    )
    column_franken = (
        base_types in ({"column"}, {"column", "box"})
        and cover_types in ({"row"}, {"row", "box"})
    )
    if (row_franken or column_franken) and (
        "box" in base_types or "box" in cover_types
    ):
        return "franken"
    return "mutant"


def _candidate_mask(state, digit: int) -> int:
    mask = 0
    for row in range(9):
        for column in range(9):
            if digit in state.candidates[row][column]:
                mask |= _cell_mask(row, column)
    return mask


def _template_elimination_mask(state, digit: int) -> int | None:
    """Candidati assenti da ogni template valido per una singola cifra.

    Un valore ``0`` prova che nessun fish per la cifra puo' eliminare
    qualcosa. ``None`` indica invece che lo stato parziale non ammette un
    template completo e disabilita prudentemente questa ottimizzazione.
    """
    candidate_mask = _candidate_mask(state, digit)
    row_options = []
    for row in range(9):
        placed = [
            column
            for column in range(9)
            if int(state.grid[row, column]) == digit
        ]
        if len(placed) > 1:
            return None
        if placed:
            row_options.append(tuple(placed))
            continue
        options = tuple(
            column
            for column in range(9)
            if candidate_mask & _cell_mask(row, column)
        )
        if not options:
            return None
        row_options.append(options)

    template_union = 0
    template_count = 0

    def visit(row, used_columns, used_boxes, mask):
        nonlocal template_union, template_count
        if row == 9:
            template_union |= mask
            template_count += 1
            return
        for column in row_options[row]:
            column_bit = 1 << column
            box_bit = 1 << (3 * (row // 3) + column // 3)
            if used_columns & column_bit or used_boxes & box_bit:
                continue
            visit(
                row + 1,
                used_columns | column_bit,
                used_boxes | box_bit,
                mask | _cell_mask(row, column),
            )

    visit(0, 0, 0, 0)
    if template_count == 0:
        return None
    return candidate_mask & ~template_union


def _mask_candidates(mask: int, digit: int) -> frozenset[Candidate]:
    result = []
    while mask:
        low = mask & -mask
        index = low.bit_length() - 1
        result.append((index // 9, index % 9, int(digit)))
        mask ^= low
    return frozenset(result)


def _common_peer_mask(mask: int) -> int:
    if not mask:
        return (1 << 81) - 1
    common = (1 << 81) - 1
    while mask:
        low = mask & -mask
        common &= PEER_MASKS[low.bit_length() - 1]
        mask ^= low
    return common


def _normalise_house_types(values, *, field: str) -> frozenset[str]:
    result = frozenset(str(value).strip().casefold() for value in values)
    aliases = {"col": "column", "line": "row", "block": "box"}
    result = frozenset(aliases.get(value, value) for value in result)
    unknown = result - HOUSE_TYPES
    if unknown:
        raise ValueError(
            f"Tipi di casa non validi in {field}: {', '.join(sorted(unknown))}."
        )
    if not result:
        raise ValueError(f"{field} non puo' essere vuoto.")
    return result


def _iter_cover_combinations(
    cover_ids: tuple[int, ...],
    cover_masks: dict[int, int],
    *,
    size: int,
    base_mask: int,
    endo_mask: int,
    max_fins: int,
    target_mask: int | None = None,
) -> Iterator[tuple[tuple[int, ...], int, int]]:
    """Enumera cover sets con pruning sulle fin ormai inevitabili."""
    suffix_union = [0] * (len(cover_ids) + 1)
    for index in range(len(cover_ids) - 1, -1, -1):
        suffix_union[index] = suffix_union[index + 1] | cover_masks[cover_ids[index]]

    target_cover_ids = (
        frozenset(
            house_id
            for house_id in cover_ids
            if cover_masks[house_id] & target_mask
        )
        if target_mask is not None
        else frozenset(cover_ids)
    )

    def visit(start, chosen, union_mask, overlap_mask, has_target_cover):
        needed = size - len(chosen)
        if needed == 0:
            if has_target_cover:
                yield tuple(chosen), union_mask, overlap_mask
            return
        if len(cover_ids) - start < needed:
            return
        mandatory_fins = (
            base_mask & ~(union_mask | suffix_union[start])
        ) | endo_mask
        if mandatory_fins.bit_count() > max_fins:
            return
        if not has_target_cover and not any(
            house_id in target_cover_ids
            for house_id in cover_ids[start:]
        ):
            return

        last_start = len(cover_ids) - needed
        for position in range(start, last_start + 1):
            house_id = cover_ids[position]
            mask = cover_masks[house_id]
            yield from visit(
                position + 1,
                chosen + [house_id],
                union_mask | mask,
                overlap_mask | (union_mask & mask),
                has_target_cover or house_id in target_cover_ids,
            )

    yield from visit(0, [], 0, 0, False)


def find_fish(
    state,
    digit: int,
    size: int,
    allowed_base_types: Iterable[str] = HOUSE_TYPES,
    allowed_cover_types: Iterable[str] = HOUSE_TYPES,
    *,
    accepted_classes: Iterable[str] | None = None,
    max_fins: int = DEFAULT_MAX_FINS,
    max_endo_fins: int = DEFAULT_MAX_ENDO_FINS,
    max_results: int = DEFAULT_MAX_RAW_RESULTS,
    target_mask: int | None = None,
) -> Iterator[FishDeduction]:
    """Trova fish parametrici per una cifra e una dimensione.

    Il numero di base e cover sets e' sempre ``size``. ``max_fins`` conta
    insieme exo-fin ed endo-fin, come nel solver HoDoKu.
    """
    digit = int(digit)
    size = int(size)
    if digit not in range(1, 10):
        raise ValueError("digit deve essere compreso tra 1 e 9.")
    if size not in FISH_SIZE_NAMES:
        raise ValueError("size deve essere 2, 3 o 4.")
    if max_fins < 0 or max_endo_fins < 0 or max_results <= 0:
        raise ValueError("I budget del fish devono essere non negativi e finiti.")

    base_types = _normalise_house_types(
        allowed_base_types, field="allowed_base_types"
    )
    cover_types = _normalise_house_types(
        allowed_cover_types, field="allowed_cover_types"
    )
    accepted = (
        frozenset(FISH_CLASS_ORDER)
        if accepted_classes is None
        else frozenset(str(value).casefold() for value in accepted_classes)
    )
    unknown_classes = accepted - set(FISH_CLASS_ORDER)
    if unknown_classes:
        raise ValueError(
            f"Classi fish non valide: {', '.join(sorted(unknown_classes))}."
        )

    candidates_mask = _candidate_mask(state, digit)
    if not candidates_mask:
        return
    house_candidate_masks = {
        house_id: HOUSE_MASKS[house_id] & candidates_mask
        for house_id in range(27)
    }
    base_house_ids = tuple(
        house_id
        for house_id in range(27)
        if HOUSE_TYPE_BY_ID[house_id] in base_types
        and house_candidate_masks[house_id]
    )
    all_cover_ids = tuple(
        house_id
        for house_id in range(27)
        if HOUSE_TYPE_BY_ID[house_id] in cover_types
        and house_candidate_masks[house_id]
    )
    if len(base_house_ids) < size or len(all_cover_ids) < size:
        return

    emitted = 0
    for base_sets in combinations(base_house_ids, size):
        base_union = 0
        endo_mask = 0
        for house_id in base_sets:
            mask = house_candidate_masks[house_id]
            endo_mask |= base_union & mask
            base_union |= mask
        if endo_mask.bit_count() > max_endo_fins:
            continue

        relevant_cover_ids = tuple(
            house_id
            for house_id in all_cover_ids
            if house_id not in base_sets
            and house_candidate_masks[house_id] & base_union
        )
        if len(relevant_cover_ids) < size:
            continue
        if target_mask is not None:
            relevant_cover_ids = tuple(sorted(
                relevant_cover_ids,
                key=lambda house_id: (
                    not bool(house_candidate_masks[house_id] & target_mask),
                    house_id,
                ),
            ))

        for cover_sets, cover_union, cover_overlap in _iter_cover_combinations(
            relevant_cover_ids,
            house_candidate_masks,
            size=size,
            base_mask=base_union,
            endo_mask=endo_mask,
            max_fins=max_fins,
            target_mask=target_mask,
        ):
            fish_class = classify_fish(base_sets, cover_sets)
            if fish_class not in accepted:
                continue

            exo_mask = base_union & ~cover_union & ~endo_mask
            all_fins_mask = exo_mask | endo_mask
            if all_fins_mask.bit_count() > max_fins:
                continue

            regular_targets = cover_union & ~base_union
            potential_targets = regular_targets | cover_overlap
            if target_mask is not None:
                potential_targets &= target_mask
            if not potential_targets:
                continue
            visible_targets = potential_targets & _common_peer_mask(all_fins_mask)
            if not visible_targets:
                continue

            actual_cannibal = cover_overlap & visible_targets
            body_mask = (base_union & cover_union) & ~endo_mask
            sashimi = bool(all_fins_mask) and any(
                (
                    house_candidate_masks[house_id]
                    & ~all_fins_mask
                ).bit_count() <= 1
                for house_id in base_sets
            )
            pattern = FishPattern(
                digit=digit,
                size=size,
                base_sets=tuple(base_sets),
                cover_sets=tuple(cover_sets),
                fins=_mask_candidates(exo_mask, digit),
                endo_fins=_mask_candidates(endo_mask, digit),
                cannibalistic_targets=_mask_candidates(
                    actual_cannibal, digit
                ),
                fish_class=fish_class,
            )
            yield FishDeduction(
                pattern=pattern,
                eliminations=_mask_candidates(visible_targets, digit),
                body=_mask_candidates(body_mask, digit),
                potential_targets=_mask_candidates(potential_targets, digit),
                sashimi=sashimi,
            )
            emitted += 1
            if emitted >= max_results:
                return


def _deduction_rank(deduction: FishDeduction) -> tuple:
    pattern = deduction.pattern
    return (
        pattern.size,
        FISH_CLASS_ORDER[pattern.fish_class],
        int(bool(pattern.all_fins)),
        int(not deduction.sashimi),
        len(pattern.all_fins),
        len(pattern.cannibalistic_targets),
        pattern.base_sets,
        pattern.cover_sets,
    )


def _siamese_deductions(
    deductions: list[FishDeduction],
) -> tuple[list[FishDeduction], set[int]]:
    """Aggrega coppie finned con stesse basi e una cover differente."""
    siamese = []
    consumed: set[int] = set()
    seen = set()
    for left_index, right_index in combinations(range(len(deductions)), 2):
        left = deductions[left_index]
        right = deductions[right_index]
        lp = left.pattern
        rp = right.pattern
        if not lp.all_fins or not rp.all_fins:
            continue
        if (
            lp.digit != rp.digit
            or lp.size != rp.size
            or lp.fish_class != rp.fish_class
            or lp.base_sets != rp.base_sets
            or left.sashimi != right.sashimi
        ):
            continue
        if len(set(lp.cover_sets) ^ set(rp.cover_sets)) != 2:
            continue
        if left.eliminations == right.eliminations:
            continue

        eliminations = left.eliminations | right.eliminations
        components = tuple(sorted(
            (lp, rp), key=lambda item: (item.cover_sets, sorted(item.fins))
        ))
        signature = (
            lp.digit,
            lp.size,
            lp.fish_class,
            lp.base_sets,
            tuple(sorted(eliminations)),
        )
        if signature in seen:
            continue
        seen.add(signature)
        merged_pattern = replace(
            lp,
            fins=lp.fins | rp.fins,
            endo_fins=lp.endo_fins | rp.endo_fins,
            cannibalistic_targets=(
                lp.cannibalistic_targets | rp.cannibalistic_targets
            ),
        )
        siamese.append(FishDeduction(
            pattern=merged_pattern,
            eliminations=eliminations,
            body=left.body | right.body,
            potential_targets=left.potential_targets | right.potential_targets,
            sashimi=left.sashimi,
            components=components,
            equivalent_pattern_count=2,
        ))
        consumed.update((left_index, right_index))
    return siamese, consumed


def consolidate_fish_deductions(
    deductions: Iterable[FishDeduction],
    *,
    allow_siamese: bool = True,
) -> list[FishDeduction]:
    """Consolida componenti Siamese e conclusioni strutturalmente duplicate."""
    raw = list(deductions)
    siamese, consumed = (
        _siamese_deductions(raw) if allow_siamese else ([], set())
    )
    candidates = [
        deduction
        for index, deduction in enumerate(raw)
        if index not in consumed
    ] + siamese

    by_outcome: dict[tuple[Candidate, ...], FishDeduction] = {}
    counts: dict[tuple[Candidate, ...], int] = {}
    for deduction in candidates:
        outcome = tuple(sorted(deduction.eliminations))
        counts[outcome] = counts.get(outcome, 0) + deduction.equivalent_pattern_count
        previous = by_outcome.get(outcome)
        if previous is None or _deduction_rank(deduction) < _deduction_rank(previous):
            by_outcome[outcome] = deduction

    return sorted(
        (
            replace(
                deduction,
                equivalent_pattern_count=counts[outcome],
            )
            for outcome, deduction in by_outcome.items()
        ),
        key=_deduction_rank,
    )


def find_all_fish(
    state,
    *,
    sizes: Iterable[int] = (2, 3, 4),
    max_fins: int = DEFAULT_MAX_FINS,
    max_endo_fins: int = DEFAULT_MAX_ENDO_FINS,
    max_results_per_search: int = DEFAULT_MAX_RAW_RESULTS,
    allow_siamese: bool = True,
) -> list[FishDeduction]:
    """Esegue il motore in ordine Basic, Franken, Mutant.

    Come un solver umano, la raccolta si arresta alla prima classe che offre
    conclusioni: una forma piu complessa non e' necessaria quando lo stesso
    stato dispone gia' di un fish di classe inferiore. Il comportamento evita
    soprattutto che la ricerca Mutant combinatoria rallenti gli step ordinari.
    """
    normalised_sizes = sorted({int(value) for value in sizes})
    for size in normalised_sizes:
        if size not in FISH_SIZE_NAMES:
            raise ValueError("sizes puo' contenere soltanto 2, 3 e 4.")

    template_eliminations = {
        digit: _template_elimination_mask(state, digit)
        for digit in range(1, 10)
    }
    eligible_digits = tuple(
        digit
        for digit in range(1, 10)
        if template_eliminations[digit] is None
        or template_eliminations[digit] != 0
    )

    search_tiers = (
        (
            "basic",
            (
                (("row",), ("column",)),
                (("column",), ("row",)),
            ),
            max_results_per_search,
        ),
        (
            "franken",
            (
                (("row", "box"), ("column", "box")),
                (("column", "box"), ("row", "box")),
            ),
            min(max_results_per_search, 8),
        ),
        (
            "mutant",
            ((HOUSE_TYPES, HOUSE_TYPES),),
            min(max_results_per_search, 4),
        ),
    )
    for fish_class, searches, result_limit in search_tiers:
        raw: list[FishDeduction] = []
        for size in normalised_sizes:
            for digit in eligible_digits:
                for base_types, cover_types in searches:
                    raw.extend(find_fish(
                        state,
                        digit,
                        size,
                        base_types,
                        cover_types,
                        accepted_classes=(fish_class,),
                        max_fins=max_fins,
                        max_endo_fins=max_endo_fins,
                        max_results=result_limit,
                        target_mask=template_eliminations[digit],
                    ))
        if raw:
            return consolidate_fish_deductions(
                raw, allow_siamese=allow_siamese
            )
    return []


__all__ = [
    "Candidate",
    "DEFAULT_MAX_ENDO_FINS",
    "DEFAULT_MAX_FINS",
    "FISH_SIZE_NAMES",
    "FishDeduction",
    "FishPattern",
    "HOUSE_CELLS",
    "HOUSE_MASKS",
    "HOUSE_TYPE_BY_ID",
    "HOUSE_TYPES",
    "classify_fish",
    "consolidate_fish_deductions",
    "find_all_fish",
    "find_fish",
    "house_label",
]
