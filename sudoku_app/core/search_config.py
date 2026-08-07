"""Configurazione autorevole della ricerca P17.

``InferenceProfile`` descrive le regole ammesse dentro una prova.
``SearchLimits`` descrive i budget computazionali dei detector. Le due
dimensioni restano indipendenti dalla ``SearchPolicy`` scelta dal solver.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from types import MappingProxyType


@dataclass(frozen=True, slots=True)
class InferenceProfile:
    id: str
    allow_static_links: bool = True
    allow_dynamic_singles: bool = False
    allow_locked_candidates: bool = False
    allow_subsets: bool = False
    allow_basic_fish: bool = False
    allow_coloring: bool = False
    allow_group_nodes: bool = False
    allow_als: bool = False
    allow_nested_subproofs: bool = False
    max_nested_depth: int = 0

    def __post_init__(self):
        if not self.id or self.id != self.id.strip().casefold():
            raise ValueError("L'id del profilo deve essere minuscolo e stabile.")
        if self.max_nested_depth < 0:
            raise ValueError("max_nested_depth non puo' essere negativo.")
        if self.max_nested_depth and not self.allow_nested_subproofs:
            raise ValueError(
                "Una profondita' Nested richiede allow_nested_subproofs."
            )
        if self.allow_nested_subproofs and self.max_nested_depth < 1:
            raise ValueError(
                "Un profilo Nested richiede max_nested_depth positivo."
            )

    @property
    def advanced_rule_ids(self):
        rules = []
        if self.allow_locked_candidates:
            rules.append("locked-candidates")
        if self.allow_subsets:
            rules.append("subsets")
        if self.allow_basic_fish:
            rules.append("basic-fish")
        if self.allow_coloring:
            rules.append("coloring")
        if self.allow_group_nodes:
            rules.append("group-nodes")
        if self.allow_als:
            rules.append("als")
        if self.allow_nested_subproofs:
            rules.append("nested-subproofs")
        return tuple(rules)

    def to_dict(self):
        return asdict(self)


STATIC_PROFILE = InferenceProfile(id="static")
DYNAMIC_PROFILE = InferenceProfile(
    id="dynamic",
    allow_dynamic_singles=True,
)
DYNAMIC_PLUS_PROFILE = InferenceProfile(
    id="dynamic_plus",
    allow_dynamic_singles=True,
    allow_locked_candidates=True,
    allow_subsets=True,
    allow_basic_fish=True,
)
NESTED_LEVEL_1_PROFILE = InferenceProfile(
    id="nested_level_1",
    allow_dynamic_singles=True,
    allow_nested_subproofs=True,
    max_nested_depth=1,
)
NESTED_LEVEL_2_PROFILE = InferenceProfile(
    id="nested_level_2",
    allow_dynamic_singles=True,
    allow_nested_subproofs=True,
    max_nested_depth=2,
)
COMPLETE_TREE_PROFILE = InferenceProfile(
    id="complete_tree",
    allow_dynamic_singles=True,
)

INFERENCE_PROFILES = MappingProxyType({
    profile.id: profile
    for profile in (
        STATIC_PROFILE,
        DYNAMIC_PROFILE,
        DYNAMIC_PLUS_PROFILE,
        NESTED_LEVEL_1_PROFILE,
        NESTED_LEVEL_2_PROFILE,
        COMPLETE_TREE_PROFILE,
    )
})


_TECHNIQUE_PROFILE_IDS = {
    "Dynamic Forcing Chain": "dynamic",
    "Dynamic Forcing Chain Plus": "dynamic_plus",
    "Forcing Net": "dynamic_plus",
    "Bowman's Bingo": "dynamic_plus",
    "Nested Forcing Chain": "nested_level_2",
    "Complete Forcing Tree": "complete_tree",
}


def inference_profile(profile):
    if isinstance(profile, InferenceProfile):
        return profile
    try:
        return INFERENCE_PROFILES[str(profile).strip().casefold()]
    except KeyError as error:
        raise ValueError(f"InferenceProfile sconosciuto: {profile!r}.") from error


def profile_for_technique(technique):
    return INFERENCE_PROFILES[
        _TECHNIQUE_PROFILE_IDS.get(str(technique), "static")
    ]


@dataclass(frozen=True, slots=True)
class SearchLimits:
    mode: str
    presentation_results: int = 16
    logic_presentation_results: int = 8
    nested_presentation_results: int = 2
    complete_tree_presentation_results: int = 1
    logic_results: int | None = 16
    static_cycle_edges: int | None = 16
    fish_fins: int | None = 3
    fish_endo_fins: int | None = 2
    fish_results: int | None = 512
    als_chain_alses: int | None = 8
    als_chain_states: int | None = 32_768
    als_results: int | None = 512
    als_aic_alses: int | None = 64
    als_aic_attempts: int | None = 256
    als_aic_path_states: int | None = 2_048
    als_aic_path_edges: int | None = 12
    als_death_blossom_states: int | None = 32_768
    kraken_results: int | None = 16
    kraken_patterns: int | None = 64
    kraken_path_attempts: int | None = 512
    kraken_path_edges: int | None = 12
    kraken_fish_fins: int | None = 3
    kraken_fish_endo_fins: int | None = 1
    kraken_fish_results: int | None = 8
    template_results: int | None = 16
    templates_per_digit: int | None = 100_000
    aligned_max_degree: int | None = 6
    aligned_base_combinations: int | None = 4_096
    aligned_assignments: int | None = 65_536
    aligned_results: int | None = 128
    exocet_patterns: int | None = 2_048
    exocet_results: int | None = 64
    bowmans_attempts: int | None = 729
    bowmans_results: int | None = 8
    nested_depth: int | None = 2
    nested_proof_nodes: int | None = 512
    nested_branches: int | None = 64
    nested_subproofs: int | None = 32
    nested_results: int | None = 2
    nested_attempts: int | None = 512
    nested_predecessor_edges: int | None = 4

    def __post_init__(self):
        if self.mode not in {"limited", "unlimited"}:
            raise ValueError("SearchLimits.mode deve essere limited o unlimited.")
        for name, value in asdict(self).items():
            if name == "mode" or value is None:
                continue
            if isinstance(value, bool) or int(value) < 1:
                raise ValueError(f"{name} deve essere positivo o None.")

    @property
    def unlimited(self):
        return self.mode == "unlimited"

    def to_dict(self):
        return asdict(self)

    @property
    def signature(self):
        return tuple(asdict(self).items())


LIMITED_SEARCH_LIMITS = SearchLimits(mode="limited")
UNLIMITED_SEARCH_LIMITS = SearchLimits(
    mode="unlimited",
    logic_results=None,
    static_cycle_edges=None,
    fish_fins=None,
    fish_endo_fins=None,
    fish_results=None,
    als_chain_alses=None,
    als_chain_states=None,
    als_results=None,
    als_aic_alses=None,
    als_aic_attempts=None,
    als_aic_path_states=None,
    als_aic_path_edges=None,
    als_death_blossom_states=None,
    kraken_results=None,
    kraken_patterns=None,
    kraken_path_attempts=None,
    kraken_path_edges=None,
    kraken_fish_fins=None,
    kraken_fish_endo_fins=None,
    kraken_fish_results=None,
    template_results=None,
    templates_per_digit=None,
    aligned_max_degree=None,
    aligned_base_combinations=None,
    aligned_assignments=None,
    aligned_results=None,
    exocet_patterns=None,
    exocet_results=None,
    bowmans_attempts=None,
    bowmans_results=None,
    nested_depth=None,
    nested_proof_nodes=None,
    nested_branches=None,
    nested_subproofs=None,
    nested_results=None,
    nested_attempts=None,
    nested_predecessor_edges=None,
)

_STATE_ATTRIBUTE = "_sudoku_search_limits_p17"
_CANCELLATION_ATTRIBUTE = "_sudoku_cancellation_check_p17_1"


def search_limits(value=None):
    if value is None:
        return LIMITED_SEARCH_LIMITS
    if isinstance(value, SearchLimits):
        return value
    normalised = str(value).strip().casefold()
    if normalised == "limited":
        return LIMITED_SEARCH_LIMITS
    if normalised == "unlimited":
        return UNLIMITED_SEARCH_LIMITS
    raise ValueError(f"Modalita' SearchLimits sconosciuta: {value!r}.")


def bind_search_limits(state, value=None):
    limits = search_limits(value)
    try:
        setattr(state, _STATE_ATTRIBUTE, limits)
    except (AttributeError, TypeError):
        # I doppi di test senza attributi conservano il comportamento
        # limited. Gli stati Sudoku reali supportano sempre il binding.
        if limits is not LIMITED_SEARCH_LIMITS:
            raise TypeError(
                "Lo stato non supporta una configurazione SearchLimits."
            )
    return limits


def limits_for_state(state):
    return search_limits(getattr(state, _STATE_ATTRIBUTE, None))


def bind_cancellation_check(state, callback=None):
    """Collega una richiesta di arresto esterna alla singola analisi.

    Il callback non riceve argomenti e restituisce un valore booleano. La
    cancellazione resta separata dai limiti di ricerca: interrompe il calcolo
    in modo esplicito e rende l'esito ``TRUNCATED``.
    """
    if callback is not None and not callable(callback):
        raise TypeError("cancellation_check deve essere callable oppure None.")

    try:
        setattr(state, _CANCELLATION_ATTRIBUTE, callback)
    except (AttributeError, TypeError):
        if callback is not None:
            raise TypeError(
                "Lo stato non supporta una richiesta di cancellazione."
            )
    return callback


def cancellation_check_for_state(state):
    return getattr(state, _CANCELLATION_ATTRIBUTE, None)


def cancellation_signature_for_state(state):
    callback = cancellation_check_for_state(state)
    return None if callback is None else id(callback)


__all__ = [
    "COMPLETE_TREE_PROFILE",
    "DYNAMIC_PLUS_PROFILE",
    "DYNAMIC_PROFILE",
    "INFERENCE_PROFILES",
    "InferenceProfile",
    "LIMITED_SEARCH_LIMITS",
    "NESTED_LEVEL_1_PROFILE",
    "NESTED_LEVEL_2_PROFILE",
    "STATIC_PROFILE",
    "SearchLimits",
    "UNLIMITED_SEARCH_LIMITS",
    "bind_cancellation_check",
    "bind_search_limits",
    "cancellation_check_for_state",
    "cancellation_signature_for_state",
    "inference_profile",
    "limits_for_state",
    "profile_for_technique",
    "search_limits",
]
