"""Schema condiviso delle prove logiche e delle relative metriche.

Le metriche dichiarate dal motore descrivono la prova completa e sono
autorevoli. Le catene presenti in ``logic`` sono invece una vista destinata
alla presentazione: vengono usate soltanto per completare metriche assenti.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence


PROOF_SCHEMA_VERSION = "2.0.0"
PROOF_METRICS_VERSION = "2.0.0"

PROOF_METRIC_FIELDS = (
    "proof_node_count",
    "proof_edge_count",
    "displayed_literal_count",
    "assumption_count",
    "chain_count",
    "max_chain_length",
    "total_chain_length",
    "branch_count",
    "leaf_count",
    "nested_depth",
    "nested_subproof_count",
)


def _count(value, *, field):
    """Converte un conteggio in intero non negativo e finito."""
    if isinstance(value, bool):
        return int(value)

    try:
        number = float(value)
    except (TypeError, ValueError) as error:
        raise ValueError(
            f"La metrica {field!r} deve essere numerica."
        ) from error

    if not math.isfinite(number) or number < 0 or not number.is_integer():
        raise ValueError(
            f"La metrica {field!r} deve essere un intero non negativo."
        )

    return int(number)


def _items(value):
    if value is None or isinstance(value, (str, bytes, Mapping)):
        return []
    if isinstance(value, Sequence):
        return list(value)
    try:
        return list(value)
    except TypeError:
        return []


def _literal_signature(literal):
    """Firma stabile per contare i letterali mostrati senza duplicati."""
    if isinstance(literal, Mapping):
        return (
            literal.get("row"),
            literal.get("column"),
            literal.get("value"),
            literal.get("state"),
        )
    if isinstance(literal, (tuple, list)):
        return tuple(literal)
    return repr(literal)


def _derive_metrics_from_display(logic):
    assumptions = _items(logic.get("assumptions"))
    chains = [
        chain
        for chain in (
            _items(raw_chain)
            for raw_chain in _items(logic.get("chains"))
        )
        if chain
    ]
    chain_lengths = [len(chain) for chain in chains]
    displayed_literals = {
        _literal_signature(literal)
        for chain in chains
        for literal in chain
    }
    displayed_literals.update(
        _literal_signature(literal)
        for literal in assumptions
    )
    displayed_literal_count = len(displayed_literals)

    return {
        # In assenza di un grafo del motore, i letterali mostrati sono il
        # solo fallback disponibile per nodi e archi della prova.
        "proof_node_count": displayed_literal_count,
        "proof_edge_count": sum(
            max(length - 1, 0) for length in chain_lengths
        ),
        "displayed_literal_count": displayed_literal_count,
        "assumption_count": len(assumptions),
        "chain_count": len(chains),
        "max_chain_length": max(chain_lengths, default=0),
        "total_chain_length": sum(chain_lengths),
        # Una vista lineare non contiene abbastanza informazione per
        # ricostruire ramificazione, foglie o sottoprove nested.
        "branch_count": 0,
        "leaf_count": 0,
        "nested_depth": 0,
        "nested_subproof_count": 0,
    }


def normalize_proof_metrics(logic):
    """Restituisce le metriche v2, dando precedenza ai valori del motore.

    La presenza di una chiave esplicita e' significativa: anche uno zero
    dichiarato dal motore prevale su un valore ricavabile dalla vista. Il
    vecchio nome ``nesting_depth`` viene convertito in ``nested_depth``.
    """
    if logic is None:
        logic = {}
    if not isinstance(logic, Mapping):
        raise TypeError("La prova logica deve essere una mappa.")

    raw_metrics = logic.get("metrics") or {}
    if not isinstance(raw_metrics, Mapping):
        raise TypeError("logic['metrics'] deve essere una mappa.")

    explicit = dict(raw_metrics)
    if (
        "nested_depth" not in explicit
        and "nesting_depth" in explicit
    ):
        explicit["nested_depth"] = explicit["nesting_depth"]

    derived = _derive_metrics_from_display(logic)
    metrics = {"metrics_version": PROOF_METRICS_VERSION}

    for field in PROOF_METRIC_FIELDS:
        value = explicit[field] if field in explicit else derived[field]
        metrics[field] = _count(value, field=field)

    return metrics


def normalize_proof(logic):
    """Materializza lo schema v2 conservando i dettagli non strutturali."""
    if logic is None:
        logic = {}
    if not isinstance(logic, Mapping):
        raise TypeError("La prova logica deve essere una mappa.")

    proof = dict(logic)
    proof["schema_version"] = PROOF_SCHEMA_VERSION
    proof["kind"] = str(proof.get("kind") or "unspecified")
    proof["assumptions"] = _items(proof.get("assumptions"))
    proof["chains"] = [
        _items(chain) for chain in _items(proof.get("chains"))
    ]
    proof["metrics"] = normalize_proof_metrics(proof)
    return proof
