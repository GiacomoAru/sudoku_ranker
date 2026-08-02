"""Catalogo autorevole delle tecniche attualmente supportate.

Il modulo non importa il solver né i detector: in questo modo difficoltà,
tassonomia e registro possono dipendere dal catalogo senza creare cicli di
import.  ``sudoku_app.core.techniques`` completa la validazione a import
terminato, confrontando i ``detector_id`` qui dichiarati con i runner reali.

Le mappe in fondo al file sono export di compatibilità generati dal catalogo.
Non costituiscono una seconda fonte di verità.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
import math


TECHNIQUE_CATALOG_VERSION = "1.5.0"

LEGACY_TECHNIQUE_ALIASES = {
    "Nested Forcing Chain": "Complete Forcing Tree",
    "Nested Contradiction Forcing Chain": "Complete Forcing Tree",
}

RATING_KINDS = frozenset({"se", "pseudo_se", "project"})
ENGINE_TYPES = frozenset({"local", "logic", "nested", "complete_tree"})
IMPLEMENTATION_STATUSES = frozenset({
    "implemented",
    "disabled",
    "deprecated",
    "planned",
})


@dataclass(frozen=True, slots=True)
class TechniqueAlias:
    """Nome alternativo valido all'interno di uno specifico namespace."""

    name: str
    namespace: str = "common"


@dataclass(frozen=True, slots=True)
class TechniqueDefinition:
    """Definizione stabile e serializzabile di una tecnica Sudoku."""

    id: str
    canonical_name: str
    display_name_it: str

    aliases: tuple[TechniqueAlias, ...]

    family_id: str
    strategy_id: str
    parent_id: str | None
    se_equivalent_parent_id: str | None

    base_difficulty: float
    rating_kind: str

    engine_type: str
    fallback_tier: int
    priority: int

    detector_id: str | None
    implementation_status: str
    abstract: bool

    requires_unique_solution: bool
    proof_metric_profile: tuple[str, ...]


class CatalogValidationError(ValueError):
    """Il catalogo o il registro dei detector non è coerente."""


FAMILY_DISPLAY_NAMES_IT = {
    "direct_placements": "Inserimenti diretti",
    "locked_candidates": "Intersezioni box/linee",
    "subsets": "Sottoinsiemi bloccati",
    "fish": "Fish",
    "wings": "Wings",
    "uniqueness": "Unicita",
    "exclusion": "Exclusion",
    "single_digit_patterns": "Pattern a cifra singola",
    "coloring": "Coloring",
    "bivalue_chains": "Catene bivalue",
    "bidirectional_cycles": "Cicli bidirezionali",
    "forcing_chains": "Catene forzanti",
    "assumption_logic": "Assunzioni logiche",
    "multiple_forcing": "Forcing multipli",
    "dynamic_forcing": "Forcing dinamici",
    "nested_forcing": "Forcing annidati",
    "exhaustive_forcing": "Exhaustive Forcing",
}

STRATEGY_DISPLAY_NAMES_IT = {
    "elementary": "Tecniche elementari",
    "subsets_intersections": "Sottoinsiemi e intersezioni",
    "fish_wings": "Fish e wings",
    "uniqueness_exclusion": "Unicita ed esclusione",
    "single_digit_patterns": "Pattern a cifra singola",
    "static_chains": "Catene statiche",
    "assumption_logic": "Assunzioni logiche",
    "multiple_forcing": "Forcing multipli",
    "dynamic_forcing": "Forcing dinamici",
    "nested_forcing": "Forcing annidati",
    "last_resort": "Last Resort",
}


LOCAL_METRICS = (
    "support_cell_count",
    "unit_count",
    "candidate_count",
    "conclusion_count",
)
SUBSET_METRICS = (
    "subset_size",
    "subset_cell_count",
    "subset_digit_count",
    "unit_count",
)
FISH_METRICS = (
    "proof_node_count",
    "fish_size",
    "base_set_count",
    "cover_set_count",
    "fin_count",
    "endo_fin_count",
    "cannibalistic_count",
)
CHAIN_METRICS = (
    "proof_node_count",
    "proof_edge_count",
    "chain_count",
    "max_chain_length",
)
COLORING_METRICS = CHAIN_METRICS + (
    "color_component_count",
    "color_node_count",
    "color_link_count",
)
FORCING_METRICS = (
    "proof_node_count",
    "assumption_count",
    "branch_count",
    "leaf_count",
    "max_chain_length",
)
NESTED_METRICS = FORCING_METRICS + (
    "nested_depth",
    "nested_subproof_count",
)


def _aliases(*names: str, namespace: str = "common"):
    return tuple(TechniqueAlias(name, namespace) for name in names)


def _entry(
    technique_id,
    canonical_name,
    base_difficulty,
    family_id,
    strategy_id,
    detector_id,
    *,
    aliases=(),
    display_name_it=None,
    parent_id=None,
    se_equivalent_parent_id=None,
    rating_kind="se",
    engine_type="local",
    fallback_tier=0,
    implementation_status="implemented",
    abstract=False,
    requires_unique_solution=False,
    proof_metric_profile=LOCAL_METRICS,
):
    return {
        "id": technique_id,
        "canonical_name": canonical_name,
        "display_name_it": display_name_it or canonical_name,
        "aliases": tuple(aliases),
        "family_id": family_id,
        "strategy_id": strategy_id,
        "parent_id": parent_id,
        "se_equivalent_parent_id": se_equivalent_parent_id,
        "base_difficulty": float(base_difficulty),
        "rating_kind": rating_kind,
        "engine_type": engine_type,
        "fallback_tier": int(fallback_tier),
        "detector_id": detector_id,
        "implementation_status": implementation_status,
        "abstract": bool(abstract),
        "requires_unique_solution": bool(requires_unique_solution),
        "proof_metric_profile": tuple(proof_metric_profile),
    }


