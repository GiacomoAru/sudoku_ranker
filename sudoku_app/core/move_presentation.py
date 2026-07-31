"""Helper comuni per descrizioni e celle evidenziate delle Move."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping

from . import proof as proof_model


def format_cell(row, column):
    return f"R{int(row) + 1}C{int(column) + 1}"


def format_cells(cells):
    labels = [
        format_cell(row, column)
        for row, column in sorted({
            (int(row), int(column)) for row, column in cells
        })
    ]
    if not labels:
        return "nessuna cella"
    if len(labels) == 1:
        return labels[0]
    return ", ".join(labels[:-1]) + f" e {labels[-1]}"


def build_highlight(primary, placements, eliminations):
    primary_cells = sorted({
        (int(row), int(column)) for row, column in primary
    })
    secondary = {
        (int(row), int(column))
        for row, column, _ in placements
    } | {
        (int(row), int(column))
        for row, column, _ in eliminations
    }
    return {
        "primary": primary_cells,
        "secondary": sorted(secondary),
    }


def proof_primary_cells(logic):
    if not isinstance(logic, Mapping):
        return []
    raw_dag = logic.get("proof_dag")
    if raw_dag is not None:
        return proof_model.proof_dag(raw_dag).primary_cells()

    cells = set()
    for literal in logic.get("assumptions", ()) or ():
        normalized = proof_model.normalize_literal(literal)
        cells.add((normalized[0], normalized[1]))
    for chain in logic.get("chains", ()) or ():
        for literal in chain:
            normalized = proof_model.normalize_literal(literal)
            cells.add((normalized[0], normalized[1]))
    return sorted(cells)


def _group_conclusions(items):
    grouped = defaultdict(list)
    for row, column, value in items:
        grouped[int(value)].append((int(row), int(column)))
    return grouped


def conclusion_text(placements, eliminations):
    clauses = []
    for value, cells in sorted(_group_conclusions(placements).items()):
        clauses.append(
            f"il valore {value} viene inserito in {format_cells(cells)}"
        )
    for value, cells in sorted(_group_conclusions(eliminations).items()):
        clauses.append(
            f"il candidato {value} viene eliminato da {format_cells(cells)}"
        )
    if not clauses:
        return "non viene prodotta alcuna conclusione"
    if len(clauses) == 1:
        return clauses[0]
    return "; ".join(clauses[:-1]) + f"; inoltre, {clauses[-1]}"


def _proof_summary(technique, logic):
    if not isinstance(logic, Mapping):
        return ""
    metrics = logic.get("metrics", {}) or {}
    kind = str(logic.get("kind") or "")
    branches = int(metrics.get("branch_count", 0) or 0)
    leaves = int(metrics.get("leaf_count", 0) or 0)
    assumptions = int(metrics.get("assumption_count", 0) or 0)
    chains = int(metrics.get("chain_count", 0) or 0)
    nested = int(metrics.get("nested_subproof_count", 0) or 0)

    def counted(value, singular, plural):
        return f"{value} {singular if value == 1 else plural}"

    if technique == "Complete Forcing Tree" or "complete-forcing-tree" in kind:
        return (
            "La dimostrazione esplora un albero completo di casi "
            f"con {counted(branches, 'ramo', 'rami')} e "
            f"{counted(leaves, 'foglia contraddittoria', 'foglie contraddittorie')}."
        )
    if technique == "Nested Forcing Chain" or nested:
        return (
            "La dimostrazione Nested contiene "
            f"{counted(nested, 'sottoprova', 'sottoprove')}, "
            f"{counted(assumptions, 'assunzione', 'assunzioni')} e "
            f"{counted(branches, 'ramo', 'rami')}."
        )
    if chains or assumptions or branches:
        return (
            f"La dimostrazione usa {counted(chains, 'catena', 'catene')}, "
            f"{counted(assumptions, 'assunzione', 'assunzioni')} e "
            f"{counted(branches, 'ramo', 'rami')}."
        )
    return ""


def normalize_description(
    technique,
    description,
    *,
    primary,
    placements,
    eliminations,
    logic=None,
):
    """Produce pattern, ragionamento e conclusione in ordine uniforme."""
    primary = sorted(set(primary))
    if primary:
        pattern = (
            f"Il pattern {technique} coinvolge {format_cells(primary)}."
        )
    else:
        pattern = f"Il pattern {technique} è verificato nello stato corrente."

    body = " ".join(str(description or "").split()).strip()
    if body and body[-1] not in ".!?":
        body += "."
    if not body:
        body = (
            "I vincoli della tecnica rendono obbligatoria la conclusione."
        )

    proof_summary = _proof_summary(technique, logic)
    conclusion = conclusion_text(placements, eliminations)
    parts = [pattern, body]
    if proof_summary:
        parts.append(proof_summary)
    parts.append(f"Di conseguenza, {conclusion}.")
    return " ".join(parts)


__all__ = [
    "build_highlight",
    "conclusion_text",
    "format_cell",
    "format_cells",
    "normalize_description",
    "proof_primary_cells",
]
