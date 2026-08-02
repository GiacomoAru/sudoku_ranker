"""Registro dichiarativo dei detector disponibili nel solver.

Il registro collega funzioni Python e ID permanenti del catalogo. Il solver
consuma esclusivamente ``TechniqueRunner`` e non ispeziona nomi di funzione,
closure o nomi visibili delle tecniche per stabilire engine e fallback.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from . import technique_catalog
from . import techniques


RunnerFunction = Callable[[object], list[dict]]


@dataclass(frozen=True, slots=True)
class TechniqueRunner:
    """Detector eseguibile con classificazione esplicita e immutabile."""

    detector_id: str
    technique_ids: tuple[str, ...]
    function: RunnerFunction
    engine_type: str
    fallback_tier: int
    minimum_difficulty: float
    priority: int

    def __post_init__(self):
        if not self.detector_id:
            raise technique_catalog.CatalogValidationError(
                "Un TechniqueRunner deve avere un detector_id."
            )
        if not self.technique_ids:
            raise technique_catalog.CatalogValidationError(
                f"Il detector {self.detector_id!r} non dichiara tecniche."
            )
        if len(set(self.technique_ids)) != len(self.technique_ids):
            raise technique_catalog.CatalogValidationError(
                f"Il detector {self.detector_id!r} dichiara ID duplicati."
            )
        if not callable(self.function):
            raise technique_catalog.CatalogValidationError(
                f"Il detector {self.detector_id!r} non è eseguibile."
            )
        if self.engine_type not in technique_catalog.ENGINE_TYPES:
            raise technique_catalog.CatalogValidationError(
                f"Engine non valido per {self.detector_id!r}."
            )
        if self.fallback_tier not in (0, 1, 2):
            raise technique_catalog.CatalogValidationError(
                f"Fallback tier non valido per {self.detector_id!r}."
            )
        if self.minimum_difficulty < 0:
            raise technique_catalog.CatalogValidationError(
                f"Difficoltà non valida per {self.detector_id!r}."
            )
        if (
            isinstance(self.priority, bool)
            or not isinstance(self.priority, int)
            or self.priority < 0
        ):
            raise technique_catalog.CatalogValidationError(
                f"Priorità non valida per {self.detector_id!r}."
            )

        definitions = tuple(
            technique_catalog.technique_definition(technique_id)
            for technique_id in self.technique_ids
        )
        if any(
            definition.detector_id != self.detector_id
            for definition in definitions
        ):
            raise technique_catalog.CatalogValidationError(
                f"Il detector {self.detector_id!r} dichiara tecniche "
                "assegnate a un altro detector."
            )
        if any(
            definition.engine_type != self.engine_type
            for definition in definitions
        ):
            raise technique_catalog.CatalogValidationError(
                f"Engine incoerente per {self.detector_id!r}."
            )
        if any(
            definition.fallback_tier != self.fallback_tier
            for definition in definitions
        ):
            raise technique_catalog.CatalogValidationError(
                f"Fallback tier incoerente per {self.detector_id!r}."
            )
        expected_minimum = min(
            definition.base_difficulty
            for definition in definitions
        )
        if self.minimum_difficulty != expected_minimum:
            raise technique_catalog.CatalogValidationError(
                f"Difficoltà minima incoerente per {self.detector_id!r}."
            )
        expected_priority = min(
            definition.priority
            for definition in definitions
            if definition.base_difficulty == expected_minimum
        )
        if self.priority != expected_priority:
            raise technique_catalog.CatalogValidationError(
                f"Priorità incoerente per {self.detector_id!r}."
            )

    def collect(self, state):
        """Esegue il detector tramite l'adattatore registrato."""
        return self.function(state)


def _cached_local_function(detector_id, function, args):
    def collect(state):
        return techniques._cached_local(
            state,
            detector_id,
            function,
            *args,
        )

    return collect