# L'ordine delle righe conserva l'ordine storico usato come spareggio tra
# tecniche con la stessa difficoltà. ``priority`` è derivata da tale ordine e
# viene poi memorizzata in ogni definizione.
_CATALOG_ROWS = (
    # Inserimenti diretti.
    _entry(
        "single.last_value", "Last Value", 1.0,
        "direct_placements", "elementary", "last_value",
        aliases=_aliases("Last Digit", "Full House"),
    ),
    _entry(
        "single.hidden.box", "Hidden Single (Box)", 1.2,
        "direct_placements", "elementary", "hidden_single",
        aliases=_aliases("Hidden Single in Box"),
    ),
    _entry(
        "single.hidden.line", "Hidden Single (Row/Column)", 1.5,
        "direct_placements", "elementary", "hidden_single",
        aliases=_aliases("Hidden Single in Row/Column"),
    ),
    _entry(
        "single.naked", "Naked Single", 1.8,
        "direct_placements", "elementary", "naked_single",
        aliases=_aliases("Sole Candidate"),
    ),

    # Intersezioni box/linee.
    _entry(
        "direct.pointing", "Direct Pointing", 2.4,
        "locked_candidates", "subsets_intersections", "direct_locked",
    ),
    _entry(
        "intersection.pointing", "Pointing", 2.4,
        "locked_candidates", "subsets_intersections", "locked_candidates",
        aliases=_aliases("Locked Candidates Type 1"),
    ),
    _entry(
        "direct.claiming", "Direct Claiming", 2.5,
        "locked_candidates", "subsets_intersections", "direct_locked",
    ),
    _entry(
        "intersection.claiming", "Claiming", 2.5,
        "locked_candidates", "subsets_intersections", "locked_candidates",
        aliases=_aliases("Box-Line Reduction", "Locked Candidates Type 2"),
    ),

    # Sottoinsiemi.
    _entry(
        "subset.naked.2", "Naked Pair", 2.6,
        "subsets", "subsets_intersections", "naked_subset:2",
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "direct.hidden.2", "Direct Hidden Pair", 3.0,
        "subsets", "subsets_intersections", "direct_hidden_subset:2",
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "subset.hidden.2", "Hidden Pair", 3.0,
        "subsets", "subsets_intersections", "hidden_subset:2",
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "subset.naked.3", "Naked Triple", 3.2,
        "subsets", "subsets_intersections", "naked_subset:3",
        aliases=_aliases("Naked Triplet"),
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "direct.hidden.3", "Direct Hidden Triplet", 3.4,
        "subsets", "subsets_intersections", "direct_hidden_subset:3",
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "subset.hidden.3", "Hidden Triple", 3.4,
        "subsets", "subsets_intersections", "hidden_subset:3",
        aliases=_aliases("Hidden Triplet"),
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "subset.naked.4", "Naked Quadruple", 3.6,
        "subsets", "subsets_intersections", "naked_subset:4",
        aliases=_aliases("Naked Quad"),
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "subset.hidden.4", "Hidden Quadruple", 3.7,
        "subsets", "subsets_intersections", "hidden_subset:4",
        aliases=_aliases("Hidden Quad"),
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "subset.naked.5", "Generalized Naked Quintuple", 4.0,
        "subsets", "subsets_intersections", "naked_subset:5",
        aliases=_aliases("Naked Quintuple"),
        rating_kind="pseudo_se", proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "subset.naked.6", "Generalized Naked Sextuple", 4.2,
        "subsets", "subsets_intersections", "naked_subset:6",
        aliases=_aliases("Naked Sextuple"),
        rating_kind="pseudo_se", proof_metric_profile=SUBSET_METRICS,
    ),

    # Fish, wings e pattern a cifra singola.
    _entry(
        "fish.basic.2", "X-Wing", 3.8,
        "fish", "fish_wings", "fish",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.basic.3", "Swordfish", 4.1,
        "fish", "fish_wings", "fish",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.basic.4", "Jellyfish", 4.8,
        "fish", "fish_wings", "fish",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.finned.2", "Finned X-Wing", 4.0,
        "fish", "fish_wings", "fish",
        parent_id="fish.basic.2",
        se_equivalent_parent_id="fish.basic.2",
        rating_kind="pseudo_se", proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.sashimi.2", "Sashimi X-Wing", 4.1,
        "fish", "fish_wings", "fish",
        parent_id="fish.finned.2",
        se_equivalent_parent_id="fish.basic.2",
        rating_kind="pseudo_se", proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.finned.3", "Finned Swordfish", 4.3,
        "fish", "fish_wings", "fish",
        parent_id="fish.basic.3",
        se_equivalent_parent_id="fish.basic.3",
        rating_kind="pseudo_se", proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.sashimi.3", "Sashimi Swordfish", 4.4,
        "fish", "fish_wings", "fish",
        parent_id="fish.finned.3",
        se_equivalent_parent_id="fish.basic.3",
        rating_kind="pseudo_se", proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.finned.4", "Finned Jellyfish", 5.0,
        "fish", "fish_wings", "fish",
        parent_id="fish.basic.4",
        se_equivalent_parent_id="fish.basic.4",
        rating_kind="pseudo_se", proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.sashimi.4", "Sashimi Jellyfish", 5.1,
        "fish", "fish_wings", "fish",
        parent_id="fish.finned.4",
        se_equivalent_parent_id="fish.basic.4",
        rating_kind="pseudo_se", proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.franken.2", "Franken X-Wing", 4.5,
        "fish", "fish_wings", "fish",
        parent_id="fish.basic.2", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.franken.3", "Franken Swordfish", 4.9,
        "fish", "fish_wings", "fish",
        parent_id="fish.basic.3", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.franken.4", "Franken Jellyfish", 5.3,
        "fish", "fish_wings", "fish",
        parent_id="fish.basic.4", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.franken.finned.2", "Finned Franken X-Wing", 4.7,
        "fish", "fish_wings", "fish",
        parent_id="fish.franken.2", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.franken.sashimi.2", "Sashimi Franken X-Wing", 4.8,
        "fish", "fish_wings", "fish",
        parent_id="fish.franken.finned.2", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.franken.finned.3", "Finned Franken Swordfish", 5.1,
        "fish", "fish_wings", "fish",
        parent_id="fish.franken.3", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.franken.sashimi.3", "Sashimi Franken Swordfish", 5.2,
        "fish", "fish_wings", "fish",
        parent_id="fish.franken.finned.3", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.franken.finned.4", "Finned Franken Jellyfish", 5.5,
        "fish", "fish_wings", "fish",
        parent_id="fish.franken.4", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.franken.sashimi.4", "Sashimi Franken Jellyfish", 5.6,
        "fish", "fish_wings", "fish",
        parent_id="fish.franken.finned.4", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.2", "Mutant X-Wing", 4.8,
        "fish", "fish_wings", "fish",
        parent_id="fish.basic.2", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.3", "Mutant Swordfish", 5.2,
        "fish", "fish_wings", "fish",
        parent_id="fish.basic.3", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.4", "Mutant Jellyfish", 5.6,
        "fish", "fish_wings", "fish",
        parent_id="fish.basic.4", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.finned.2", "Finned Mutant X-Wing", 5.0,
        "fish", "fish_wings", "fish",
        parent_id="fish.mutant.2", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.sashimi.2", "Sashimi Mutant X-Wing", 5.1,
        "fish", "fish_wings", "fish",
        parent_id="fish.mutant.finned.2", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.finned.3", "Finned Mutant Swordfish", 5.4,
        "fish", "fish_wings", "fish",
        parent_id="fish.mutant.3", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.sashimi.3", "Sashimi Mutant Swordfish", 5.5,
        "fish", "fish_wings", "fish",
        parent_id="fish.mutant.finned.3", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.finned.4", "Finned Mutant Jellyfish", 5.8,
        "fish", "fish_wings", "fish",
        parent_id="fish.mutant.4", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.sashimi.4", "Sashimi Mutant Jellyfish", 5.9,
        "fish", "fish_wings", "fish",
        parent_id="fish.mutant.finned.4", rating_kind="pseudo_se",
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.siamese", "Siamese Fish", 4.2,
        "fish", "fish_wings", "fish",
        rating_kind="pseudo_se", proof_metric_profile=FISH_METRICS,
    ),
    # Famiglie e modificatori strutturali: il detector emette il sottotipo
    # dimensionato e conserva questi attributi nel FishPattern autorevole.
    _entry(
        "fish.franken.finned", "Finned Franken Fish", 4.7,
        "fish", "fish_wings", "fish",
        rating_kind="pseudo_se", abstract=True,
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.franken.sashimi", "Sashimi Franken Fish", 4.8,
        "fish", "fish_wings", "fish",
        rating_kind="pseudo_se", abstract=True,
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.finned", "Finned Mutant Fish", 5.0,
        "fish", "fish_wings", "fish",
        rating_kind="pseudo_se", abstract=True,
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.mutant.sashimi", "Sashimi Mutant Fish", 5.1,
        "fish", "fish_wings", "fish",
        rating_kind="pseudo_se", abstract=True,
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.modifier.endo", "Endo-Finned Fish", 5.0,
        "fish", "fish_wings", "fish",
        rating_kind="pseudo_se", abstract=True,
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "fish.modifier.cannibalistic", "Cannibalistic Fish", 5.0,
        "fish", "fish_wings", "fish",
        rating_kind="pseudo_se", abstract=True,
        proof_metric_profile=FISH_METRICS,
    ),
    _entry(
        "wing.xy", "Y-Wing", 4.2,
        "wings", "fish_wings", "y_wing",
        aliases=_aliases("XY-Wing"),
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "wing.xyz", "XYZ-Wing", 4.4,
        "wings", "fish_wings", "xyz_wing",
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "wing.w", "W-Wing", 4.5,
        "wings", "fish_wings", "w_wing",
        aliases=_aliases("Woods' Wing"),
        parent_id="se.forcing_chain",
        se_equivalent_parent_id="se.forcing_chain",
        rating_kind="pseudo_se",
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "sdp.skyscraper", "Skyscraper", 3.9,
        "single_digit_patterns", "single_digit_patterns", "skyscraper",
        parent_id="se.forcing_x_chain",
        se_equivalent_parent_id="se.forcing_x_chain",
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "sdp.two_string_kite", "Two-String Kite", 4.0,
        "single_digit_patterns", "single_digit_patterns", "two_string_kite",
        aliases=_aliases("2-String Kite"),
        parent_id="se.forcing_x_chain",
        se_equivalent_parent_id="se.forcing_x_chain",
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "sdp.turbot_fish", "Turbot Fish", 4.2,
        "single_digit_patterns", "single_digit_patterns", "forcing_x_chain",
        aliases=_aliases("Turbot Crane"),
        parent_id="se.forcing_x_chain",
        se_equivalent_parent_id="se.forcing_x_chain",
        engine_type="logic",
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "sdp.empty_rectangle", "Empty Rectangle", 4.3,
        "single_digit_patterns", "single_digit_patterns", "empty_rectangle",
        aliases=_aliases("ER"),
        parent_id="se.forcing_x_chain",
        se_equivalent_parent_id="se.forcing_x_chain",
        rating_kind="pseudo_se",
        proof_metric_profile=CHAIN_METRICS,
    ),

    # Coloring: classificazioni esplicite del grafo X a cifra singola.
    _entry(
        "color.simple.trap", "Simple Colors: Color Trap", 4.0,
        "coloring", "static_chains", "coloring",
        aliases=_aliases("Color Trap", "Simple Coloring Trap"),
        parent_id="se.forcing_x_chain",
        se_equivalent_parent_id="se.forcing_x_chain",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=COLORING_METRICS,
    ),
    _entry(
        "color.simple.wrap", "Simple Colors: Color Wrap", 4.1,
        "coloring", "static_chains", "coloring",
        aliases=_aliases("Color Wrap", "Simple Coloring Wrap"),
        parent_id="se.forcing_x_chain",
        se_equivalent_parent_id="se.forcing_x_chain",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=COLORING_METRICS,
    ),
    _entry(
        "color.multi.type1", "Multi Colors Type 1", 4.4,
        "coloring", "static_chains", "coloring",
        aliases=_aliases("Multi Coloring Type 1"),
        parent_id="se.forcing_x_chain",
        se_equivalent_parent_id="se.forcing_x_chain",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=COLORING_METRICS,
    ),
    _entry(
        "color.multi.type2", "Multi Colors Type 2", 4.5,
        "coloring", "static_chains", "coloring",
        aliases=_aliases("Multi Coloring Type 2"),
        parent_id="se.forcing_x_chain",
        se_equivalent_parent_id="se.forcing_x_chain",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=COLORING_METRICS,
    ),

    # Unicità ed exclusion.
    _entry(
        "unique.ur.1", "Unique Rectangle Type 1", 4.3,
        "uniqueness", "uniqueness_exclusion", "ur_type_1",
        aliases=_aliases("UR1"), rating_kind="pseudo_se",
        requires_unique_solution=True,
    ),
    _entry(
        "unique.avoidable.1", "Avoidable Rectangle Type 1", 4.4,
        "uniqueness", "uniqueness_exclusion", "avoidable_rectangle:1",
        aliases=_aliases("AR1"), rating_kind="pseudo_se",
        requires_unique_solution=True,
    ),
    _entry(
        "unique.ur.2", "Unique Rectangle Type 2", 4.5,
        "uniqueness", "uniqueness_exclusion", "ur_type_2",
        aliases=_aliases("UR2"), rating_kind="pseudo_se",
        requires_unique_solution=True,
    ),
    _entry(
        "unique.avoidable.2", "Avoidable Rectangle Type 2", 4.6,
        "uniqueness", "uniqueness_exclusion", "avoidable_rectangle:2",
        aliases=_aliases("AR2"), rating_kind="pseudo_se",
        requires_unique_solution=True,
    ),
    _entry(
        "unique.ur.4", "Unique Rectangle Type 4", 4.6,
        "uniqueness", "uniqueness_exclusion", "ur_type_4",
        aliases=_aliases("UR4"), rating_kind="pseudo_se",
        requires_unique_solution=True,
    ),
    _entry(
        "unique.bug.1", "BUG+1", 4.6,
        "uniqueness", "uniqueness_exclusion", "bug_plus_one",
        aliases=_aliases("BUG Type 1"), requires_unique_solution=True,
    ),
    _entry(
        "unique.ur.5", "Unique Rectangle Type 5", 4.7,
        "uniqueness", "uniqueness_exclusion", "ur_type_5",
        aliases=_aliases("UR5"), rating_kind="pseudo_se",
        requires_unique_solution=True,
    ),
    _entry(
        "unique.ur.6", "Unique Rectangle Type 6", 4.8,
        "uniqueness", "uniqueness_exclusion", "ur_type_6",
        aliases=_aliases("UR6"), rating_kind="pseudo_se",
        requires_unique_solution=True,
    ),
    _entry(
        "unique.hidden_rectangle", "Hidden Rectangle", 4.9,
        "uniqueness", "uniqueness_exclusion", "hidden_rectangle",
        aliases=_aliases("HR"), rating_kind="pseudo_se",
        requires_unique_solution=True,
    ),
    _entry(
        "unique.ur.3", "Unique Rectangle Type 3", 4.9,
        "uniqueness", "uniqueness_exclusion", "ur_type_3",
        aliases=_aliases("UR3"), rating_kind="pseudo_se",
        requires_unique_solution=True,
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "unique.loop.1", "Unique Loop Type 1", 5.0,
        "uniqueness", "uniqueness_exclusion", "unique_loop",
        aliases=_aliases("UL1"), rating_kind="pseudo_se",
        requires_unique_solution=True,
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "unique.bug.2", "BUG Type 2", 5.0,
        "uniqueness", "uniqueness_exclusion", "bug_types",
        rating_kind="pseudo_se", requires_unique_solution=True,
    ),
    _entry(
        "unique.bug.4", "BUG Type 4", 5.1,
        "uniqueness", "uniqueness_exclusion", "bug_types",
        rating_kind="pseudo_se", requires_unique_solution=True,
    ),
    _entry(
        "unique.loop.2", "Unique Loop Type 2", 5.1,
        "uniqueness", "uniqueness_exclusion", "unique_loop",
        aliases=_aliases("UL2"), rating_kind="pseudo_se",
        requires_unique_solution=True,
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "unique.loop.4", "Unique Loop Type 4", 5.2,
        "uniqueness", "uniqueness_exclusion", "unique_loop",
        aliases=_aliases("UL4"), rating_kind="pseudo_se",
        requires_unique_solution=True,
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "unique.bug.3.2", "BUG Type 3 (Pair)", 5.2,
        "uniqueness", "uniqueness_exclusion", "bug_types",
        aliases=_aliases("BUG Type 3 Pair"), rating_kind="pseudo_se",
        requires_unique_solution=True, proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "unique.bug.3.3", "BUG Type 3 (Triplet)", 5.4,
        "uniqueness", "uniqueness_exclusion", "bug_types",
        aliases=_aliases("BUG Type 3 Triplet"), rating_kind="pseudo_se",
        requires_unique_solution=True, proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "unique.loop.3", "Unique Loop Type 3", 5.4,
        "uniqueness", "uniqueness_exclusion", "unique_loop",
        aliases=_aliases("UL3"), rating_kind="pseudo_se",
        requires_unique_solution=True,
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "unique.bug.3.4", "BUG Type 3 (Quad)", 5.6,
        "uniqueness", "uniqueness_exclusion", "bug_types",
        aliases=_aliases("BUG Type 3 Quad"), rating_kind="pseudo_se",
        requires_unique_solution=True, proof_metric_profile=SUBSET_METRICS,
    ),

    # Catene e cicli statici.
    _entry(
        "chain.remote_pair", "Remote Pair", 4.7,
        "bivalue_chains", "static_chains", "xy_chain",
        parent_id="se.bidirectional_y_cycle",
        se_equivalent_parent_id="se.bidirectional_y_cycle",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "chain.xy", "XY-Chain", 5.5,
        "bivalue_chains", "static_chains", "xy_chain",
        aliases=_aliases("Y-Chain"),
        parent_id="se.bidirectional_y_cycle",
        se_equivalent_parent_id="se.bidirectional_y_cycle",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "se.bidirectional_x_cycle", "Bidirectional X-Cycle", 5.4,
        "bidirectional_cycles", "static_chains", "bidirectional_x_cycle",
        aliases=_aliases("X-Cycle", "Fishy Cycle", "Bilocation Cycle"),
        engine_type="logic", proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "se.bidirectional_y_cycle", "Bidirectional Y-Cycle", 5.6,
        "bidirectional_cycles", "static_chains", "bidirectional_y_cycle",
        aliases=_aliases("Y-Cycle", "Bivalue Cycle"),
        engine_type="logic", proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "loop.xy", "XY-Cycle", 5.8,
        "bidirectional_cycles", "static_chains", "bidirectional_y_cycle",
        parent_id="se.bidirectional_y_cycle",
        se_equivalent_parent_id="se.bidirectional_y_cycle",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "loop.cnl", "Continuous Nice Loop", 6.1,
        "bidirectional_cycles", "static_chains", "bidirectional_cycle",
        aliases=_aliases("AIC Loop"),
        parent_id="se.bidirectional_cycle",
        se_equivalent_parent_id="se.bidirectional_cycle",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "se.bidirectional_cycle", "Bidirectional Cycle", 6.1,
        "bidirectional_cycles", "static_chains", "bidirectional_cycle",
        aliases=_aliases("Nice Loop"),
        engine_type="logic", proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "se.forcing_x_chain", "Forcing X-Chain", 5.7,
        "forcing_chains", "static_chains", "forcing_x_chain",
        aliases=_aliases("Discontinuous X-Cycle"),
        engine_type="logic", proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "chain.aic", "Alternating Inference Chain", 6.0,
        "forcing_chains", "static_chains", "forcing_chain",
        parent_id="se.forcing_chain",
        se_equivalent_parent_id="se.forcing_chain",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "intersection.sue_de_coq", "Sue de Coq", 5.0,
        "exclusion", "uniqueness_exclusion", "sue_de_coq",
        aliases=_aliases("SdC"), rating_kind="pseudo_se",
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "intersection.sue_de_coq.extended", "Extended Sue de Coq", 5.2,
        "exclusion", "uniqueness_exclusion", "sue_de_coq",
        aliases=_aliases("Extended SdC"), rating_kind="pseudo_se",
        proof_metric_profile=SUBSET_METRICS,
    ),
    _entry(
        "se.forcing_chain", "Forcing Chain", 6.7,
        "forcing_chains", "static_chains", "forcing_chain",
        aliases=_aliases("Forward Implication Chain"),
        engine_type="logic", proof_metric_profile=CHAIN_METRICS,
    ),
    _entry(
        "exclusion.aligned_pair", "Aligned Pair Exclusion", 6.2,
        "exclusion", "uniqueness_exclusion", "aligned_pair_exclusion",
        aliases=_aliases("APE"), proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "exclusion.aligned_triplet", "Aligned Triplet Exclusion", 7.5,
        "exclusion", "uniqueness_exclusion", "aligned_triplet_exclusion",
        aliases=_aliases("ATE"), rating_kind="pseudo_se",
        proof_metric_profile=FORCING_METRICS,
    ),

    # Forcing ordinary.
    _entry(
        "forcing.nishio", "Nishio", 7.1,
        "assumption_logic", "assumption_logic", "nishio",
        engine_type="logic", proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.cell", "Cell Forcing Chain", 7.6,
        "multiple_forcing", "multiple_forcing", "cell_forcing_chain",
        aliases=_aliases("Multiple Cell Forcing Chain"),
        engine_type="logic", proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.region", "Region Forcing Chain", 7.8,
        "multiple_forcing", "multiple_forcing", "region_forcing_chain",
        aliases=_aliases("Unit Forcing Chain"),
        engine_type="logic", proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.dynamic.contradiction",
        "Dynamic Contradiction Forcing Chain", 8.5,
        "dynamic_forcing", "dynamic_forcing", "dynamic_forcing_chain",
        parent_id="forcing.dynamic",
        se_equivalent_parent_id="forcing.dynamic",
        engine_type="logic", proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.dynamic.double", "Dynamic Double Forcing Chain", 8.5,
        "dynamic_forcing", "dynamic_forcing", "dynamic_forcing_chain",
        parent_id="forcing.dynamic",
        se_equivalent_parent_id="forcing.dynamic",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.dynamic.cell", "Dynamic Cell Forcing Chain", 8.5,
        "dynamic_forcing", "dynamic_forcing", "dynamic_forcing_chain",
        parent_id="forcing.dynamic",
        se_equivalent_parent_id="forcing.dynamic",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.dynamic.region", "Dynamic Region Forcing Chain", 8.5,
        "dynamic_forcing", "dynamic_forcing", "dynamic_forcing_chain",
        parent_id="forcing.dynamic",
        se_equivalent_parent_id="forcing.dynamic",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.dynamic", "Dynamic Forcing Chain", 8.5,
        "dynamic_forcing", "dynamic_forcing", "dynamic_forcing_chain",
        engine_type="logic", abstract=True,
        proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.plus.contradiction",
        "Dynamic Contradiction Forcing Chain Plus", 9.0,
        "dynamic_forcing", "dynamic_forcing", "dynamic_forcing_chain_plus",
        parent_id="forcing.plus",
        se_equivalent_parent_id="forcing.plus",
        engine_type="logic", proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.plus.double", "Dynamic Double Forcing Chain Plus", 9.0,
        "dynamic_forcing", "dynamic_forcing", "dynamic_forcing_chain_plus",
        parent_id="forcing.plus",
        se_equivalent_parent_id="forcing.plus",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.plus.cell", "Dynamic Cell Forcing Chain Plus", 9.0,
        "dynamic_forcing", "dynamic_forcing", "dynamic_forcing_chain_plus",
        parent_id="forcing.plus",
        se_equivalent_parent_id="forcing.plus",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.plus.region", "Dynamic Region Forcing Chain Plus", 9.0,
        "dynamic_forcing", "dynamic_forcing", "dynamic_forcing_chain_plus",
        parent_id="forcing.plus",
        se_equivalent_parent_id="forcing.plus",
        rating_kind="pseudo_se", engine_type="logic",
        proof_metric_profile=FORCING_METRICS,
    ),
    _entry(
        "forcing.plus", "Dynamic Forcing Chain Plus", 9.0,
        "dynamic_forcing", "dynamic_forcing", "dynamic_forcing_chain_plus",
        engine_type="logic", abstract=True,
        proof_metric_profile=FORCING_METRICS,
    ),

    # Le vere Nested restano un livello distinto dalla ricerca esaustiva.
    _entry(
        "nested.contradiction", "Nested Contradiction Forcing Chain", 9.5,
        "nested_forcing", "nested_forcing", "nested_forcing_chain",
        parent_id="nested.forcing_chain",
        se_equivalent_parent_id="nested.forcing_chain",
        rating_kind="pseudo_se", engine_type="nested", fallback_tier=1,
        proof_metric_profile=NESTED_METRICS,
    ),
    _entry(
        "nested.double", "Nested Double Forcing Chain", 9.5,
        "nested_forcing", "nested_forcing", "nested_forcing_chain",
        parent_id="nested.forcing_chain",
        se_equivalent_parent_id="nested.forcing_chain",
        rating_kind="pseudo_se", engine_type="nested", fallback_tier=1,
        proof_metric_profile=NESTED_METRICS,
    ),
    _entry(
        "nested.cell", "Nested Cell Forcing Chain", 9.5,
        "nested_forcing", "nested_forcing", "nested_forcing_chain",
        parent_id="nested.forcing_chain",
        se_equivalent_parent_id="nested.forcing_chain",
        rating_kind="pseudo_se", engine_type="nested", fallback_tier=1,
        proof_metric_profile=NESTED_METRICS,
    ),
    _entry(
        "nested.region", "Nested Region Forcing Chain", 9.5,
        "nested_forcing", "nested_forcing", "nested_forcing_chain",
        parent_id="nested.forcing_chain",
        se_equivalent_parent_id="nested.forcing_chain",
        rating_kind="pseudo_se", engine_type="nested", fallback_tier=1,
        proof_metric_profile=NESTED_METRICS,
    ),
    _entry(
        "nested.forcing_chain", "Nested Forcing Chain", 9.5,
        "nested_forcing", "nested_forcing", "nested_forcing_chain",
        engine_type="nested", fallback_tier=1, abstract=True,
        proof_metric_profile=NESTED_METRICS,
    ),
    _entry(
        "forcing.complete_tree", "Complete Forcing Tree", 13.0,
        "exhaustive_forcing", "last_resort", "complete_forcing_tree",
        rating_kind="project", engine_type="complete_tree",
        fallback_tier=2, proof_metric_profile=FORCING_METRICS,
    ),
)


