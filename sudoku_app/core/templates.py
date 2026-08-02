"""Pattern Overlay Method per una singola cifra.

Il motore enumera soltanto le 9 posizioni della cifra richiesta. Non risolve
il Sudoku completo e non produce conclusioni quando il budget interrompe
l'enumerazione: union e intersection parziali non sono prove sufficienti.
"""

from __future__ import annotations

from dataclasses import dataclass

from . import proof


Candidate = tuple[int, int, int]
Cell = tuple[int, int]

DEFAULT_MAX_TEMPLATES_PER_DIGIT = 100_000
DEFAULT_MAX_TEMPLATE_RESULTS = 16


def _cell_bit(row: int, column: int) -> int:
    return 1 << (int(row) * 9 + int(column))


def _cells_from_mask(mask: int) -> tuple[Cell, ...]:
    cells = []
    while mask:
        low = mask & -mask
        index = low.bit_length() - 1
        cells.append((index // 9, index % 9))
        mask ^= low
    return tuple(cells)


@dataclass(frozen=True, slots=True)
class TemplateEnumeration:
    digit: int
    template_count: int
    union_mask: int
    intersection_mask: int
    candidate_mask: int
    truncated: bool
    max_templates: int

    @property
    def placements(self) -> frozenset[Candidate]:
        if self.truncated or not self.template_count:
            return frozenset()
        return frozenset(
            (row, column, self.digit)
            for row, column in _cells_from_mask(
                self.intersection_mask & self.candidate_mask
            )
        )

    @property
    def eliminations(self) -> frozenset[Candidate]:
        if self.truncated or not self.template_count:
            return frozenset()
        return frozenset(
            (row, column, self.digit)
            for row, column in _cells_from_mask(
                self.candidate_mask & ~self.union_mask
            )
        )


@dataclass(frozen=True, slots=True)
class TemplateDeduction:
    enumeration: TemplateEnumeration

    @property
    def digit(self) -> int:
        return self.enumeration.digit

    @property
    def placements(self) -> frozenset[Candidate]:
        return self.enumeration.placements

    @property
    def eliminations(self) -> frozenset[Candidate]:
        return self.enumeration.eliminations

    @property
    def primary_cells(self) -> tuple[Cell, ...]:
        return _cells_from_mask(self.enumeration.candidate_mask)

    def to_dict(self) -> dict:
        value = self.enumeration
        return {
            "digit": self.digit,
            "template_count": value.template_count,
            "candidate_cells": [
                list(cell) for cell in _cells_from_mask(value.candidate_mask)
            ],
            "union_cells": [
                list(cell) for cell in _cells_from_mask(value.union_mask)
            ],
            "intersection_cells": [
                list(cell) for cell in _cells_from_mask(
                    value.intersection_mask
                )
            ],
            "placements": [list(item) for item in sorted(self.placements)],
            "eliminations": [
                list(item) for item in sorted(self.eliminations)
            ],
            "search": {
                "truncated": value.truncated,
                "max_templates": value.max_templates,
            },
        }

    def proof_payload(self) -> dict:
        value = self.enumeration
        nodes = {
            0: proof.ProofNode(
                id=0,
                kind="advanced-rule",
                conclusion=None,
                parents=(),
                reason="template-enumeration",
                depth=0,
                payload={
                    "node_type": "template",
                    "digit": self.digit,
                    "template_count": value.template_count,
                    "candidate_cells": [
                        list(cell)
                        for cell in _cells_from_mask(value.candidate_mask)
                    ],
                    "search_truncated": value.truncated,
                    "max_templates": value.max_templates,
                    "presentation": False,
                },
            ),
        }
        conclusion_ids = []
        for action, candidates, is_on in (
            ("placement", self.placements, True),
            ("elimination", self.eliminations, False),
        ):
            for candidate in sorted(candidates):
                node_id = len(nodes)
                nodes[node_id] = proof.ProofNode(
                    id=node_id,
                    kind="common-conclusion",
                    conclusion=(*candidate, is_on),
                    parents=(0,),
                    reason=action,
                    depth=1,
                    payload={
                        "action": action,
                        "presentation": False,
                    },
                )
                conclusion_ids.append(node_id)
        dag = proof.ProofDAG(
            nodes=nodes,
            roots=(0,),
            conclusions=tuple(conclusion_ids),
        )
        return proof.logic_payload(
            dag,
            kind="single-digit-templates",
            reasons=("template-enumeration",),
            extra={
                "template_pattern": self.to_dict(),
                "search": self.to_dict()["search"],
            },
        )


def enumerate_digit_templates(
    state,
    digit: int,
    *,
    max_templates: int = DEFAULT_MAX_TEMPLATES_PER_DIGIT,
) -> TemplateEnumeration:
    """Enumera configurazioni riga/colonna/box compatibili per una cifra."""
    digit = int(digit)
    max_templates = int(max_templates)
    if digit not in range(1, 10):
        raise ValueError("digit deve essere compreso tra 1 e 9.")
    if max_templates < 1:
        raise ValueError("max_templates deve essere positivo.")

    candidate_mask = 0
    row_options = []
    for row in range(9):
        placed = tuple(
            column
            for column in range(9)
            if int(state.grid[row, column]) == digit
        )
        if len(placed) > 1:
            return TemplateEnumeration(
                digit, 0, 0, 0, candidate_mask, False, max_templates
            )
        for column in range(9):
            if (
                int(state.grid[row, column]) == 0
                and digit in state.candidates[row][column]
            ):
                candidate_mask |= _cell_bit(row, column)
        if placed:
            row_options.append(placed)
            continue
        options = tuple(
            column
            for column in range(9)
            if int(state.grid[row, column]) == 0
            and digit in state.candidates[row][column]
        )
        if not options:
            return TemplateEnumeration(
                digit, 0, 0, 0, candidate_mask, False, max_templates
            )
        row_options.append(options)

    template_count = 0
    union_mask = 0
    intersection_mask = 0
    truncated = False

    def visit(row, used_columns, used_boxes, mask):
        nonlocal template_count, union_mask, intersection_mask, truncated
        if truncated:
            return
        if row == 9:
            if template_count >= max_templates:
                truncated = True
                return
            template_count += 1
            union_mask |= mask
            intersection_mask = (
                mask if template_count == 1 else intersection_mask & mask
            )
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
                mask | _cell_bit(row, column),
            )
            if truncated:
                return

    visit(0, 0, 0, 0)
    return TemplateEnumeration(
        digit=digit,
        template_count=template_count,
        union_mask=union_mask,
        intersection_mask=intersection_mask,
        candidate_mask=candidate_mask,
        truncated=truncated,
        max_templates=max_templates,
    )


def find_templates(
    state,
    *,
    max_results: int = DEFAULT_MAX_TEMPLATE_RESULTS,
    max_templates: int = DEFAULT_MAX_TEMPLATES_PER_DIGIT,
) -> tuple[TemplateDeduction, ...]:
    """Restituisce soltanto deduzioni basate su enumerazioni complete."""
    max_results = max(1, int(max_results))
    deductions = []
    for digit in range(1, 10):
        enumeration = enumerate_digit_templates(
            state, digit, max_templates=max_templates
        )
        if (
            enumeration.truncated
            or not enumeration.template_count
            or not (enumeration.placements or enumeration.eliminations)
        ):
            continue
        deductions.append(TemplateDeduction(enumeration))
        if len(deductions) >= max_results:
            break
    return tuple(deductions)


__all__ = [
    "Candidate",
    "Cell",
    "DEFAULT_MAX_TEMPLATE_RESULTS",
    "DEFAULT_MAX_TEMPLATES_PER_DIGIT",
    "TemplateDeduction",
    "TemplateEnumeration",
    "enumerate_digit_templates",
    "find_templates",
]