def _runner(detector_id, technique_ids, function):
    technique_ids = tuple(technique_ids)
    definitions = tuple(
        technique_catalog.technique_definition(technique_id)
        for technique_id in technique_ids
    )

    misplaced = tuple(
        definition.id
        for definition in definitions
        if definition.detector_id != detector_id
    )
    if misplaced:
        raise technique_catalog.CatalogValidationError(
            f"Detector {detector_id!r} incoerente per: "
            f"{', '.join(misplaced)}."
        )

    engine_types = {definition.engine_type for definition in definitions}
    fallback_tiers = {
        definition.fallback_tier for definition in definitions
    }
    if len(engine_types) != 1:
        raise technique_catalog.CatalogValidationError(
            f"Il detector {detector_id!r} mescola engine differenti."
        )
    if len(fallback_tiers) != 1:
        raise technique_catalog.CatalogValidationError(
            f"Il detector {detector_id!r} mescola fallback tier differenti."
        )

    minimum_difficulty = min(
        definition.base_difficulty
        for definition in definitions
    )
    minimum_priority = min(
        definition.priority
        for definition in definitions
        if definition.base_difficulty == minimum_difficulty
    )

    return TechniqueRunner(
        detector_id=detector_id,
        technique_ids=technique_ids,
        function=function,
        engine_type=engine_types.pop(),
        fallback_tier=fallback_tiers.pop(),
        minimum_difficulty=minimum_difficulty,
        priority=minimum_priority,
    )


def _local(detector_id, technique_ids, function, *args):
    return _runner(
        detector_id,
        technique_ids,
        _cached_local_function(detector_id, function, args),
    )


def _logic(detector_id, technique_ids, function):
    return _runner(detector_id, technique_ids, function)