TECHNIQUE_DEFINITIONS = tuple(
    TechniqueDefinition(priority=index * 10, **row)
    for index, row in enumerate(_CATALOG_ROWS, start=1)
)


def _normalise_name(value):
    return " ".join(str(value).strip().casefold().split())


def validate_catalog(definitions=TECHNIQUE_DEFINITIONS):
    """Valida identificatori, parent, metadata e collisioni degli alias."""
    definitions = tuple(definitions)
    by_id = {}
    canonical_names = {}
    aliases_by_namespace = {}
    family_strategies = {}

    for definition in definitions:
        if not isinstance(definition, TechniqueDefinition):
            raise CatalogValidationError(
                "Ogni voce deve essere una TechniqueDefinition."
            )
        if not definition.id or definition.id.strip() != definition.id:
            raise CatalogValidationError("ID tecnica vuoto o non normalizzato.")
        if definition.id in by_id:
            raise CatalogValidationError(
                f"ID tecnica duplicato: {definition.id!r}."
            )
        by_id[definition.id] = definition

        canonical_key = _normalise_name(definition.canonical_name)
        if (
            not canonical_key
            or definition.canonical_name.strip() != definition.canonical_name
        ):
            raise CatalogValidationError(
                f"Nome canonico vuoto o non normalizzato per "
                f"{definition.id!r}."
            )
        if canonical_key in canonical_names:
            raise CatalogValidationError(
                "Nome canonico duplicato: "
                f"{definition.canonical_name!r}."
            )
        canonical_names[canonical_key] = definition.id

        if (
            not definition.display_name_it
            or definition.display_name_it.strip()
            != definition.display_name_it
        ):
            raise CatalogValidationError(
                f"Nome italiano vuoto o non normalizzato per "
                f"{definition.id!r}."
            )

        if definition.family_id not in FAMILY_DISPLAY_NAMES_IT:
            raise CatalogValidationError(
                f"Famiglia sconosciuta per {definition.id!r}: "
                f"{definition.family_id!r}."
            )
        if definition.strategy_id not in STRATEGY_DISPLAY_NAMES_IT:
            raise CatalogValidationError(
                f"Strategia sconosciuta per {definition.id!r}: "
                f"{definition.strategy_id!r}."
            )
        previous_strategy = family_strategies.setdefault(
            definition.family_id,
            definition.strategy_id,
        )
        if previous_strategy != definition.strategy_id:
            raise CatalogValidationError(
                f"La famiglia {definition.family_id!r} usa strategie "
                "incompatibili."
            )
        if definition.rating_kind not in RATING_KINDS:
            raise CatalogValidationError(
                f"Tipo di rating non valido per {definition.id!r}."
            )
        if definition.engine_type not in ENGINE_TYPES:
            raise CatalogValidationError(
                f"Engine non valido per {definition.id!r}."
            )
        if definition.fallback_tier not in (0, 1, 2):
            raise CatalogValidationError(
                f"Fallback tier non valido per {definition.id!r}."
            )
        if definition.implementation_status not in IMPLEMENTATION_STATUSES:
            raise CatalogValidationError(
                f"Stato di implementazione non valido per {definition.id!r}."
            )
        if (
            definition.implementation_status == "implemented"
            and (
                not definition.detector_id
                or definition.detector_id.strip() != definition.detector_id
            )
        ):
            raise CatalogValidationError(
                f"Tecnica implementata senza detector: {definition.id!r}."
            )
        if not math.isfinite(definition.base_difficulty):
            raise CatalogValidationError(
                f"Difficoltà non finita per {definition.id!r}."
            )
        if definition.base_difficulty < 0:
            raise CatalogValidationError(
                f"Difficoltà negativa per {definition.id!r}."
            )
        if (
            isinstance(definition.priority, bool)
            or not isinstance(definition.priority, int)
            or definition.priority < 0
        ):
            raise CatalogValidationError(
                f"Priorità non valida per {definition.id!r}."
            )
        if len(set(definition.proof_metric_profile)) != len(
            definition.proof_metric_profile
        ):
            raise CatalogValidationError(
                f"Metriche duplicate per {definition.id!r}."
            )
        if any(
            not metric or metric.strip() != metric
            for metric in definition.proof_metric_profile
        ):
            raise CatalogValidationError(
                f"Metriche vuote o non normalizzate per {definition.id!r}."
            )

        for alias in definition.aliases:
            if not isinstance(alias, TechniqueAlias):
                raise CatalogValidationError(
                    f"Alias non valido per {definition.id!r}."
                )
            alias_key = _normalise_name(alias.name)
            namespace = str(alias.namespace).strip().casefold()
            if not alias_key or not namespace:
                raise CatalogValidationError(
                    f"Alias vuoto per {definition.id!r}."
                )
            key = namespace, alias_key
            previous = aliases_by_namespace.get(key)
            if previous is not None:
                raise CatalogValidationError(
                    "Alias duplicato nello stesso namespace: "
                    f"{alias.name!r} ({namespace!r}) per "
                    f"{previous!r} e {definition.id!r}."
                )
            aliases_by_namespace[key] = definition.id

    for definition in definitions:
        for field_name, target_id in (
            ("parent_id", definition.parent_id),
            ("se_equivalent_parent_id", definition.se_equivalent_parent_id),
        ):
            if target_id is not None and target_id not in by_id:
                raise CatalogValidationError(
                    f"{field_name} inesistente per {definition.id!r}: "
                    f"{target_id!r}."
                )

    visiting = set()
    visited = set()

    def visit(technique_id):
        if technique_id in visiting:
            raise CatalogValidationError(
                f"Ciclo nel grafo dei parent in {technique_id!r}."
            )
        if technique_id in visited:
            return
        visiting.add(technique_id)
        parent_id = by_id[technique_id].parent_id
        if parent_id is not None:
            visit(parent_id)
        visiting.remove(technique_id)
        visited.add(technique_id)

    for technique_id in by_id:
        visit(technique_id)

    return definitions


