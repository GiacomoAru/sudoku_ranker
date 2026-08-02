"""Presentazione derivata delle mosse del solver.

Pattern e ``ProofDAG`` restano le fonti logiche autorevoli. Questo modulo
materializza soltanto viste adatte a testo, archivio e interfaccia web.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence

from . import proof as proof_model


VISUAL_EVIDENCE_SCHEMA_VERSION = "1.2.0"
EXPLANATION_SCHEMA_VERSION = "1.0.0"

LINK_RELATIONS = frozenset({
    "implication",
    "equivalence",
    "contradiction",
    "grouped-implication",
})
LINK_DIRECTIONS = frozenset({"forward", "bidirectional"})

CANDIDATE_ROLES = frozenset({
    "pattern", "support", "link", "assumption", "contradiction", "target",
    "placement", "elimination", "base", "cover", "fin", "endo-fin",
    "group",
})


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
    effect = {
        (int(row), int(column)) for row, column, _ in placements
    } | {
        (int(row), int(column)) for row, column, _ in eliminations
    }
    implication = set(primary_cells) - effect
    return {
        "implication": sorted(implication),
        "effect": sorted(effect),
        # Viste storiche derivate: i renderer nuovi usano i nomi semantici.
        "primary": primary_cells,
        "secondary": sorted(effect),
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
        cells.update(proof_model.literal_cells(normalized))
    for chain in logic.get("chains", ()) or ():
        for literal in chain:
            normalized = proof_model.normalize_literal(literal)
            cells.update(proof_model.literal_cells(normalized))
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


def _candidate_key(row, column, value):
    return int(row), int(column), int(value)


def _literal_parts(literal):
    try:
        normalized = proof_model.normalize_literal(literal)
    except (KeyError, TypeError, ValueError):
        return None
    if normalized is None:
        return None
    if proof_model.is_group_literal(normalized):
        return None
    row, column, value, is_on = normalized
    return row, column, value, "on" if is_on else "off"


def _iter_chain_links(logic):
    if not isinstance(logic, Mapping):
        return
    for chain in logic.get("chain_links", ()) or ():
        for link in chain or ():
            if isinstance(link, Mapping):
                yield link


def _visual_literal(literal):
    if (
        isinstance(literal, Sequence)
        and not isinstance(literal, (str, bytes))
        and len(literal) == 3
    ):
        row, column, value = literal
        return {
            "row": int(row),
            "column": int(column),
            "value": int(value),
            "state": "candidate",
        }
    if (
        isinstance(literal, Sequence)
        and not isinstance(literal, (str, bytes))
        and len(literal) == 4
        and isinstance(literal[3], str)
    ):
        row, column, value, state = literal
        literal = {
            "row": row,
            "column": column,
            "value": value,
            "state": state,
        }
    try:
        normalized = proof_model.normalize_literal(literal)
    except (KeyError, TypeError, ValueError):
        return None
    if normalized is not None and (
        proof_model.is_group_literal(normalized)
        or proof_model.is_als_literal(normalized)
    ):
        return proof_model.literal_record(normalized)
    parts = _literal_parts(normalized)
    if parts is None:
        return None
    return {
        "row": parts[0],
        "column": parts[1],
        "value": parts[2],
        "state": parts[3],
    }


def _normalise_visual_link(link):
    """Conserva soltanto relazioni dichiarate, senza inferire equivalenze."""
    if not isinstance(link, Mapping):
        return None
    source = _visual_literal(link.get("source"))
    target = _visual_literal(link.get("target"))
    if source is None or target is None:
        return None

    relation = str(link.get("relation") or "implication")
    if relation not in LINK_RELATIONS:
        relation = "implication"
    direction = str(link.get("direction") or "forward")
    if relation == "equivalence":
        direction = "bidirectional"
    if direction not in LINK_DIRECTIONS:
        direction = "forward"

    support_candidates = []
    for literal in link.get("support_candidates", ()) or ():
        record = _visual_literal(literal)
        if record is not None:
            support_candidates.append(record)

    return {
        "source": source,
        "target": target,
        "relation": relation,
        "direction": direction,
        "strength": str(link.get("strength") or "unspecified"),
        "reason": str(link.get("reason") or "unspecified"),
        "support_candidates": support_candidates,
        "support_house_ids": sorted({
            int(value) for value in link.get("support_house_ids", ()) or ()
        }),
    }


def build_visual_evidence(
    primary,
    placements,
    eliminations,
    *,
    logic=None,
    state=None,
    explicit=None,
):
    """Deriva evidenze candidate-level da pattern, conclusioni e ProofDAG."""
    candidate_roles = defaultdict(set)
    candidate_states = {}
    cell_roles = defaultdict(set)
    links = []
    groups = {}

    def add_candidate(row, column, value, *roles, literal_state="candidate"):
        key = _candidate_key(row, column, value)
        candidate_roles[key].update(role for role in roles if role)
        candidate_states.setdefault(key, literal_state)

    def add_literal(literal, *roles):
        try:
            normalized = proof_model.normalize_literal(literal)
        except (KeyError, TypeError, ValueError):
            return None
        if normalized is None:
            return None
        if proof_model.is_group_literal(normalized):
            group, is_on = normalized
            state_label = "on" if is_on else "off"
            key = (
                group.digit,
                tuple(sorted(group.cells)),
                group.house_ids,
                group.role,
                state_label,
            )
            group_roles = {"group", *roles}
            record = groups.setdefault(key, {
                **group.to_dict(),
                "state": state_label,
                "roles": [],
            })
            record["roles"] = sorted(set(record["roles"]) | group_roles)
            for row, column, value in group.candidates:
                add_candidate(
                    row, column, value, *group_roles,
                    literal_state=state_label,
                )
                cell_roles[(row, column)].add("group")
            return normalized
        if proof_model.is_als_literal(normalized):
            als, is_on = normalized
            state_label = "on" if is_on else "off"
            als_roles = {"als", *roles}
            for row, column, value in als.candidates:
                add_candidate(
                    row, column, value, *als_roles,
                    literal_state=state_label,
                )
                cell_roles[(row, column)].add("als")
            return normalized
        row, column, value, is_on = normalized
        add_candidate(
            row, column, value, *roles,
            literal_state="on" if is_on else "off",
        )
        return normalized

    for row, column in primary:
        key = (int(row), int(column))
        cell_roles[key].update(("pattern", "implication"))
        if state is not None and int(state.grid[key]) == 0:
            for value in state.candidates[key[0]][key[1]]:
                add_candidate(*key, value, "support")

    for row, column, value in placements:
        add_candidate(
            row, column, value, "target", "placement", literal_state="on"
        )
        key = (int(row), int(column))
        cell_roles[key].discard("implication")
        cell_roles[key].update(("target", "effect"))
    for row, column, value in eliminations:
        add_candidate(
            row, column, value, "target", "elimination", literal_state="off"
        )
        key = (int(row), int(column))
        cell_roles[key].discard("implication")
        cell_roles[key].update(("target", "effect"))

    if isinstance(logic, Mapping):
        raw_dag = logic.get("proof_dag")
        dag = proof_model.proof_dag(raw_dag) if raw_dag is not None else None
        if dag is not None:
            for node in dag.nodes.values():
                if node.conclusion is None:
                    continue
                roles = ["link"]
                if node.kind == "assumption":
                    roles.append("assumption")
                if node.kind == "contradiction":
                    roles.append("contradiction")
                add_literal(node.conclusion, *roles)

        for link in _iter_chain_links(logic):
            source = add_literal(link.get("source"), "link")
            target = add_literal(link.get("target"), "link")
            if source is None or target is None:
                continue
            target_roles = set()
            if (
                not proof_model.is_group_literal(target)
                and not proof_model.is_als_literal(target)
            ):
                target_roles = candidate_roles[_candidate_key(*target[:3])]
            visual_link = _normalise_visual_link({
                "source": link.get("source"),
                "target": link.get("target"),
                "relation": (
                    "contradiction"
                    if "contradiction" in target_roles
                    else (
                        "grouped-implication"
                        if proof_model.is_group_literal(source)
                        or proof_model.is_group_literal(target)
                        or proof_model.is_als_literal(source)
                        or proof_model.is_als_literal(target)
                        else "implication"
                    )
                ),
                "direction": "forward",
                "strength": str(link.get("strength") or "unspecified"),
                "reason": str(link.get("reason") or "unspecified"),
                "support_candidates": link.get("support_candidates", ()),
                "support_house_ids": link.get("support_house_ids", ()),
            })
            if visual_link is not None:
                links.append(visual_link)

    if isinstance(explicit, Mapping):
        for cell in explicit.get("cells", ()) or ():
            key = (int(cell["row"]), int(cell["column"]))
            cell_roles[key].update(cell.get("roles", ()) or ())
        for candidate in explicit.get("candidates", ()) or ():
            add_candidate(
                candidate["row"], candidate["column"], candidate["value"],
                *(candidate.get("roles", ()) or ()),
                literal_state=str(candidate.get("state") or "candidate"),
            )
        for group in explicit.get("groups", ()) or ():
            literal = group
            if "node_type" not in group and "group" not in group:
                literal = {
                    "node_type": "group",
                    "group": {
                        key: value
                        for key, value in group.items()
                        if key in {"digit", "cells", "house_ids", "role"}
                    },
                    "state": group.get("state", "on"),
                }
            add_literal(literal, *(group.get("roles", ()) or ()))
        for link in explicit.get("links", ()) or ():
            normalized = _normalise_visual_link(link)
            if normalized is not None:
                links.append(normalized)

    return {
        "schema_version": VISUAL_EVIDENCE_SCHEMA_VERSION,
        "cells": [
            {"row": row, "column": column, "roles": sorted(roles)}
            for (row, column), roles in sorted(cell_roles.items())
        ],
        "candidates": [
            {
                "row": row, "column": column, "value": value,
                "state": candidate_states[(row, column, value)],
                "roles": sorted(roles),
            }
            for (row, column, value), roles in sorted(candidate_roles.items())
        ],
        "groups": [groups[key] for key in sorted(groups)],
        "links": links,
    }


def build_explanation(
    technique,
    description,
    *,
    technique_id=None,
    primary=(),
    placements=(),
    eliminations=(),
    logic=None,
):
    """Costruisce una spiegazione a sezioni, traducibile e renderizzabile."""
    primary = sorted(set(primary))
    pattern = (
        f"Il pattern {technique} coinvolge {format_cells(primary)}."
        if primary
        else f"Il pattern {technique} è verificato nello stato corrente."
    )
    body = " ".join(str(description or "").split()).strip()
    if body and body[-1] not in ".!?":
        body += "."
    if not body:
        body = "I vincoli della tecnica rendono obbligatoria la conclusione."

    sections = [
        {"kind": "pattern", "label": "Pattern", "text": pattern},
        {"kind": "reasoning", "label": "Ragionamento", "text": body},
    ]
    proof_summary = _proof_summary(technique, logic)
    if proof_summary:
        sections.append({
            "kind": "proof", "label": "Dimostrazione", "text": proof_summary,
        })
    sections.append({
        "kind": "conclusion", "label": "Conclusione",
        "text": f"Di conseguenza, {conclusion_text(placements, eliminations)}.",
    })
    return {
        "schema_version": EXPLANATION_SCHEMA_VERSION,
        "key": f"{technique_id or technique}.default",
        "title": str(technique),
        "sections": sections,
        "facts": {
            "primary_cells": [list(cell) for cell in primary],
            "placements": [list(item) for item in placements],
            "eliminations": [list(item) for item in eliminations],
        },
    }


def render_explanation(explanation):
    return " ".join(
        str(section.get("text") or "").strip()
        for section in explanation.get("sections", ())
        if str(section.get("text") or "").strip()
    )


def normalize_description(
    technique,
    description,
    *,
    primary,
    placements,
    eliminations,
    logic=None,
):
    """Compatibilità testuale: rende la spiegazione strutturata."""
    return render_explanation(build_explanation(
        technique,
        description,
        primary=primary,
        placements=placements,
        eliminations=eliminations,
        logic=logic,
    ))


def snapshot_candidates(state):
    """Copia stabile dei candidati, adatta a log e serializzazione."""
    return [
        [sorted(int(value) for value in state.candidates[row][column])
         for column in range(9)]
        for row in range(9)
    ]


def format_candidate_grid(grid, candidates=None, *, visual_evidence=None):
    """Rende la griglia in pencil marks 3x3, con legenda delle evidenze."""
    if candidates is None and hasattr(grid, "candidates"):
        candidates = grid.candidates
        grid = grid.grid
    if candidates is None:
        candidates = [[set() for _ in range(9)] for _ in range(9)]

    def value_at(row, column):
        try:
            return int(grid[row, column])
        except (TypeError, IndexError):
            return int(grid[row][column])

    border = "+" + "+".join("-" * 11 for _ in range(3)) + "+"
    lines = [border]
    for row in range(9):
        for mini_row in range(3):
            groups = []
            for box in range(3):
                rendered_cells = []
                for column in range(box * 3, box * 3 + 3):
                    solved = value_at(row, column)
                    if solved:
                        cell = f" {solved} " if mini_row == 1 else "   "
                    else:
                        values = set(candidates[row][column])
                        digits = range(mini_row * 3 + 1, mini_row * 3 + 4)
                        cell = "".join(
                            str(digit) if digit in values else " " for digit in digits
                        )
                    rendered_cells.append(cell)
                groups.append(" ".join(rendered_cells))
            lines.append("|" + "|".join(groups) + "|")
        if row in {2, 5, 8}:
            lines.append(border)

    evidence = visual_evidence or {}
    records = evidence.get("candidates", ()) if isinstance(evidence, Mapping) else ()
    if records:
        lines.append("Evidenze candidati:")
        for item in records:
            roles = ", ".join(item.get("roles", ())) or "support"
            lines.append(
                f"- {format_cell(item['row'], item['column'])}#"
                f"{int(item['value'])}: {roles}"
            )
    return "\n".join(lines)


def print_candidate_grid(grid, candidates=None, *, visual_evidence=None, file=None):
    """Stampa la vista candidate-level e restituisce il testo emesso."""
    rendered = format_candidate_grid(
        grid, candidates, visual_evidence=visual_evidence
    )
    print(rendered, file=file)
    return rendered


__all__ = [
    "CANDIDATE_ROLES",
    "EXPLANATION_SCHEMA_VERSION",
    "LINK_DIRECTIONS",
    "LINK_RELATIONS",
    "VISUAL_EVIDENCE_SCHEMA_VERSION",
    "build_explanation",
    "build_highlight",
    "build_visual_evidence",
    "conclusion_text",
    "format_candidate_grid",
    "format_cell",
    "format_cells",
    "normalize_description",
    "print_candidate_grid",
    "proof_primary_cells",
    "render_explanation",
    "snapshot_candidates",
]
