"""Schema serializzato delle prove logiche e delle relative metriche.

Da P06 il ``proof_dag`` e' autorevole. ``chains``, ``chain_links`` e
``metrics`` sono viste derivate, conservate nel payload per rendere semplici
renderer, classificatori e archivi.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from . import proof as proof_model


PROOF_SCHEMA_VERSION = "3.5.0"
PROOF_METRICS_VERSION = "3.2.0"

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
    "group_node_count",
    "max_group_size",
    "als_node_count",
    "als_cell_count",
    "rcc_count",
    "fork_node_count",
    "merge_node_count",
    "max_parent_count",
    "template_count",
    "kraken_branch_count",
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
        "group_node_count": 0,
        "max_group_size": 0,
        "als_node_count": 0,
        "als_cell_count": 0,
        "rcc_count": 0,
        "fork_node_count": 0,
        "merge_node_count": 0,
        "max_parent_count": 0,
        "template_count": 0,
        "kraken_branch_count": 0,
    }


def normalize_proof_metrics(logic):
    """Restituisce le metriche v3 derivate dal DAG quando presente.

    La presenza di una chiave esplicita e' significativa: anche uno zero
    dichiarato dal motore prevale su un valore ricavabile dalla vista. Il
    vecchio nome ``nesting_depth`` viene convertito in ``nested_depth``.
    """
    if logic is None:
        logic = {}
    if not isinstance(logic, Mapping):
        raise TypeError("La prova logica deve essere una mappa.")

    raw_dag = logic.get("proof_dag")
    dag_metrics = None
    if raw_dag is not None:
        dag_metrics = proof_model.proof_dag(raw_dag).metrics()

    raw_metrics = logic.get("metrics") or {}
    if not isinstance(raw_metrics, Mapping):
        raise TypeError("logic['metrics'] deve essere una mappa.")

    explicit = dict(dag_metrics if dag_metrics is not None else raw_metrics)
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


def normalize_proof(logic, *, placements=None, eliminations=None):
    """Materializza lo schema v3 e rende il DAG fonte autorevole."""
    if logic is None:
        logic = {}
    if not isinstance(logic, Mapping):
        raise TypeError("La prova logica deve essere una mappa.")

    proof = dict(logic)
    proof["schema_version"] = PROOF_SCHEMA_VERSION
    proof["kind"] = str(proof.get("kind") or "unspecified")
    assumptions = _items(proof.get("assumptions"))
    chains = [_items(chain) for chain in _items(proof.get("chains"))]
    dag = proof_model.proof_dag(proof.get("proof_dag"))
    if dag is None:
        dag = proof_model.ProofDAG.from_chains(
            assumptions=assumptions,
            chains=chains,
            reasons=_items(proof.get("reasons")),
            proof_kind=proof["kind"],
            placements=placements or (),
            eliminations=eliminations or (),
        )
    elif placements is not None or eliminations is not None:
        dag = dag.select_conclusions(
            placements=placements or (),
            eliminations=eliminations or (),
        )

    proof["proof_dag"] = dag.to_dict()
    proof["dag_digest"] = dag.digest()
    proof["assumptions"] = [
        proof_model.literal_record(node.conclusion)
        for node in sorted(dag.nodes.values(), key=lambda node: node.id)
        if node.kind == "assumption" and node.conclusion is not None
    ]
    proof["chains"] = [
        [proof_model.literal_record(literal) for literal in chain]
        for chain in dag.derived_chains()
    ]
    proof["chain_links"] = dag.derived_chain_links()
    proof["metrics"] = normalize_proof_metrics(proof)
    return proof


def proof_signature(logic):
    """Firma stabile del DAG, usabile da deduplicazione e tie-break."""
    if not logic or not isinstance(logic, Mapping):
        return ""
    cached = logic.get("dag_digest")
    if cached:
        return str(cached)
    dag = proof_model.proof_dag(logic.get("proof_dag"))
    return "" if dag is None else dag.digest()