validate_catalog()

TECHNIQUE_BY_ID = {
    definition.id: definition
    for definition in TECHNIQUE_DEFINITIONS
}
TECHNIQUE_CATALOG = TECHNIQUE_BY_ID
TECHNIQUE_BY_CANONICAL_NAME = {
    definition.canonical_name: definition
    for definition in TECHNIQUE_DEFINITIONS
}
_TECHNIQUE_BY_NORMALISED_CANONICAL_NAME = {
    _normalise_name(definition.canonical_name): definition
    for definition in TECHNIQUE_DEFINITIONS
}
_ALIASES_BY_NAME = defaultdict(list)
_ALIASES_BY_NAMESPACE_AND_NAME = {}
for _definition in TECHNIQUE_DEFINITIONS:
    for _alias in _definition.aliases:
        _alias_name = _normalise_name(_alias.name)
        _alias_namespace = _alias.namespace.strip().casefold()
        _ALIASES_BY_NAME[_alias_name].append(_definition)
        _ALIASES_BY_NAMESPACE_AND_NAME[
            (_alias_namespace, _alias_name)
        ] = _definition
_ALIASES_BY_NAME = {
    name: tuple(definitions)
    for name, definitions in _ALIASES_BY_NAME.items()
}
TECHNIQUE_IDS_BY_DETECTOR = {
    detector_id: tuple(
        definition.id
        for definition in TECHNIQUE_DEFINITIONS
        if definition.detector_id == detector_id
    )
    for detector_id in dict.fromkeys(
        definition.detector_id
        for definition in TECHNIQUE_DEFINITIONS
        if definition.detector_id is not None
    )
}