_DECLARED_RUNNERS = (
    _local(
        "last_value",
        ("single.last_value",),
        techniques.last_value,
    ),
    _local(
        "naked_single",
        ("single.naked",),
        techniques.naked_single,
    ),
    _local(
        "hidden_single",
        ("single.hidden.box", "single.hidden.line"),
        techniques.hidden_single,
    ),
    _local(
        "direct_locked",
        ("direct.pointing", "direct.claiming"),
        techniques.direct_locked_candidates,
    ),
    _local(
        "direct_hidden_subset:2",
        ("direct.hidden_pair",),
        techniques.direct_hidden_subset,
        2,
    ),
    _local(
        "direct_hidden_subset:3",
        ("direct.hidden_triple",),
        techniques.direct_hidden_subset,
        3,
    ),
    _local(
        "locked_candidates",
        ("intersection.pointing", "intersection.claiming"),
        techniques.locked_candidates,
    ),
    _local(
        "naked_subset:2",
        ("subset.naked.2",),
        techniques.naked_subset,
        2,
    ),
    _local(
        "hidden_subset:2",
        ("subset.hidden.2",),
        techniques.hidden_subset,
        2,
    ),
    _local(
        "naked_subset:3",
        ("subset.naked.3",),
        techniques.naked_subset,
        3,
    ),
    _local(
        "hidden_subset:3",
        ("subset.hidden.3",),
        techniques.hidden_subset,
        3,
    ),
    _local(
        "naked_subset:4",
        ("subset.naked.4",),
        techniques.naked_subset,
        4,
    ),
    _local(
        "hidden_subset:4",
        ("subset.hidden.4",),
        techniques.hidden_subset,
        4,
    ),
    _local(
        "naked_subset:5",
        ("subset.naked.5",),
        techniques.naked_subset,
        5,
    ),
    _local(
        "naked_subset:6",
        ("subset.naked.6",),
        techniques.naked_subset,
        6,
    ),
    _local(
        "fish",
        technique_catalog.TECHNIQUE_IDS_BY_DETECTOR["fish"],
        techniques.generalized_fish,
    ),
    _logic(
        "kraken",
        ("kraken.fish.type1", "kraken.fish.type2"),
        techniques.kraken,
    ),
    _logic(
        "coloring",
        technique_catalog.TECHNIQUE_IDS_BY_DETECTOR["coloring"],
        techniques.coloring,
    ),
    _local(
        "skyscraper",
        ("sdp.skyscraper",),
        techniques.skyscraper,
    ),
    _local(
        "two_string_kite",
        ("sdp.two_string_kite",),
        techniques.two_string_kite,
    ),
    _local(
        "empty_rectangle",
        ("sdp.empty_rectangle",),
        techniques.empty_rectangle,
    ),
    _local("y_wing", ("wing.xy",), techniques.y_wing),
    _local("xyz_wing", ("wing.xyz",), techniques.xyz_wing),
    _local("w_wing", ("wing.w",), techniques.w_wing),
    _local(
        "als",
        technique_catalog.TECHNIQUE_IDS_BY_DETECTOR["als"],
        techniques.als,
    ),
    _local(
        "templates",
        ("template.single_digit",),
        techniques.templates,
    ),
    _local(
        "ur_type_1",
        ("unique.ur.1",),
        techniques.unique_rectangle_type1,
    ),
    _local(
        "ur_type_2",
        ("unique.ur.2",),
        techniques.unique_rectangle_type2,
    ),
    _local(
        "ur_type_3",
        ("unique.ur.3",),
        techniques.unique_rectangle_type3,
    ),
    _local(
        "ur_type_4",
        ("unique.ur.4",),
        techniques.unique_rectangle_type4,
    ),
    _local(
        "ur_type_5",
        ("unique.ur.5",),
        techniques.unique_rectangle_type5,
    ),
    _local(
        "ur_type_6",
        ("unique.ur.6",),
        techniques.unique_rectangle_type6,
    ),
    _local(
        "hidden_rectangle",
        ("unique.hidden_rectangle",),
        techniques.hidden_rectangle,
    ),
    _local(
        "avoidable_rectangle:1",
        ("unique.avoidable.1",),
        techniques.avoidable_rectangle_type1,
    ),
    _local(
        "avoidable_rectangle:2",
        ("unique.avoidable.2",),
        techniques.avoidable_rectangle_type2,
    ),
    _local(
        "unique_loop",
        (
            "unique.loop.1",
            "unique.loop.2",
            "unique.loop.3",
            "unique.loop.4",
        ),
        techniques.unique_loops,
    ),
    _local(
        "bug_plus_one",
        ("unique.bug.1",),
        techniques.bug_plus_one,
    ),
    _local(
        "bug_types",
        (
            "unique.bug.2",
            "unique.bug.4",
            "unique.bug.3.2",
            "unique.bug.3.3",
            "unique.bug.3.4",
        ),
        techniques.bug_types_2_to_4,
    ),
    _local(
        "sue_de_coq",
        (
            "misc.sue_de_coq.basic",
            "misc.sue_de_coq.extended",
        ),
        techniques.sue_de_coq,
    ),
    _local(
        "aligned_pair_exclusion",
        ("exclusion.aligned_pair",),
        techniques.aligned_pair_exclusion,
    ),
    _local(
        "aligned_triplet_exclusion",
        ("exclusion.aligned_triple",),
        techniques.aligned_triplet_exclusion,
    ),
    _logic(
        "bidirectional_x_cycle",
        ("se.bidirectional_x_cycle",),
        techniques.bidirectional_x_cycle,
    ),
    _logic(
        "xy_chain",
        ("chain.remote_pair", "chain.xy"),
        techniques.xy_chain,
    ),
    _logic(
        "bidirectional_y_cycle",
        ("loop.xy", "se.bidirectional_y_cycle"),
        techniques.bidirectional_y_cycle,
    ),
    _logic(
        "forcing_x_chain",
        ("sdp.turbot_fish", "chain.x", "se.forcing_x_chain"),
        techniques.forcing_x_chain,
    ),
    _logic(
        "forcing_chain",
        ("loop.dnl", "se.forcing_chain"),
        techniques.forcing_chain,
    ),
    _logic(
        "aic",
        ("chain.aic.type1", "chain.aic.type2"),
        techniques.aic,
    ),
    _logic(
        "bidirectional_cycle",
        ("loop.cnl", "se.bidirectional_cycle"),
        techniques.bidirectional_cycle,
    ),
    _logic(
        "grouped_chain",
        (
            "chain.grouped.x",
            "loop.grouped.dnl",
            "chain.grouped.aic",
            "loop.grouped.cnl",
        ),
        techniques.grouped_chain,
    ),
    _logic(
        "nishio",
        ("forcing.nishio",),
        techniques.nishio,
    ),
    _logic(
        "cell_forcing_chain",
        ("forcing.cell",),
        techniques.cell_forcing_chain,
    ),
    _logic(
        "region_forcing_chain",
        ("forcing.region",),
        techniques.region_forcing_chain,
    ),
    _logic(
        "dynamic_forcing_chain",
        (
            "forcing.dynamic",
            "forcing.dynamic.contradiction",
            "forcing.dynamic.double",
            "forcing.dynamic.cell",
            "forcing.dynamic.region",
        ),
        techniques.dynamic_forcing_chain,
    ),
    _logic(
        "dynamic_forcing_chain_plus",
        (
            "forcing.plus",
            "forcing.plus.contradiction",
            "forcing.plus.double",
            "forcing.plus.cell",
            "forcing.plus.region",
        ),
        techniques.dynamic_forcing_chain_plus,
    ),
    _logic(
        "forcing_net",
        (
            "forcing.net.contradiction",
            "forcing.net.double",
            "forcing.net.cell",
            "forcing.net.region",
        ),
        techniques.forcing_net,
    ),
    _logic(
        "nested_forcing_chain",
        (
            "nested.forcing_chain",
            "nested.contradiction",
            "nested.double",
            "nested.cell",
            "nested.region",
        ),
        techniques.nested_forcing_chain,
    ),
    _logic(
        "complete_forcing_tree",
        ("forcing.complete_tree",),
        techniques.complete_forcing_tree,
    ),
)


