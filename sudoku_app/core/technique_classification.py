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
    "AIC",
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


def _parsed_chains(logic):
    if not isinstance(logic, Mapping):
        return None
    chains = logic.get("chains")
    chain_links = logic.get("chain_links")
    if (
        not isinstance(chains, Sequence)
        or isinstance(chains, (str, bytes))
        or not isinstance(chain_links, Sequence)
        or isinstance(chain_links, (str, bytes))
        or not chains
        or len(chain_links) != len(chains)
    ):
        return None

    result = []
    for raw_chain, raw_links in zip(chains, chain_links):
        chain = tuple(_literal(item) for item in raw_chain)
        if (
            not chain
            or any(item is None for item in chain)
            or not isinstance(raw_links, Sequence)
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
            support_candidates = _triplets(
                raw_link.get("support_candidates")
            )
            try:
                support_house_ids = tuple(sorted({
                    int(item)
                    for item in raw_link.get("support_house_ids", ())
                }))
            except (TypeError, ValueError):
                return None
            if (
                source != chain[index]
                or target != chain[index + 1]
                or reason not in {"peer", "x", "y"}
                or strength not in {"strong", "weak"}
                or "support_candidates" not in raw_link
                or "support_house_ids" not in raw_link
            ):
                return None
            links.append((
                source,
                target,
                reason,
                strength,
                support_candidates,
                support_house_ids,
            ))
        result.append((chain, tuple(links)))
    return tuple(result)


def _single_chain(logic):
    parsed = _parsed_chains(logic)
    if parsed is None or len(parsed) != 1:
        return None
    return parsed[0]


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


def _valid_support(state, link):
    source, target, reason, _, support_candidates, house_ids = link
    endpoints = {source[:3], target[:3]}
    if support_candidates != endpoints:
        return False
    if any(not 0 <= house_id < len(UNITS) for house_id in house_ids):
        return False

    endpoint_cells = {source[:2], target[:2]}
    if reason == "y":
        return not house_ids and source[:2] == target[:2]
    shared_house_ids = {
        house_id
        for house_id, unit in enumerate(UNITS)
        if endpoint_cells <= set(unit)
    }
    if reason == "peer":
        return set(house_ids) == shared_house_ids

    digit = source[2]
    conjugate_house_ids = {
        house_id
        for house_id in shared_house_ids
        if {
            (row, column)
            for row, column in UNITS[house_id]
            if digit in state.candidates[row][column]
        } == endpoint_cells
    }
    return bool(conjugate_house_ids) and set(house_ids) == conjugate_house_ids


def _valid_link(state, link):
    source, target, reason, strength, *_ = link
    if source[3] == target[3]:
        return False
    if not _valid_support(state, link):
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
            or links[link_index][2:4] != ("y", "strong")
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
        for source, target, reason, *_ in links
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


def _endpoint_aic_structure(
    state,
    deduction,
    parsed,
    *,
    allowed,
    required,
):
    """Valida prove T-on -> endpoint -> endpoint -> T-off equivalenti."""
    eliminations = _triplets(deduction.get("eliminations"))
    if not eliminations:
        return None
    common_central = None
    common_links = None
    represented_targets = set()

    for chain, links in parsed:
        if (
            len(chain) < 6
            or not all(_valid_link(state, link) for link in links)
            or not _alternates(links)
            or links[0][3] != "weak"
            or links[-1][3] != "weak"
        ):
            return None
        target = chain[0]
        if (
            not target[3]
            or chain[-1][:3] != target[:3]
            or chain[-1][3]
        ):
            return None
        central = chain[1:-1]
        central_links = links[1:-1]
        if (
            central[0][3]
            or not central[-1][3]
            or len({_item[:3] for _item in central}) != len(central)
            or central_links[0][3] != "strong"
            or central_links[-1][3] != "strong"
        ):
            return None
        reasons = {link[2] for link in central_links}
        if not reasons <= set(allowed) or not set(required) <= reasons:
            return None
        signature = tuple(central)
        link_signature = tuple(
            (link[0], link[1], link[2], link[3])
            for link in central_links
        )
        if common_central is None:
            common_central = signature
            common_links = link_signature
        elif signature != common_central or link_signature != common_links:
            return None
        represented_targets.add(target[:3])

    if not eliminations <= represented_targets:
        return None
    return common_central, common_links, frozenset(represented_targets)


def _continuous_loop_eliminations(state, links):
    allowed = set()
    for link in links:
        source, target, reason, strength, _, house_ids = link
        if strength != "weak":
            continue
        endpoints = {source[:3], target[:3]}
        if reason == "peer":
            for house_id in house_ids:
                for row, column in UNITS[house_id]:
                    candidate = (row, column, source[2])
                    if (
                        candidate not in endpoints
                        and source[2] in state.candidates[row][column]
                    ):
                        allowed.add(candidate)
        elif reason == "y":
            row, column = source[:2]
            for digit in state.candidates[row][column]:
                candidate = (row, column, digit)
                if candidate not in endpoints:
                    allowed.add(candidate)
    return allowed


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
    parsed_chains = _parsed_chains(logic)
    if parsed_chains is None:
        return None
    if parent in {"Forcing X-Chain", "AIC"}:
        endpoint = _endpoint_aic_structure(
            state,
            deduction,
            parsed_chains,
            allowed=(
                {"peer", "x"}
                if parent == "Forcing X-Chain"
                else {"peer", "x", "y"}
            ),
            required=(
                {"peer", "x"}
                if parent == "Forcing X-Chain"
                else {"x", "y"}
            ),
        )
        if endpoint is None:
            return None
        central, central_links, represented_targets = endpoint
        digits = {literal[2] for literal in central}
        first, last = central[0], central[-1]
        if parent == "Forcing X-Chain":
            if len(digits) != 1:
                return None
            for name in (
                "Skyscraper",
                "Two-String Kite",
                "Empty Rectangle",
            ):
                if name in matching_x_patterns:
                    return name
            full_chain, full_links = parsed_chains[0]
            return (
                "Turbot Fish"
                if _is_turbot_fish(full_chain, full_links, deduction)
                else "X-Chain"
            )
        if len(digits) == 1:
            return None
        if first[2] == last[2]:
            return "AIC Type 1"
        if last[:2] not in peers(first[0], first[1]):
            return None
        cross_candidates = {
            (first[0], first[1], last[2]),
            (last[0], last[1], first[2]),
        }
        existing_cross_candidates = {
            candidate
            for candidate in cross_candidates
            if candidate[2] in state.candidates[candidate[0]][candidate[1]]
        }
        if not represented_targets <= existing_cross_candidates:
            return None
        return "AIC Type 2"

    if len(parsed_chains) != 1:
        return None
    chain, links = parsed_chains[0]

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
        return "Discontinuous Nice Loop" if _alternates(links) else parent

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
    if not _alternates(links):
        return parent
    eliminations = _triplets(deduction.get("eliminations"))
    if not eliminations or not eliminations <= _continuous_loop_eliminations(
        state, links
    ):
        return None
    return "Continuous Nice Loop"


__all__ = ["classify_logic_technique"]