def technique_definition(technique_id):
    """Restituisce una definizione a partire dal suo ID stabile."""
    try:
        return TECHNIQUE_BY_ID[str(technique_id)]
    except KeyError as error:
        raise KeyError(f"ID tecnica sconosciuto: {technique_id!r}.") from error


def resolve_technique(name, *, namespace=None):
    """Risolve un nome canonico o un alias in una definizione.

    I nomi canonici hanno sempre precedenza. Se lo stesso alias è ammesso in
    namespace differenti, il chiamante deve specificare ``namespace``.
    """
    normalised_name = _normalise_name(name)
    definition = _TECHNIQUE_BY_NORMALISED_CANONICAL_NAME.get(normalised_name)
    if definition is not None:
        return definition

    if namespace is not None:
        key = str(namespace).strip().casefold(), normalised_name
        try:
            return _ALIASES_BY_NAMESPACE_AND_NAME[key]
        except KeyError as error:
            raise KeyError(
                f"Alias tecnica sconosciuto: {name!r} ({namespace!r})."
            ) from error

    definitions = _ALIASES_BY_NAME.get(normalised_name, ())
    if not definitions:
        raise KeyError(f"Tecnica o alias sconosciuto: {name!r}.")
    unique_ids = {definition.id for definition in definitions}
    if len(unique_ids) != 1:
        raise CatalogValidationError(
            f"Alias ambiguo {name!r}; specificare il namespace."
        )
    return definitions[0]