def _validate_registry(runners):
    detector_ids = [runner.detector_id for runner in runners]
    if len(detector_ids) != len(set(detector_ids)):
        raise technique_catalog.CatalogValidationError(
            "Il registro contiene detector_id duplicati."
        )

    technique_catalog.validate_detector_registry({
        runner.detector_id: runner.technique_ids
        for runner in runners
    })


_validate_registry(_DECLARED_RUNNERS)

TECHNIQUE_RUNNERS = tuple(sorted(
    _DECLARED_RUNNERS,
    key=lambda runner: (
        runner.minimum_difficulty,
        runner.priority,
        runner.detector_id,
    ),
))
RUNNER_BY_DETECTOR_ID = {
    runner.detector_id: runner
    for runner in TECHNIQUE_RUNNERS
}
RUNNERS_BY_FALLBACK_TIER = {
    tier: tuple(
        runner
        for runner in TECHNIQUE_RUNNERS
        if runner.fallback_tier == tier
    )
    for tier in (0, 1, 2)
}
ORDINARY_RUNNERS = RUNNERS_BY_FALLBACK_TIER[0]
NESTED_RUNNERS = RUNNERS_BY_FALLBACK_TIER[1]
COMPLETE_TREE_RUNNERS = RUNNERS_BY_FALLBACK_TIER[2]


__all__ = [
    "COMPLETE_TREE_RUNNERS",
    "NESTED_RUNNERS",
    "ORDINARY_RUNNERS",
    "RUNNERS_BY_FALLBACK_TIER",
    "RUNNER_BY_DETECTOR_ID",
    "TECHNIQUE_RUNNERS",
    "TechniqueRunner",
]
