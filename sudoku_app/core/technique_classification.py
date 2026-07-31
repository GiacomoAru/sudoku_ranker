"""Classificazione strutturale delle catene statiche.

I nomi specifici non vengono dedotti dal runner, dalla lunghezza della prova o
dal suo ``kind``.  Questo modulo verifica invece letterali, ordine degli archi,
forza dei link e vincoli Sudoku nello stato che ha prodotto la deduzione.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .data_structure import UNITS, peers


Literal = tuple[int, int, int, bool]

_STATIC_TECHNIQUES = frozenset({
    "Bidirectional X-Cycle",
    "XY-Chain",
    "Bidirectional Y-Cycle",
    "Forcing X-Chain",
    "Forcing Chain",
    "Bidirectional Cycle",
})


def _literal(value) -> Literal | None:
    if not isinstance(value, Mapping):
        return None
    try:
        row = int(value["row"])
        column = int(value["column"])
        digit = int(value["value"])
    except (KeyError, TypeError, ValueError):
        return None
    raw_state = value.get("state")
    if raw_state in (True, 1, "on", "true", "True"):
        is_on = True
    elif raw_state in (False, 0, "off", "false", "False"):
        is_on = False
    else:
        return None
    if not (0 <= row < 9 and 0 <= column < 9 and 1 <= digit <= 9):
        return None
    return row, column, digit, is_on


def _triplets(items):
    result = set()
    for item in items or ():
        try:
            row, column, digit = item
            result.add((int(row), int(column), int(digit)))
        except (TypeError, ValueError):
            continue
    return result


def _single_chain(logic):
    if not isinstance(logic, Mapping):
        return None
    chains = logic.get("chains")
    chain_links = logic.get("chain_links")
    if (
        not isinstance(chains, Sequence)
        or isinstance(chains, (str, bytes))
        or len(chains) != 1
        or not isinstance(chain_links, Sequence)
        or isinstance(chain_links, (str, bytes))
        or len(chain_links) != 1
    ):
        return None

    chain = tuple(_literal(item) for item in chains[0])
    if not chain or any(item is None for item in chain):
        return None
    raw_links = chain_links[0]
    if (
        not isinstance(raw_links, Sequence)
        or isinstance(raw_links, (str, bytes))
        or len(raw_links) != len(chain) - 1
    ):
        return None

    links = []
    for index, raw_link in enumerate(raw_links):
        if not isinstance(raw_link, Mapping):
            return None
        source = _literal(raw_link.get("source"))
        target = _literal(raw_link.get("target"))
        reason = raw_link.get("reason")
        strength = raw_link.get("strength")
        if (
            source != chain[index]
            or target != chain[index + 1]
            or reason not in {"peer", "x", "y"}
            or strength not in {"strong", "weak"}
        ):
            return None
        links.append((source, target, reason, strength))
    return chain, tuple(links)


def _candidate_values(state, literal):
    return set(state.candidates[literal[0]][literal[1]])


def _is_conjugate_pair(state, first, second):
    if first[2] != second[2] or first[:2] == second[:2]:
        return False
    cells = {first[:2], second[:2]}
    digit = first[2]
    for unit in UNITS:
        if not cells <= set(unit):
            continue
        positions = {
            (row, column)
            for row, column in unit
            if digit in state.candidates[row][column]
        }
        if positions == cells:
            return True
    return False


def _valid_link(state, link):
    source, target, reason, strength = link
    if source[3] == target[3]:
        return False

    expected_strength = "weak" if source[3] else "strong"
    if strength != expected_strength:
        return False

    if reason == "peer":
        return (
            strength == "weak"
            and source[2] == target[2]
            and source[:2] != target[:2]
            and target[:2] in peers(source[0], source[1])
        )

    if reason == "x":
        return strength == "strong" and _is_conjugate_pair(
            state, source, target
        )

    if source[:2] != target[:2] or source[2] == target[2]:
        return False
    values = _candidate_values(state, source)
    if not {source[2], target[2]} <= values:
        return False
    return strength == "weak" or values == {source[2], target[2]}


def _alternates(links):
    strengths = [link[3] for link in links]
    return all(
        first != second
        for first, second in zip(strengths, strengths[1:])
    )


def _valid_chain(
    state,
    deduction,
    chain,
    links,
    *,
    allowed,
    required,
    closed,
):
    if len(chain) < 4 or not all(_valid_link(state, link) for link in links):
        return False
    reasons = {link[2] for link in links}
    if not reasons <= set(allowed) or not set(required) <= reasons:
        return False

    body = chain[:-1] if closed else chain
    if len(set(body)) != len(body):
        return False

    if closed:
        return chain[0] == chain[-1]

    first, last = chain[0], chain[-1]
    if first[:3] != last[:3] or first[3] == last[3]:
        return False
    candidate = first[:3]
    if first[3]:
        return candidate in _triplets(deduction.get("eliminations"))
    return candidate in _triplets(deduction.get("placements"))


def _xy_path_cells(state, deduction, chain, links):
    if not _valid_chain(
        state,
        deduction,
        chain,
        links,
        allowed={"peer", "y"},
        required={"peer", "y"},
        closed=False,
    ):
        return None
    if not chain[0][3] or chain[-1][3] or len(chain[1:-1]) % 2:
        return None
    if links[0][2] != "peer" or links[-1][2] != "peer":
        return None

    cells = []
    interior = chain[1:-1]
    for offset in range(0, len(interior), 2):
        off_literal, on_literal = interior[offset:offset + 2]
        link_index = offset + 1
        if (
            off_literal[3]
            or not on_literal[3]
            or off_literal[:2] != on_literal[:2]
            or off_literal[2] == on_literal[2]
            or links[link_index][2:] != ("y", "strong")
        ):
            return None
        values = _candidate_values(state, off_literal)
        if values != {off_literal[2], on_literal[2]}:
            return None
        cells.append((off_literal[:2], frozenset(values)))

    if len(cells) < 3 or len({cell for cell, _ in cells}) != len(cells):
        return None
    return tuple(cells)


def _is_xy_cycle(state, chain, links):
    if len(chain) < 7:
        return False
    body = chain[:-1]
    cells = {literal[:2] for literal in body}
    if len(cells) < 3:
        return False
    for cell in cells:
        literals = [literal for literal in body if literal[:2] == cell]
        values = set(state.candidates[cell[0]][cell[1]])
        if (
            len(literals) != 2
            or {literal[3] for literal in literals} != {False, True}
            or {literal[2] for literal in literals} != values
            or len(values) != 2
        ):
            return False
    return all(
        (reason == "y") == (source[:2] == target[:2])
        for source, target, reason, _ in links
    )


def _is_turbot_fish(chain, links, deduction):
    if (
        not chain[0][3]
        or chain[-1][3]
        or len(links) != 5
        or [link[2] for link in links] != ["peer", "x", "peer", "x", "peer"]
        or [link[3] for link in links] != ["weak", "strong", "weak", "strong", "weak"]
    ):
        return False
    cells = [literal[:2] for literal in chain[:-1]]
    return (
        len(set(cells)) == 5
        and chain[0][:3] in _triplets(deduction.get("eliminations"))
    )


def classify_logic_technique(
    state,
    parent,
    deduction,
    *,
    matching_x_patterns=(),
):
    """Restituisce il nome strutturale, o ``None`` per una prova invalida."""
    logic = deduction.get("logic", {})

    forcing_subtypes = {
        "dynamic-contradiction": "Contradiction",
        "dynamic-reduction": "Double",
        "dynamic-cell-reduction": "Cell",
        "dynamic-region-reduction": "Region",
    }
    subtype = forcing_subtypes.get(logic.get("kind"))
    if subtype and parent == "Dynamic Forcing Chain":
        return f"Dynamic {subtype} Forcing Chain"
    if subtype and parent == "Dynamic Forcing Chain Plus":
        return f"Dynamic {subtype} Forcing Chain Plus"
    if subtype and parent == "Nested Forcing Chain":
        return f"Nested {subtype} Forcing Chain"

    if parent not in _STATIC_TECHNIQUES:
        return parent
    parsed = _single_chain(logic)
    if parsed is None:
        return None
    chain, links = parsed

    if parent == "XY-Chain":
        cells = _xy_path_cells(state, deduction, chain, links)
        if cells is None:
            return None
        pairs = [values for _, values in cells]
        if len(cells) >= 4 and len(cells) % 2 == 0 and len(set(pairs)) == 1:
            return "Remote Pair"
        return "XY-Chain"

    if parent == "Bidirectional Y-Cycle":
        if not _valid_chain(
            state,
            deduction,
            chain,
            links,
            allowed={"peer", "y"},
            required={"peer", "y"},
            closed=True,
        ):
            return None
        return "XY-Cycle" if _is_xy_cycle(state, chain, links) else parent

    if parent == "Bidirectional X-Cycle":
        return parent if _valid_chain(
            state,
            deduction,
            chain,
            links,
            allowed={"peer", "x"},
            required={"peer", "x"},
            closed=True,
        ) else None

    if parent == "Forcing X-Chain":
        if not _valid_chain(
            state,
            deduction,
            chain,
            links,
            allowed={"peer", "x"},
            required={"peer", "x"},
            closed=False,
        ):
            return None
        for name in (
            "Skyscraper",
            "Two-String Kite",
            "Empty Rectangle",
        ):
            if name in matching_x_patterns:
                return name
        return "Turbot Fish" if _is_turbot_fish(chain, links, deduction) else parent

    if parent == "Forcing Chain":
        if not _valid_chain(
            state,
            deduction,
            chain,
            links,
            allowed={"peer", "x", "y"},
            required={"x", "y"},
            closed=False,
        ):
            return None
        return "Alternating Inference Chain" if _alternates(links) else parent

    if not _valid_chain(
        state,
        deduction,
        chain,
        links,
        allowed={"peer", "x", "y"},
        required={"x", "y"},
        closed=True,
    ):
        return None
    return "Continuous Nice Loop" if _alternates(links) else parent


__all__ = ["classify_logic_technique"]