def resolve_legacy_technique(name):
    """Risolve esclusivamente i nomi prodotti dagli archivi pre-P04."""
    try:
        canonical_name = LEGACY_TECHNIQUE_ALIASES[str(name)]
    except KeyError as error:
        raise KeyError(
            f"Alias tecnica legacy sconosciuto: {name!r}."
        ) from error
    return resolve_technique(canonical_name)


def validate_detector_registry(
    detector_technique_ids,
    definitions=TECHNIQUE_DEFINITIONS,
):
    """Confronta il catalogo con un registro ``detector -> technique_ids``."""
    definitions = validate_catalog(definitions)
    by_id = {definition.id: definition for definition in definitions}
    expected = defaultdict(set)
    for definition in definitions:
        if definition.implementation_status == "implemented":
            expected[definition.detector_id].add(definition.id)

    declared = {}
    for detector_id, technique_ids in detector_technique_ids.items():
        detector_id = str(detector_id).strip()
        technique_ids = tuple(technique_ids)
        if not detector_id:
            raise CatalogValidationError("Detector ID vuoto nel registro.")
        if not technique_ids:
            raise CatalogValidationError(
                f"Il detector {detector_id!r} non dichiara tecniche."
            )
        if detector_id in declared:
            raise CatalogValidationError(
                f"Detector duplicato nel registro: {detector_id!r}."
            )
        declared[detector_id] = set(technique_ids)

        unknown = declared[detector_id] - set(by_id)
        if unknown:
            raise CatalogValidationError(
                f"Il detector {detector_id!r} dichiara ID sconosciuti: "
                f"{', '.join(sorted(unknown))}."
            )
        misplaced = {
            technique_id
            for technique_id in declared[detector_id]
            if by_id[technique_id].detector_id != detector_id
        }
        if misplaced:
            raise CatalogValidationError(
                f"Il detector {detector_id!r} dichiara tecniche assegnate "
                f"altrove: {', '.join(sorted(misplaced))}."
            )

    missing_detectors = set(expected) - set(declared)
    if missing_detectors:
        raise CatalogValidationError(
            "Detector implementati non registrati: "
            f"{', '.join(sorted(missing_detectors))}."
        )

    for detector_id, expected_ids in expected.items():
        missing_ids = expected_ids - declared[detector_id]
        if missing_ids:
            raise CatalogValidationError(
                f"Il detector {detector_id!r} non dichiara: "
                f"{', '.join(sorted(missing_ids))}."
            )

    return True


# -------------------------------------------------------------------------
# Export di compatibilità. Tutti sono derivati dalle definizioni precedenti.
# -------------------------------------------------------------------------

TECHNIQUE_DIFFICULTY = {
    definition.canonical_name: definition.base_difficulty
    for definition in TECHNIQUE_DEFINITIONS
}
TECHNIQUE_FAMILY = {
    definition.canonical_name: FAMILY_DISPLAY_NAMES_IT[definition.family_id]
    for definition in TECHNIQUE_DEFINITIONS
}
TECHNIQUE_STRATEGY = {
    definition.canonical_name: STRATEGY_DISPLAY_NAMES_IT[
        definition.strategy_id
    ]
    for definition in TECHNIQUE_DEFINITIONS
}
FAMILY_TO_STRATEGY = {
    FAMILY_DISPLAY_NAMES_IT[definition.family_id]: (
        STRATEGY_DISPLAY_NAMES_IT[definition.strategy_id]
    )
    for definition in TECHNIQUE_DEFINITIONS
}
MODERN_TECHNIQUE_PARENT = {
    definition.canonical_name: TECHNIQUE_BY_ID[
        definition.se_equivalent_parent_id
    ].canonical_name
    for definition in TECHNIQUE_DEFINITIONS
    if definition.se_equivalent_parent_id is not None
}
TECHNIQUE_ORDER = tuple(
    definition.canonical_name
    for definition in sorted(
        TECHNIQUE_DEFINITIONS,
        key=lambda item: (item.base_difficulty, item.priority),
    )
)
TECHNIQUE_FAMILY_ORDER = tuple(dict.fromkeys(
    TECHNIQUE_FAMILY[name]
    for name in TECHNIQUE_ORDER
))
TECHNIQUE_STRATEGY_ORDER = tuple(dict.fromkeys(
    TECHNIQUE_STRATEGY[name]
    for name in TECHNIQUE_ORDER
))


__all__ = [
    "CatalogValidationError",
    "ENGINE_TYPES",
    "FAMILY_TO_STRATEGY",
    "FAMILY_DISPLAY_NAMES_IT",
    "IMPLEMENTATION_STATUSES",
    "LEGACY_TECHNIQUE_ALIASES",
    "MODERN_TECHNIQUE_PARENT",
    "RATING_KINDS",
    "STRATEGY_DISPLAY_NAMES_IT",
    "TECHNIQUE_BY_CANONICAL_NAME",
    "TECHNIQUE_BY_ID",
    "TECHNIQUE_CATALOG",
    "TECHNIQUE_CATALOG_VERSION",
    "TECHNIQUE_DEFINITIONS",
    "TECHNIQUE_DIFFICULTY",
    "TECHNIQUE_FAMILY",
    "TECHNIQUE_FAMILY_ORDER",
    "TECHNIQUE_IDS_BY_DETECTOR",
    "TECHNIQUE_ORDER",
    "TECHNIQUE_STRATEGY",
    "TECHNIQUE_STRATEGY_ORDER",
    "TechniqueAlias",
    "TechniqueDefinition",
    "resolve_technique",
    "resolve_legacy_technique",
    "technique_definition",
    "validate_catalog",
    "validate_detector_registry",
]
