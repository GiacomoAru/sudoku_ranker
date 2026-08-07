"""Motore risolutivo e analisi logica dei Sudoku.

A ogni passaggio il solver interroga le tecniche in ordine di difficolta' e
sceglie sempre la mossa certificata piu' semplice: la ``SearchPolicy``
(``mode``) non cambia mai quella scelta, cambia soltanto quante mosse
alternative vengono raccolte attorno a essa. Le cinque policy sono:

* ``superficial``   soltanto le mosse con difficolta' minima effettiva;
* ``smart_profile``  default. Scalino (``search_tier``, vedi
  ``technique_catalog``) della mossa minima, finestra ``p`` soltanto dentro
  quello scalino;
* ``full_profile``  finestra ``p`` su tutte le tecniche ordinarie, senza
  vincolo di scalino (comportamento storico di ``profile``);
* ``smart_deep``     scalino della mossa minima esplorato per intero, senza
  finestra;
* ``deep``           tutti gli scalini ordinari esplorati per intero, senza
  finestra.

Lo scalino raggruppa le tecniche come le cercherebbe un umano (famiglia
cognitiva), non come sono implementate: due tecniche possono condividere lo
stesso motore ma appartenere a scalini diversi. Contratto completo in
``TASSIONOMIA.md``, sezione "Scalini di ricerca P17".

Le tecniche di fallback (Nested Forcing Chain, Complete Forcing Tree) restano
fuori da ogni inventario ordinario, incluso ``deep``: sono interrogate solo
in assenza di mosse ordinarie (Nested) o ordinarie+Nested (Complete Tree),
allo stesso modo per ogni ``SearchPolicy`` — non e' la policy a decidere se
l'albero completo interviene, ma soltanto l'assenza di alternative piu'
semplici. Il solver prova nell'ordine tecniche ordinarie, Nested Forcing
Chain e Complete Forcing Tree, fermandosi al primo livello che produce mosse.
Le tecniche ordinarie possono restituire fino a 16 conclusioni, quelle del
Logic Engine fino a 8, le Nested fino a 2 e l'albero completo una sola.
Questi limiti riguardano i risultati, non la profondita' interna della
ricerca.

Ogni mossa possiede una difficolta' base determinata dalla tecnica e una
difficolta' tecnica effettiva. Quest'ultima aggiunge alla base la complessita'
concreta della prova, quando la mossa espone catene, assunzioni, rami o
metriche strutturali. La crescita e' logaritmica e non ha un limite massimo.

Ogni runner interrogato risponde FOUND (mosse trovate), EXHAUSTED (nessuna
mossa, ricerca completa) o TRUNCATED con cause tipizzate. ``SearchLimits``
centralizza i budget e offre le modalita' limited e unlimited. La mossa
scelta e' ``certified`` soltanto se nessun runner potenzialmente piu'
semplice ha subito un troncamento capace di nascondere il minimo reale.
"""

import math

from . import canonicalization as sc
from . import data_structure as sds
from . import difficulty as difficulty_model
from . import move_presentation
from . import proof_schema
from . import search_config
from . import techniques as st
from . import technique_catalog
from . import technique_registry


ANALYSIS_MODES = {
    "deep",
    "smart_deep",
    "full_profile",
    "smart_profile",
    "superficial",
}

# "profile" e "profilo" sono lo storico identificatore pre-P17: risolvono a
# ``full_profile`` per non alterare il comportamento di analisi gia'
# archiviate sul disco (vedi TECHNIQUE_SEARCH_TIER / repository.py). Nessun
# nuovo alias deve essere aggiunto senza un formato legacy reale da
# supportare (regola P19).
ANALYSIS_MODE_ALIASES = {
    "full": "deep",
    "profile": "full_profile",
    "profilo": "full_profile",
    "standard": "superficial",
    "shallow": "superficial",
    "superficiale": "superficial",
}

DEFAULT_PROFILE_DIFFICULTY_WINDOW = 1.5
DEFAULT_ANALYSIS_MODE = "smart_profile"
MAX_MOVES_PER_TECHNIQUE = (
    search_config.LIMITED_SEARCH_LIMITS.presentation_results
)
MAX_LOGIC_ENGINE_MOVES_PER_TECHNIQUE = (
    search_config.LIMITED_SEARCH_LIMITS.logic_presentation_results
)
MAX_NESTED_MOVES_PER_STEP = (
    search_config.LIMITED_SEARCH_LIMITS.nested_presentation_results
)
MAX_COMPLETE_TREE_MOVES_PER_STEP = (
    search_config.LIMITED_SEARCH_LIMITS.complete_tree_presentation_results
)
MAX_SOLVER_STEPS = 8_192

if not (
    1
    <= MAX_COMPLETE_TREE_MOVES_PER_STEP
    <= MAX_NESTED_MOVES_PER_STEP
    <= MAX_LOGIC_ENGINE_MOVES_PER_TECHNIQUE
    <= MAX_MOVES_PER_TECHNIQUE
):
    raise ValueError(
        "I limiti devono rispettare: Complete Tree <= Nested <= "
        "Logic Engine <= generale."
    )


_TECHNIQUE_RANK_BY_ID = {
    definition.id: index
    for index, definition in enumerate(sorted(
        technique_catalog.TECHNIQUE_DEFINITIONS,
        key=lambda item: (item.base_difficulty, item.priority),
    ))
}

# Pesi della crescita dinamica. Sono applicati alla prova concreta e non
# introducono alcun tetto massimo alla difficolta'.
_CHAIN_LENGTH_WEIGHT = 0.10
_CHAIN_COUNT_WEIGHT = 0.06
_ASSUMPTION_WEIGHT = 0.05
_SECONDARY_NODE_WEIGHT = 0.03
_BRANCH_WEIGHT = 0.06
_NESTED_DEPTH_WEIGHT = 0.08


# ---------------------------------------------------------------------------
# Difficolta' e ordinamento
# ---------------------------------------------------------------------------


def _move_definition(move):
    """Restituisce i metadata strutturali dichiarati dalla mossa."""
    technique_id = move.get("technique_id")
    if not technique_id:
        raise ValueError("La mossa non dichiara technique_id.")
    try:
        return technique_catalog.technique_definition(technique_id)
    except KeyError as error:
        raise ValueError(
            f"La mossa dichiara un technique_id sconosciuto: "
            f"{technique_id!r}."
        ) from error


def _base_difficulty(move):
    """Difficolta' minima associata alla tecnica della mossa."""
    return float(_move_definition(move).base_difficulty)


def _proof_metrics(move):
    """Legge esclusivamente le metriche normalizzate della prova."""
    return proof_schema.normalize_proof_metrics(
        move.get("logic", {}) or {}
    )


def _proof_complexity_extra(move):
    """Incremento illimitato basato sulla complessita' della prova."""
    definition = _move_definition(move)
    metric_profile = set(definition.proof_metric_profile)
    metrics = _proof_metrics(move)

    has_proof_structure = any(
        metrics[name] > 0
        for name in (
            "chain_count",
            "max_chain_length",
            "assumption_count",
            "branch_count",
            "nested_depth",
        )
    )
    proof_technique = bool(metric_profile & {
        "proof_node_count",
        "proof_edge_count",
        "chain_count",
        "max_chain_length",
        "assumption_count",
        "branch_count",
        "nested_depth",
        "nested_subproof_count",
    })

    if not has_proof_structure and not proof_technique:
        return 0.0

    max_chain_length = metrics["max_chain_length"]
    chain_count = max(metrics["chain_count"], 1.0)
    assumption_count = max(metrics["assumption_count"], 1.0)
    secondary_nodes = max(
        0.0,
        metrics["proof_node_count"] - max_chain_length,
    )

    length_extra = (
        _CHAIN_LENGTH_WEIGHT
        * math.log2(
            1.0 + max(0.0, max_chain_length - 4.0) / 4.0
        )
    )
    chain_extra = (
        _CHAIN_COUNT_WEIGHT
        * math.log2(chain_count)
    )
    assumption_extra = (
        _ASSUMPTION_WEIGHT
        * math.log2(assumption_count)
    )
    node_extra = (
        _SECONDARY_NODE_WEIGHT
        * math.log2(1.0 + secondary_nodes / 8.0)
    )
    branch_extra = (
        _BRANCH_WEIGHT
        * math.log2(1.0 + metrics["branch_count"] / 4.0)
    )
    depth_extra = (
        _NESTED_DEPTH_WEIGHT
        * math.log2(max(metrics["nested_depth"], 1.0))
    )

    raw_extra = (
        length_extra
        + chain_extra
        + assumption_extra
        + node_extra
        + branch_extra
        + depth_extra
    )

    if definition.fallback_tier > 0:
        family_scale = 1.0
    elif metric_profile & {"assumption_count", "branch_count", "leaf_count"}:
        family_scale = 0.85
    elif metric_profile & {
        "proof_edge_count",
        "chain_count",
        "max_chain_length",
    }:
        family_scale = 0.70
    else:
        family_scale = 0.50

    return family_scale * raw_extra


def _technical_difficulty_score(move):
    """Difficolta' base piu' la complessita' concreta della prova."""
    stored = move.get("technical_difficulty")
    if stored is not None:
        try:
            return float(stored)
        except (TypeError, ValueError):
            pass

    return round(
        _base_difficulty(move) + _proof_complexity_extra(move),
        1,
    )


def _prepare_move(move):
    """Normalizza una mossa e materializza le sue difficolta'."""
    definition = _move_definition(move)
    move.setdefault("technique", definition.canonical_name)
    move.setdefault(
        "family",
        technique_catalog.TECHNIQUE_FAMILY[definition.canonical_name],
    )
    move.setdefault(
        "strategy",
        technique_catalog.TECHNIQUE_STRATEGY[definition.canonical_name],
    )
    move["parent_id"] = definition.parent_id
    move["se_equivalent_parent_id"] = (
        definition.se_equivalent_parent_id
    )
    move["rating_kind"] = definition.rating_kind
    if move.get("logic") is not None:
        move["logic"] = proof_schema.normalize_proof(
            move["logic"],
            placements=move.get("placements", ()),
            eliminations=move.get("eliminations", ()),
        )
    metrics = _proof_metrics(move)
    extra = _proof_complexity_extra(move)
    move["base_difficulty"] = _base_difficulty(move)
    move["difficulty_extra"] = round(extra, 3)
    move["difficulty_metrics"] = metrics
    move["technical_difficulty"] = round(
        move["base_difficulty"] + extra,
        1,
    )
    return move


def _difficulty_score(move):
    """Difficolta' effettiva usata da scelta, profilo e inventario."""
    return _technical_difficulty_score(move)


def _tie_rank(move):
    return _TECHNIQUE_RANK_BY_ID.get(
        _move_definition(move).id,
        len(_TECHNIQUE_RANK_BY_ID),
    )


def _move_sort_key(move, canonical_transform=None):
    metrics = _proof_metrics(move)
    key = (
        _difficulty_score(move),
        _tie_rank(move),
        metrics["proof_node_count"],
        metrics["max_chain_length"],
        proof_schema.proof_signature(move.get("logic", {})),
    )

    if canonical_transform is None:
        return key

    placements = tuple(sorted(
        canonical_transform.map_candidate(row, column, value)
        for row, column, value in move.get("placements", ())
    ))
    eliminations = tuple(sorted(
        canonical_transform.map_candidate(row, column, value)
        for row, column, value in move.get("eliminations", ())
    ))

    return key + (placements, eliminations)


# ---------------------------------------------------------------------------
# Raccolta delle mosse
# ---------------------------------------------------------------------------


def _normalise_analysis_mode(mode):
    """Valida e normalizza il livello di profondita' dell'inventario."""
    if mode is None:
        return DEFAULT_ANALYSIS_MODE

    normalised = str(mode).strip().lower()
    normalised = ANALYSIS_MODE_ALIASES.get(normalised, normalised)

    if normalised not in ANALYSIS_MODES:
        allowed = ", ".join(sorted(ANALYSIS_MODES))
        raise ValueError(
            f"Modalita' di analisi non valida: {mode!r}. "
            f"Valori ammessi: {allowed}."
        )

    return normalised


def _normalise_solver_step_limit(max_steps):
    if isinstance(max_steps, bool):
        raise TypeError("max_steps deve essere un intero positivo.")
    try:
        max_steps = int(max_steps)
    except (TypeError, ValueError) as error:
        raise TypeError("max_steps deve essere un intero positivo.") from error
    if not 1 <= max_steps <= MAX_SOLVER_STEPS:
        raise ValueError(
            f"max_steps deve essere compreso tra 1 e {MAX_SOLVER_STEPS}."
        )
    return max_steps


def _move_outcome_signature(move):
    """Firma dell'intero risultato della mossa, indipendente dalla prova."""
    return (
        tuple(sorted(
            (int(r), int(c), int(value))
            for r, c, value in move.get("placements", ())
        )),
        tuple(sorted(
            (int(r), int(c), int(value))
            for r, c, value in move.get("eliminations", ())
        )),
    )


def _result_limit_for_classification(
    engine_type,
    fallback_tier,
    general_limit,
):
    if fallback_tier == 2:
        return min(general_limit, MAX_COMPLETE_TREE_MOVES_PER_STEP)
    if fallback_tier == 1:
        return min(general_limit, MAX_NESTED_MOVES_PER_STEP)
    if fallback_tier != 0:
        raise ValueError(f"Fallback tier sconosciuto: {fallback_tier!r}.")
    if engine_type != "local":
        return min(
            general_limit,
            MAX_LOGIC_ENGINE_MOVES_PER_TECHNIQUE,
        )
    return general_limit


def _result_limit_for_move(move, general_limit):
    definition = _move_definition(move)
    return _result_limit_for_classification(
        definition.engine_type,
        definition.fallback_tier,
        general_limit,
    )


def _result_limit_for_runner(runner, general_limit):
    return _result_limit_for_classification(
        runner.engine_type,
        runner.fallback_tier,
        general_limit,
    )


def _validate_runner_move(runner, move):
    definition = _move_definition(move)
    if (
        definition.id not in runner.technique_ids
        or definition.detector_id != runner.detector_id
    ):
        raise ValueError(
            f"Il detector {runner.detector_id!r} ha prodotto la tecnica "
            f"non dichiarata {definition.id!r}."
        )
    move["detector_id"] = runner.detector_id
    move["engine_type"] = runner.engine_type
    move["inference_engine"] = definition.inference_engine
    move["fallback_tier"] = runner.fallback_tier
    return move


def _call_registered_runner(runner, state):
    definitions = tuple(
        technique_catalog.technique_definition(technique_id)
        for technique_id in runner.technique_ids
    )
    uniqueness_verified = (
        getattr(
            state,
            "uniqueness_status",
            sds.UNIQUENESS_NOT_CHECKED,
        ) == sds.UNIQUENESS_VERIFIED
    )
    if (
        definitions
        and all(
            definition.requires_unique_solution
            for definition in definitions
        )
        and not uniqueness_verified
    ):
        return []
    moves = runner.collect(state)
    if uniqueness_verified:
        return moves
    return [
        move
        for move in (moves or ())
        if not _move_definition(move).requires_unique_solution
    ]


def _deduplicate_moves(moves, canonical_transform=None):
    """Conserva la prova meno costosa per ogni esito della tecnica."""
    unique = {}

    for move in moves:
        signature = (
            _move_definition(move).id,
            _move_outcome_signature(move),
        )
        previous = unique.get(signature)

        if previous is None or _move_sort_key(
            move,
            canonical_transform,
        ) < _move_sort_key(
            previous,
            canonical_transform,
        ):
            unique[signature] = move

    return list(unique.values())


def _limit_moves_per_technique(
    moves,
    max_moves_per_technique,
    canonical_transform=None,
):
    ordered = sorted(
        moves,
        key=lambda move: _move_sort_key(
            move,
            canonical_transform,
        ),
    )
    counts = {}
    limited = []
    capped = set()

    for move in ordered:
        definition = _move_definition(move)
        technique_id = definition.id
        display_name = move.get("technique", definition.canonical_name)
        technique_limit = _result_limit_for_move(
            move,
            max_moves_per_technique,
        )
        count = counts.get(technique_id, 0)

        if count >= technique_limit:
            capped.add(display_name)
            continue

        counts[technique_id] = count + 1
        limited.append(move)

    return limited, capped


def _collect_from_runners(
    state,
    runners,
    *,
    mode,
    profile_difficulty_window,
    canonical_transform,
    max_results,
):
    moves = []
    best_difficulty = None
    best_search_tier = None
    scanned_runner_count = 0
    stopped_early = False
    stop_before_min_difficulty = None
    capped_techniques = set()
    result_limit_reached = False
    detector_searches = []
    truncated_detector_ids = set()

    def affects_minimum(reasons, found_moves):
        """Distingue un inventario censurato da un minimo incerto."""
        if not reasons:
            return False
        if not found_moves:
            return True
        return any(
            reason != "runner_result_limit"
            and not reason.endswith("_result_limit")
            for reason in reasons
        )

    for runner in runners:
        minimum_difficulty = runner.minimum_difficulty
        if best_difficulty is not None:
            # smart_profile e smart_deep restringono per search_tier soltanto
            # nel filtro finale (un detector puo' emettere piu' tecniche a
            # scalini diversi, es. il motore ALS): qui la soglia resta un
            # superset per difficolta', mai piu' stretta di full_profile.
            runner_tiers = {
                definition.search_tier
                for definition in (
                    technique_catalog.technique_definition(technique_id)
                    for technique_id in runner.technique_ids
                )
            }
            if mode == "superficial":
                difficulty_limit = best_difficulty
            elif mode in ("smart_profile", "full_profile"):
                difficulty_limit = (
                    best_difficulty
                    + profile_difficulty_window
                )
            else:
                difficulty_limit = None

            # Dopo la frontiera che potrebbe ancora migliorare d_min, gli
            # smart profile interrogano soltanto detector dello scalino
            # certificato. smart_profile conserva anche la propria finestra.
            if (
                mode in ("smart_profile", "smart_deep")
                and float(minimum_difficulty) > best_difficulty
                and best_search_tier not in runner_tiers
            ):
                continue

            if (
                difficulty_limit is not None
                and float(minimum_difficulty) > difficulty_limit
            ):
                stopped_early = True
                stop_before_min_difficulty = float(minimum_difficulty)
                break

        scanned_runner_count += 1
        runner_limit = _result_limit_for_runner(
            runner,
            max_results,
        )
        found = list(
            _call_registered_runner(runner, state) or []
        )
        search_metadata = st.detector_search_metadata(
            state,
            runner.detector_id,
        )
        truncated_reasons = set(
            search_metadata.get("truncated_reasons", ())
        )
        if (
            search_metadata.get("search_truncated", False)
            and not truncated_reasons
        ):
            truncated_reasons.add("unspecified_budget")
        if len(found) >= runner_limit:
            result_limit_reached = True
            truncated_reasons.add("runner_result_limit")

        prepared = [
            _prepare_move(_validate_runner_move(runner, move))
            for move in found
        ]
        prepared = _deduplicate_moves(
            prepared,
            canonical_transform,
        )
        prepared_minimum = (
            min(_difficulty_score(move) for move in prepared)
            if prepared
            else None
        )
        detector_truncated = bool(
            search_metadata.get("search_truncated", False)
            or truncated_reasons
        )
        minimum_certification_affected = affects_minimum(
            truncated_reasons,
            prepared,
        )
        if detector_truncated:
            truncated_detector_ids.add(runner.detector_id)
        detector_searches.append({
            "detector_id": runner.detector_id,
            "minimum_difficulty": float(minimum_difficulty),
            "found_count": len(prepared),
            "found_minimum_difficulty": prepared_minimum,
            "outcome": (
                "TRUNCATED"
                if detector_truncated
                else "FOUND"
                if prepared
                else "EXHAUSTED"
            ),
            "completion": (
                "truncated" if detector_truncated else "exhausted"
            ),
            "minimum_certification_affected": (
                minimum_certification_affected
            ),
            "inference_profile_id": search_metadata.get(
                "inference_profile_id"
            ),
            "truncated_reasons": sorted(truncated_reasons),
        })

        raw_counts = {}
        representative_moves = {}
        for move in prepared:
            technique_id = _move_definition(move).id
            raw_counts[technique_id] = (
                raw_counts.get(technique_id, 0) + 1
            )
            representative_moves.setdefault(technique_id, move)
        if any(
            count >= _result_limit_for_move(
                representative_moves[technique_id],
                max_results,
            )
            for technique_id, count in raw_counts.items()
        ):
            result_limit_reached = True

        prepared, local_capped = _limit_moves_per_technique(
            prepared,
            max_results,
            canonical_transform,
        )
        capped_techniques.update(local_capped)

        if not prepared:
            continue

        moves.extend(prepared)
        current_best = min(
            moves,
            key=lambda move: _move_sort_key(
                move,
                canonical_transform,
            ),
        )
        best_search_tier = _move_definition(current_best).search_tier
        best_difficulty = min(
            _difficulty_score(move) for move in moves
        )

    moves = _deduplicate_moves(
        moves,
        canonical_transform,
    )
    moves, final_capped = _limit_moves_per_technique(
        moves,
        max_results,
        canonical_transform,
    )
    capped_techniques.update(final_capped)

    if moves:
        best_difficulty = min(
            _difficulty_score(move)
            for move in moves
        )

        if mode == "superficial":
            moves = [
                move
                for move in moves
                if math.isclose(
                    _difficulty_score(move),
                    best_difficulty,
                    rel_tol=0.0,
                    abs_tol=1e-9,
                )
            ]
        elif mode == "full_profile":
            difficulty_limit = (
                best_difficulty
                + profile_difficulty_window
            )
            moves = [
                move
                for move in moves
                if _difficulty_score(move) <= difficulty_limit
            ]
        elif mode in ("smart_profile", "smart_deep"):
            # La mossa minima certificata (stesso ordinamento usato per
            # scegliere la mossa da applicare) fissa lo scalino di ricerca:
            # smart_profile e smart_deep non attraversano mai quello
            # scalino, a differenza di full_profile/deep.
            best_move = min(
                moves,
                key=lambda move: _move_sort_key(
                    move,
                    canonical_transform,
                ),
            )
            best_tier = _move_definition(best_move).search_tier
            if mode == "smart_profile":
                difficulty_limit = (
                    best_difficulty
                    + profile_difficulty_window
                )
                moves = [
                    move
                    for move in moves
                    if _difficulty_score(move) <= difficulty_limit
                    and _move_definition(move).search_tier == best_tier
                ]
            else:
                moves = [
                    move
                    for move in moves
                    if _move_definition(move).search_tier == best_tier
                ]

    # Una mossa minima e' certificata quando ogni detector che potrebbe
    # produrre una difficolta' strettamente inferiore ha concluso la ricerca.
    # Un troncamento alla stessa soglia puo' nascondere mosse equivalenti, ma
    # non una mossa piu' semplice; censura quindi l'inventario e non il minimo.
    if best_difficulty is None:
        truncated_before_best_difficulty = any(
            search["completion"] == "truncated"
            and search["minimum_certification_affected"]
            for search in detector_searches
        )
    else:
        truncated_before_best_difficulty = any(
            search["completion"] == "truncated"
            and search["minimum_certification_affected"]
            and search["minimum_difficulty"] < best_difficulty
            for search in detector_searches
        )

    return moves, {
        "best_difficulty": best_difficulty,
        "scanned_runner_count": scanned_runner_count,
        "stopped_early": stopped_early,
        "stop_before_min_difficulty": stop_before_min_difficulty,
        "capped_techniques": sorted(capped_techniques),
        "result_limit_reached": result_limit_reached,
        "truncated_before_best_difficulty": truncated_before_best_difficulty,
        "truncated_detector_ids": sorted(truncated_detector_ids),
        "detector_searches": detector_searches,
    }


def collect_moves_for_analysis(
    state,
    mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=DEFAULT_PROFILE_DIFFICULTY_WINDOW,
    canonical_transform=None,
    max_moves_per_technique=None,
    search_limits="limited",
    cancellation_check=None,
):
    """Raccoglie mosse secondo policy, limiti e livelli di fallback P17.

    ``mode`` seleziona la ``SearchPolicy`` (vedi docstring di modulo):
    ``superficial``, ``smart_profile`` (default), ``full_profile``,
    ``smart_deep`` o ``deep``. Nessuna policy cambia la mossa minima
    certificata, solo quante alternative vengono raccolte attorno a essa.

    Nested viene interrogato solo senza mosse ordinarie; Complete Forcing Tree
    solo senza mosse ordinarie e Nested, indipendentemente da ``mode``. Il
    primo livello con risultati chiude la raccolta.

    ``search_limits`` accetta ``limited``, ``unlimited`` oppure un oggetto
    ``SearchLimits`` immutabile.

    ``cancellation_check`` permette un arresto esterno esplicito del fallback
    completo. Un arresto produce un detector ``TRUNCATED`` e nessuna mossa
    parziale.
    """
    mode = _normalise_analysis_mode(mode)
    limits = search_config.bind_search_limits(state, search_limits)
    search_config.bind_cancellation_check(state, cancellation_check)

    if profile_difficulty_window is None:
        profile_difficulty_window = DEFAULT_PROFILE_DIFFICULTY_WINDOW

    profile_difficulty_window = float(profile_difficulty_window)

    if profile_difficulty_window < 0:
        raise ValueError(
            "profile_difficulty_window deve essere maggiore o uguale a 0."
        )

    if max_moves_per_technique is None:
        max_moves_per_technique = limits.presentation_results

    if (
        isinstance(max_moves_per_technique, bool)
        or int(max_moves_per_technique) < 1
    ):
        raise ValueError(
            "max_moves_per_technique deve essere positivo."
        )

    max_moves_per_technique = int(max_moves_per_technique)
    ordinary_runners = technique_registry.ORDINARY_RUNNERS
    nested_runners = technique_registry.NESTED_RUNNERS
    complete_tree_runners = technique_registry.COMPLETE_TREE_RUNNERS

    moves, ordinary_metadata = _collect_from_runners(
        state,
        ordinary_runners,
        mode=mode,
        profile_difficulty_window=profile_difficulty_window,
        canonical_transform=canonical_transform,
        max_results=max_moves_per_technique,
    )

    def empty_metadata():
        return {
            "best_difficulty": None,
            "scanned_runner_count": 0,
            "stopped_early": False,
            "stop_before_min_difficulty": None,
            "capped_techniques": [],
            "result_limit_reached": False,
            "truncated_before_best_difficulty": False,
            "truncated_detector_ids": [],
            "detector_searches": [],
        }

    ordinary_moves_found = bool(moves)
    nested_fallback_attempted = False
    nested_fallback_used = False
    complete_tree_fallback_attempted = False
    complete_tree_fallback_used = False
    nested_metadata = empty_metadata()
    complete_tree_metadata = empty_metadata()

    if not moves and nested_runners:
        nested_fallback_attempted = True
        moves, nested_metadata = _collect_from_runners(
            state,
            nested_runners,
            mode="deep",
            profile_difficulty_window=profile_difficulty_window,
            canonical_transform=canonical_transform,
            max_results=limits.nested_presentation_results,
        )
        nested_fallback_used = bool(moves)

    if not moves and complete_tree_runners:
        complete_tree_fallback_attempted = True
        moves, complete_tree_metadata = _collect_from_runners(
            state,
            complete_tree_runners,
            mode="deep",
            profile_difficulty_window=profile_difficulty_window,
            canonical_transform=canonical_transform,
            max_results=limits.complete_tree_presentation_results,
        )
        complete_tree_fallback_used = bool(moves)

    inventory_censored = (
        ordinary_metadata["result_limit_reached"]
        or bool(ordinary_metadata["truncated_detector_ids"])
        or nested_fallback_attempted
        or complete_tree_fallback_attempted
    )

    if complete_tree_fallback_used:
        fallback_tier_used = 2
        fallback_stage = "complete_tree"
        fallback_reason = "no_ordinary_or_nested_move"
        active_metadata = complete_tree_metadata
    elif nested_fallback_used:
        fallback_tier_used = 1
        fallback_stage = "nested"
        fallback_reason = "no_ordinary_move"
        active_metadata = nested_metadata
    elif ordinary_moves_found:
        fallback_tier_used = 0
        fallback_stage = "ordinary"
        fallback_reason = None
        active_metadata = ordinary_metadata
    else:
        fallback_tier_used = None
        fallback_stage = None
        fallback_reason = "no_available_move"
        active_metadata = (
            complete_tree_metadata
            if complete_tree_fallback_attempted
            else nested_metadata
            if nested_fallback_attempted
            else ordinary_metadata
        )

    capped_techniques = sorted(set(
        ordinary_metadata["capped_techniques"]
        + nested_metadata["capped_techniques"]
        + complete_tree_metadata["capped_techniques"]
    ))

    # P17: la cascata ordinary -> Nested -> Complete Tree e' certificata solo
    # se ogni stadio effettivamente interrogato (non soltanto quello vincente)
    # non ha subito troncamenti che potrebbero nascondere una mossa piu'
    # semplice o smentire un EXHAUSTED dichiarato. Uno stadio mai tentato non
    # puo' compromettere la certificazione.
    certified = not ordinary_metadata["truncated_before_best_difficulty"]
    if nested_fallback_attempted:
        certified = (
            certified
            and not nested_metadata["truncated_before_best_difficulty"]
        )
    if complete_tree_fallback_attempted:
        certified = (
            certified
            and not complete_tree_metadata[
                "truncated_before_best_difficulty"
            ]
        )
    truncated_detector_ids = sorted(set(
        ordinary_metadata["truncated_detector_ids"]
        + nested_metadata["truncated_detector_ids"]
        + complete_tree_metadata["truncated_detector_ids"]
    ))
    detector_searches = (
        ordinary_metadata["detector_searches"]
        + nested_metadata["detector_searches"]
        + complete_tree_metadata["detector_searches"]
    )

    metadata = {
        "mode": mode,
        "profile_difficulty_window": (
            profile_difficulty_window
            if mode in ("smart_profile", "full_profile")
            else None
        ),
        "best_difficulty": active_metadata["best_difficulty"],
        "scanned_runner_count": (
            ordinary_metadata["scanned_runner_count"]
            + nested_metadata["scanned_runner_count"]
            + complete_tree_metadata["scanned_runner_count"]
        ),
        "total_runner_count": len(
            technique_registry.TECHNIQUE_RUNNERS
        ),
        "ordinary_runner_count": len(ordinary_runners),
        "nested_runner_count": len(nested_runners),
        "complete_tree_runner_count": len(
            complete_tree_runners
        ),
        "stopped_early": ordinary_metadata["stopped_early"],
        "stop_before_min_difficulty": ordinary_metadata[
            "stop_before_min_difficulty"
        ],
        "all_ordinary_runners_scanned": (
            not ordinary_metadata["stopped_early"]
        ),
        "complete_inventory": (
            not ordinary_metadata["stopped_early"]
            and not capped_techniques
            and not inventory_censored
        ),
        "inventory_censored": inventory_censored,
        "result_limit_reached": (
            ordinary_metadata["result_limit_reached"]
            or nested_metadata["result_limit_reached"]
            or complete_tree_metadata["result_limit_reached"]
        ),
        "fallback_tier_used": fallback_tier_used,
        "fallback_stage": fallback_stage,
        "nested_fallback_attempted": nested_fallback_attempted,
        "nested_fallback_used": nested_fallback_used,
        "complete_tree_fallback_attempted": (
            complete_tree_fallback_attempted
        ),
        "complete_tree_fallback_used": complete_tree_fallback_used,
        "fallback_reason": fallback_reason,
        "max_moves_per_technique": max_moves_per_technique,
        "max_logic_engine_moves_per_technique": (
            MAX_LOGIC_ENGINE_MOVES_PER_TECHNIQUE
        ),
        "max_nested_moves_per_step": MAX_NESTED_MOVES_PER_STEP,
        "max_complete_tree_moves_per_step": (
            MAX_COMPLETE_TREE_MOVES_PER_STEP
        ),
        "max_static_cycle_edges": limits.static_cycle_edges,
        "search_limits_mode": limits.mode,
        "search_limits": limits.to_dict(),
        "inference_profiles": {
            profile_id: profile.to_dict()
            for profile_id, profile in search_config.INFERENCE_PROFILES.items()
        },
        "capped_techniques": capped_techniques,
        "certified": certified,
        "truncated_detector_ids": truncated_detector_ids,
        "detector_searches": detector_searches,
    }

    return moves, metadata


def collect_all_moves(state, early_stop=True):
    """Interfaccia compatibile per la raccolta delle mosse."""
    mode = "superficial" if early_stop else "deep"
    moves, _ = collect_moves_for_analysis(state, mode=mode)
    return moves


def collect_all_moves_full(state):
    """Interroga tutte le tecniche ordinarie, con Nested di fallback."""
    moves, _ = collect_moves_for_analysis(state, mode="deep")
    return moves


# ---------------------------------------------------------------------------
# Inventario e applicazione
# ---------------------------------------------------------------------------


def _effective_nearby_move_count(
    moves,
    best_difficulty,
    max_moves=MAX_MOVES_PER_TECHNIQUE,
):
    """Calcola il numero pesato di conclusioni vicine alla migliore."""
    best_difficulty = float(best_difficulty)
    max_moves = max(int(max_moves), 1)
    outcome_difficulties = {}

    for move in moves:
        outcome = _move_outcome_signature(move)
        difficulty = _difficulty_score(move)
        previous = outcome_difficulties.get(outcome)

        if previous is None or difficulty < previous:
            outcome_difficulties[outcome] = difficulty

    ordered_difficulties = sorted(
        outcome_difficulties.values()
    )
    contributions = []

    for position, difficulty in enumerate(
        ordered_difficulties,
        start=1,
    ):
        se_distance = max(
            0.0,
            difficulty - best_difficulty,
        )
        se_weight = 2.0 ** (
            -se_distance
            / difficulty_model.MOVE_DISCOVERY_SE_HALF_LIFE
        )

        if position <= max_moves:
            position_weight = 1.0
        else:
            extra_position = position - max_moves
            position_weight = (
                difficulty_model
                .MOVE_DISCOVERY_EXTRA_MOVE_DECAY
                ** extra_position
            )

        contributions.append(
            se_weight * position_weight
        )

    return max(
        1.0,
        math.fsum(contributions),
    )


def _build_move_inventory(moves, best_difficulty):
    """Riassume gli esiti distinti utili a rating e heatmap."""
    all_outcomes = set()
    frontier_outcomes = set()
    by_technique = {}
    frontier_by_technique = {}
    technique_ranks = {}

    for move in moves:
        definition = _move_definition(move)
        technique = move.get("technique", definition.canonical_name)
        technique_ranks.setdefault(
            technique,
            _TECHNIQUE_RANK_BY_ID.get(
                definition.id,
                len(_TECHNIQUE_RANK_BY_ID),
            ),
        )
        outcome = _move_outcome_signature(move)
        all_outcomes.add(outcome)
        by_technique.setdefault(technique, set()).add(outcome)

        if math.isclose(
            _difficulty_score(move),
            best_difficulty,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            frontier_outcomes.add(outcome)
            frontier_by_technique.setdefault(
                technique,
                set(),
            ).add(outcome)

    return {
        "available_move_count": len(all_outcomes),
        "frontier_move_count": len(frontier_outcomes),
        "available_by_technique": {
            technique: len(outcomes)
            for technique, outcomes in sorted(
                by_technique.items(),
                key=lambda item: technique_ranks[item[0]],
            )
        },
        "frontier_by_technique": {
            technique: len(outcomes)
            for technique, outcomes in sorted(
                frontier_by_technique.items(),
                key=lambda item: technique_ranks[item[0]],
            )
        },
    }


def apply_move(state, move):
    for row, column, value in move.get("placements", ()):
        state.place(row, column, value)

    for row, column, value in move.get("eliminations", ()):
        state.eliminate(row, column, value)


def solve_and_log(
    grid,
    max_steps=MAX_SOLVER_STEPS,
    verbose=False,
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=DEFAULT_PROFILE_DIFFICULTY_WINDOW,
    uniqueness_status=sds.UNIQUENESS_NOT_CHECKED,
    search_limits="limited",
    cancellation_check=None,
):
    """Risolve il Sudoku e registra l'inventario logico di ogni stato."""
    max_steps = _normalise_solver_step_limit(max_steps)
    analysis_mode = _normalise_analysis_mode(analysis_mode)
    state = sds.SudokuState(
        grid,
        uniqueness_status=uniqueness_status,
    )
    canonical_transform = sc.canonicalize_details(
        state.grid
    ).transform
    chain = []
    step_no = 0

    while not state.is_solved() and step_no < max_steps:
        if state.is_stuck():
            return state, chain, "contradiction"

        moves, collection_metadata = collect_moves_for_analysis(
            state,
            mode=analysis_mode,
            profile_difficulty_window=profile_difficulty_window,
            canonical_transform=canonical_transform,
            search_limits=search_limits,
            cancellation_check=cancellation_check,
        )

        if not moves:
            if any(
                "external_cancellation" in search.get(
                    "truncated_reasons", ()
                )
                for search in collection_metadata["detector_searches"]
            ):
                return state, chain, "cancelled"
            return state, chain, "stuck"

        moves.sort(
            key=lambda move: _move_sort_key(
                move,
                canonical_transform,
            )
        )
        chosen = moves[0]
        base_score = _base_difficulty(chosen)
        technical_score = _difficulty_score(chosen)

        inventory = _build_move_inventory(
            moves,
            best_difficulty=technical_score,
        )
        available_move_count = max(
            int(inventory["available_move_count"]),
            1,
        )
        frontier_move_count = max(
            int(inventory["frontier_move_count"]),
            1,
        )
        effective_move_count = _effective_nearby_move_count(
            moves=moves,
            best_difficulty=technical_score,
            max_moves=MAX_MOVES_PER_TECHNIQUE,
        )
        move_discovery_difficulty = (
            difficulty_model.step_move_discovery_difficulty(
                effective_move_count=effective_move_count,
                max_moves=MAX_MOVES_PER_TECHNIQUE,
            )
        )
        discovery_is_upper_bound = bool(
            collection_metadata["inventory_censored"]
        )
        effective_move_count = round(effective_move_count, 2)
        resolution_load = difficulty_model.step_resolution_load(
            technical_score
        )

        grid_before = state.grid.copy()
        candidates_before = move_presentation.snapshot_candidates(state)
        apply_move(state, chosen)
        candidates_after = move_presentation.snapshot_candidates(state)
        step_no += 1

        record = {
            key: chosen[key]
            for key in (
                "technique_id",
                "technique",
                "family",
                "strategy",
                "parent_id",
                "se_equivalent_parent_id",
                "rating_kind",
                "detector_id",
                "engine_type",
                "inference_engine",
                "fallback_tier",
                "description",
                "explanation",
                "placements",
                "eliminations",
                "highlight",
                "visual_evidence",
                "logic",
                "fish_pattern",
                "fish_size",
                "base_set_count",
                "cover_set_count",
                "fin_count",
                "endo_fin_count",
                "cannibalistic_count",
                "coloring_pattern",
                "als_pattern",
                "als_parent_technique_id",
                "als_node_count",
                "rcc_count",
                "template_pattern",
                "template_count",
                "template_digit",
                "kraken_pattern",
                "kraken_branch_count",
                "color_digit",
                "color_component_count",
                "color_node_count",
                "color_link_count",
                "difficulty_extra",
                "difficulty_metrics",
                "proof_count",
                "conclusion_count",
            )
            if key in chosen
        }
        record["step"] = step_no
        record["grid_before"] = grid_before
        record["grid_after"] = state.grid.copy()
        record["candidates_before"] = candidates_before
        record["candidates_after"] = candidates_after
        record["base_difficulty"] = base_score
        record["technical_difficulty"] = technical_score
        record["resolution_load"] = resolution_load
        record["move_discovery_difficulty"] = (
            move_discovery_difficulty
        )
        record["available_move_count"] = available_move_count
        record["frontier_move_count"] = frontier_move_count
        record["effective_move_count"] = effective_move_count
        record["available_by_technique"] = inventory[
            "available_by_technique"
        ]
        record["frontier_by_technique"] = inventory[
            "frontier_by_technique"
        ]
        record["nested_fallback_used"] = collection_metadata[
            "nested_fallback_used"
        ]
        record["nested_fallback_attempted"] = collection_metadata[
            "nested_fallback_attempted"
        ]
        record["complete_tree_fallback_used"] = collection_metadata[
            "complete_tree_fallback_used"
        ]
        record["complete_tree_fallback_attempted"] = collection_metadata[
            "complete_tree_fallback_attempted"
        ]
        record["fallback_tier_used"] = collection_metadata[
            "fallback_tier_used"
        ]
        record["fallback_stage"] = collection_metadata[
            "fallback_stage"
        ]
        record["fallback_reason"] = collection_metadata[
            "fallback_reason"
        ]
        record["move_inventory_censored"] = collection_metadata[
            "inventory_censored"
        ]
        record["effective_move_count_is_lower_bound"] = (
            discovery_is_upper_bound
        )
        record["move_discovery_difficulty_is_upper_bound"] = (
            discovery_is_upper_bound
        )

        if collection_metadata.get("capped_techniques"):
            record["capped_techniques"] = collection_metadata[
                "capped_techniques"
            ]

        # P17: la mossa scelta e' quella minima "conosciuta" finche' non e'
        # certificata, cioe' finche' un detector potenzialmente piu' semplice
        # ha risposto TRUNCATED invece di FOUND/EXHAUSTED.
        record["certified"] = collection_metadata["certified"]
        if collection_metadata.get("truncated_detector_ids"):
            record["truncated_detector_ids"] = collection_metadata[
                "truncated_detector_ids"
            ]

        chain.append(record)

        if verbose:
            fallback_stage = collection_metadata.get("fallback_stage")
            fallback = (
                f", fallback {fallback_stage}"
                if fallback_stage in {"nested", "complete_tree"}
                else ""
            )
            print(
                f"[{step_no:03d}] "
                f"{chosen['technique']:<36} "
                f"(SE {technical_score:.1f}"
                + (
                    f", base {base_score:.1f}"
                    if not math.isclose(
                        technical_score,
                        base_score,
                        rel_tol=0.0,
                        abs_tol=1e-9,
                    )
                    else ""
                )
                + ", "
                f"individuazione "
                f"{move_discovery_difficulty:.2f}, "
                f"mosse effettive {effective_move_count:.2f}, "
                f"mosse minime {frontier_move_count}, "
                f"modo {analysis_mode}{fallback}) "
                f"{chosen['description']}"
            )

    status = (
        "solved"
        if state.is_solved()
        else "step_limit"
    )
    return state, chain, status


def solve_with_naked_singles(grid, max_steps=81):
    """
    Prova a risolvere una griglia usando esclusivamente Naked Single.

    Non richiama ``analyse_puzzle``, ``collect_all_moves`` o altre tecniche.

    Restituisce:
        state:
            Stato finale raggiunto.
        chain:
            Mosse Naked Single applicate.
        status:
            ``"solved"``, ``"stuck"`` oppure ``"contradiction"``.
    """
    state = sds.SudokuState(grid)
    chain = []

    while not state.is_solved() and len(chain) < max_steps:
        if state.is_stuck():
            return state, chain, "contradiction"

        moves = st.naked_single(state)

        if not moves:
            return state, chain, "stuck"

        # Ordine deterministico: prima riga, poi colonna, poi valore.
        moves.sort(
            key=lambda move: move["placements"][0]
        )
        chosen = moves[0]

        grid_before = state.grid.copy()
        candidates_before = move_presentation.snapshot_candidates(state)
        apply_move(state, chosen)

        record = dict(chosen)
        record["step"] = len(chain) + 1
        record["grid_before"] = grid_before
        record["grid_after"] = state.grid.copy()
        record["candidates_before"] = candidates_before
        record["candidates_after"] = move_presentation.snapshot_candidates(state)
        chain.append(record)

    status = "solved" if state.is_solved() else "stuck"
    return state, chain, status


def _unsolved_peer_count(state, row, column):
    """
    Conta quante celle non risolte condividono riga, colonna o box.

    Viene usato solo come tie-break: a parità di propagazione si preferisce
    una casella che influenza più celle ancora vuote.
    """
    peers = set()

    for index in range(9):
        if index != column:
            peers.add((row, index))

        if index != row:
            peers.add((index, column))

    box_row = (row // 3) * 3
    box_column = (column // 3) * 3

    for r in range(box_row, box_row + 3):
        for c in range(box_column, box_column + 3):
            if (r, c) != (row, column):
                peers.add((r, c))

    return sum(
        state.grid[r, c] == 0
        for r, c in peers
    )


def trivialize_greedy(
    grid,
    max_added=None,
    prune=True,
    verbose=False,
    max_candidates_per_round=25,
    max_prune_checks=25,
):
    """
    Trova indizi aggiuntivi che rendono il Sudoku risolvibile usando
    esclusivamente Naked Single.

    Strategia greedy
    ----------------
    1. Propaga tutti i Naked Single già disponibili.
    2. Per ogni casella ancora irrisolta, prova ad aggiungere il suo valore
       corretto e misura quante celle vengono risolte dalla nuova cascata di
       Naked Single.
    3. Sceglie la casella con la propagazione maggiore.
    4. A parità, preferisce la casella con più candidati, cioè quella su cui
       lo stato corrente contiene meno informazione.
    5. Come ultimo tie-break preferisce la casella che vede più celle vuote.
    6. Quando il puzzle è diventato triviale, prova a rimuovere uno alla volta
       gli indizi aggiunti che risultano superflui.

    Il risultato è inclusion-minimal dopo la potatura: nessun singolo indizio
    restituito può essere rimosso mantenendo il puzzle risolvibile con soli
    Naked Single. Non è garantito che il numero totale di indizi sia il minimo
    globale, perché la ricerca è greedy.

    ``sds.backtracking_solve`` viene usato soltanto per conoscere la soluzione
    corretta da cui prendere i nuovi indizi. La verifica di trivialità usa
    esclusivamente ``st.naked_single``.

    Restituisce un dizionario con la nuova griglia, gli indizi aggiunti e la
    catena finale di Naked Single.
    """
    
    def _prune_added_clues(
        original,
        added_clues,
        greedy_history=None,
        max_prune_checks=12,
        verbose=False,
    ):
        """
        Potatura limitata degli indizi aggiunti.

        Ogni check corrisponde a una chiamata completa a
        solve_with_naked_singles.

        Prima tenta alcune rimozioni a gruppi, poi usa il budget restante
        per verificare singolarmente gli indizi più probabilmente superflui.

        Restituisce:
            pruned_clues
            checks
            is_inclusion_minimal
        """
        if max_prune_checks <= 0:
            return added_clues.copy(), 0, False

        active = set(added_clues)
        checks = 0
        proven_necessary = set()
        cache = {}

        history_data = {}

        if greedy_history is not None:
            for index, item in enumerate(greedy_history):
                clue = (
                    item["row"],
                    item["column"],
                    item["value"],
                )

                history_data[clue] = {
                    "index": index,
                    "propagation_gain": item.get(
                        "propagation_gain",
                        0,
                    ),
                }

        def removal_priority(clue):
            """
            Prima gli indizi con minore guadagno.

            A parità, prova prima quelli aggiunti più recentemente.
            """
            data = history_data.get(clue)

            if data is None:
                try:
                    index = added_clues.index(clue)
                except ValueError:
                    index = 0

                return 0, -index

            return (
                data["propagation_gain"],
                -data["index"],
            )

        def can_remove(clues_to_remove):
            nonlocal checks

            remove_set = frozenset(clues_to_remove)

            if not remove_set:
                return False

            if remove_set in cache:
                return cache[remove_set]

            if checks >= max_prune_checks:
                return None

            checks += 1

            trial_grid = original.copy()

            for row, column, value in active:
                if (row, column, value) not in remove_set:
                    trial_grid[row, column] = value

            _, _, status = solve_with_naked_singles(
                trial_grid
            )

            removable = status == "solved"
            cache[remove_set] = removable

            return removable

        # Circa un terzo del budget viene usato per tentare rimozioni
        # multiple. Il resto rimane disponibile per i controlli singoli.
        group_budget = min(
            max_prune_checks // 3,
            max(0, len(active) // 3),
        )

        if group_budget > 0 and len(active) >= 4:
            ordered = sorted(
                active,
                key=removal_priority,
            )

            # La dimensione viene scelta in base a quanti tentativi di gruppo
            # possiamo permetterci.
            chunk_size = max(
                2,
                min(
                    6,
                    len(ordered) // group_budget,
                ),
            )

            group_checks = 0
            start = 0

            while (
                start < len(ordered)
                and group_checks < group_budget
                and checks < max_prune_checks
            ):
                chunk = [
                    clue
                    for clue in ordered[
                        start:start + chunk_size
                    ]
                    if clue in active
                ]

                start += chunk_size

                if len(chunk) < 2:
                    continue

                removable = can_remove(chunk)
                group_checks += 1

                if removable is None:
                    break

                if removable:
                    active.difference_update(chunk)

                    if verbose:
                        print(
                            f"Prune: rimossi {len(chunk)} "
                            f"indizi in un solo check."
                        )

        # Ricalcola l'ordine perché alcuni indizi potrebbero essere già
        # stati rimossi durante la fase a gruppi.
        individual_order = sorted(
            active,
            key=removal_priority,
        )

        for clue in individual_order:
            if checks >= max_prune_checks:
                break

            if clue not in active:
                continue

            removable = can_remove([clue])

            if removable is None:
                break

            if removable:
                active.remove(clue)

                if verbose:
                    row, column, value = clue
                    print(
                        f"Prune: rimosso "
                        f"R{row + 1}C{column + 1}={value}."
                    )
            else:
                proven_necessary.add(clue)

        # Un indizio che risulta necessario non deve essere ricontrollato
        # dopo la rimozione di altri indizi. Con ancora meno indizi non può
        # diventare improvvisamente rimovibile.
        is_inclusion_minimal = active.issubset(
            proven_necessary
        )

        # Mantiene l'ordine originale degli indizi.
        pruned_clues = [
            clue
            for clue in added_clues
            if clue in active
        ]

        return (
            pruned_clues,
            checks,
            is_inclusion_minimal,
        )
    
    original = sds.SudokuState(grid).grid.copy()
    solution = sds.backtracking_solve(original)
    
    if solution is None:
        raise ValueError(
            "Il Sudoku non ha una soluzione valida."
        )

    current_grid = original.copy()
    added_clues = []
    greedy_history = []

    while True:
        current_state, _, status = solve_with_naked_singles(
            current_grid
        )

        if status == "contradiction":
            raise ValueError(
                "La griglia ha prodotto una contraddizione."
            )

        if status == "solved":
            break

        if (
            max_added is not None
            and len(added_clues) >= max_added
        ):
            break

        solved_before = int(
            (current_state.grid != 0).sum()
        )
        candidates = []

        
        cells = [
            (row, column)
            for row in range(9)
            for column in range(9)
            if current_state.grid[row, column] == 0
        ]
        cells.sort(
            key=lambda position: len(
                current_state.candidates[position[0]][position[1]]
            )
        )

        if max_candidates_per_round is not None:
            cells = cells[:max_candidates_per_round]

        for row, column in cells:
            value = int(solution[row, column])
            trial_grid = current_grid.copy()
            trial_grid[row, column] = value

            trial_state, trial_chain, trial_status = (
                solve_with_naked_singles(trial_grid)
            )

            if trial_status == "contradiction":
                continue

            solved_after = int(
                (trial_state.grid != 0).sum()
            )
            propagation_gain = (
                solved_after - solved_before
            )

            candidate_count = len(
                current_state.candidates[row][column]
            )
            peer_count = _unsolved_peer_count(
                current_state,
                row,
                column,
            )

            candidates.append({
                "row": row,
                "column": column,
                "value": value,
                "propagation_gain": propagation_gain,
                "candidate_count": candidate_count,
                "peer_count": peer_count,
                "trial_naked_single_steps": len(
                    trial_chain
                ),
                "trial_solved": (
                    trial_status == "solved"
                ),
            })

        if not candidates:
            raise RuntimeError(
                "Nessun indizio valido disponibile durante "
                "la ricerca greedy."
            )

        chosen = max(
            candidates,
            key=lambda item: (
                item["propagation_gain"],
                item["candidate_count"],
                item["peer_count"],
                -item["row"],
                -item["column"],
            ),
        )

        row = chosen["row"]
        column = chosen["column"]
        value = chosen["value"]

        current_grid[row, column] = value
        added_clues.append((row, column, value))
        greedy_history.append(dict(chosen))

        if verbose:
            print(
                f"Aggiunto R{row + 1}C{column + 1}={value}: "
                f"+{chosen['propagation_gain']} celle risolte, "
                f"{chosen['candidate_count']} candidati iniziali."
            )

    _, _, greedy_status = solve_with_naked_singles(
        current_grid
    )

    prune_checks = 0
    pruning_completed = not prune

    if prune and greedy_status == "solved":
        (   added_clues,
            prune_checks,
            pruning_completed,
        ) = _prune_added_clues(
            original=original,
            added_clues=added_clues,
            greedy_history=greedy_history,
            max_prune_checks=max_prune_checks,
            verbose=verbose,
        )
        
        
    augmented_grid = original.copy()

    for row, column, value in added_clues:
        augmented_grid[row, column] = value

    final_state, final_chain, final_status = (
        solve_with_naked_singles(augmented_grid)
    )

    return {
        "status": final_status,
        "original": original,
        "augmented_grid": augmented_grid,
        "solved_grid": final_state.grid.copy(),
        "added_clues": [
            {
                "row": row,
                "column": column,
                "value": value,
            }
            for row, column, value in added_clues
        ],
        "highlight":{'primary': [(row,column) for row, column, _ in added_clues],
                        'secondary': []},
        "n_added": len(added_clues),
        "naked_single_steps": len(final_chain),
        "naked_single_chain": final_chain,
        "greedy_history": greedy_history,
        "is_inclusion_minimal": bool(
            prune
            and pruning_completed
            and final_status == "solved"
        ),
        "prune_checks": prune_checks,
    }

def grade_difficulty(chain, status):
    """Restituisce le metriche pubbliche dell'analisi."""
    if not chain:
        return {
            "difficulty_model_version": (
                difficulty_model.DIFFICULTY_MODEL_VERSION
            ),
            "technical_difficulty": 0.0,
            "technical_difficulty_label": "N/A",
            "hardest_technique": None,
            "resolution_load": 0.0,
            "resolution_load_label": "N/A",
            "move_discovery_difficulty": 0.0,
            "move_discovery_difficulty_label": "N/A",
            "move_discovery_difficulty_is_upper_bound": False,
            "step_count": 0,
            "nested_step_count": 0,
            "complete_tree_step_count": 0,
        }

    difficulty_scores = [
        float(
            move.get(
                "technical_difficulty",
                _base_difficulty(move),
            )
        )
        for move in chain
    ]
    technical_difficulty = max(difficulty_scores)
    technical_label = (
        difficulty_model.technical_difficulty_label(
            technical_difficulty
        )
    )
    resolution_load = (
        difficulty_model.aggregate_resolution_load(
            difficulty_scores
        )
    )
    resolution_load_label = (
        difficulty_model.resolution_load_label(
            resolution_load
        )
    )
    hardest_index = max(
        range(len(chain)),
        key=lambda index: difficulty_scores[index],
    )
    hardest_technique = chain[hardest_index]["technique"]

    move_discovery_steps = [
        float(
            move.get(
                "move_discovery_difficulty",
                difficulty_model.step_move_discovery_difficulty(
                    effective_move_count=move.get(
                        "effective_move_count",
                        move.get("frontier_move_count", 1),
                    ),
                    max_moves=MAX_MOVES_PER_TECHNIQUE,
                ),
            )
        )
        for move in chain
    ]
    move_discovery_difficulty = (
        difficulty_model
        .aggregate_move_discovery_difficulty(
            move_discovery_steps
        )
    )
    move_discovery_difficulty_label = (
        difficulty_model.move_discovery_label(
            move_discovery_difficulty
        )
    )
    nested_step_count = sum(
        move.get("fallback_tier_used", move.get("fallback_tier")) == 1
        for move in chain
    )
    complete_tree_step_count = sum(
        move.get("fallback_tier_used", move.get("fallback_tier")) == 2
        for move in chain
    )
    move_discovery_is_upper_bound = any(
        bool(move.get("move_discovery_difficulty_is_upper_bound"))
        for move in chain
    )

    return {
        "difficulty_model_version": (
            difficulty_model.DIFFICULTY_MODEL_VERSION
        ),
        "technical_difficulty": technical_difficulty,
        "technical_difficulty_label": (
            technical_label
            if status == "solved"
            else "Non risolto"
        ),
        "hardest_technique": hardest_technique,
        "resolution_load": resolution_load,
        "resolution_load_label": resolution_load_label,
        "move_discovery_difficulty": (
            move_discovery_difficulty
        ),
        "move_discovery_difficulty_label": (
            move_discovery_difficulty_label
        ),
        "move_discovery_difficulty_is_upper_bound": (
            move_discovery_is_upper_bound
        ),
        "step_count": len(chain),
        "nested_step_count": nested_step_count,
        "complete_tree_step_count": complete_tree_step_count,
    }


def analyse_puzzle(
    grid,
    name=None,
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=DEFAULT_PROFILE_DIFFICULTY_WINDOW,
    max_steps=MAX_SOLVER_STEPS,
    verbose=False,
    search_limits="limited",
    cancellation_check=None,
):
    """Valida, risolve, valuta e confeziona l'analisi del puzzle."""
    max_steps = _normalise_solver_step_limit(max_steps)
    analysis_mode = _normalise_analysis_mode(analysis_mode)
    original = sds.SudokuState(grid).grid.copy()
    solution_count = sds.count_solutions(original, limit=2)

    if solution_count == 0:
        raise ValueError("Il Sudoku non ha alcuna soluzione.")

    if solution_count > 1:
        raise ValueError(
            "Il Sudoku deve avere una soluzione unica; "
            "ne esiste piu' di una."
        )

    solved_grid = sds.backtracking_solve(original)
    state, chain, status = solve_and_log(
        grid,
        max_steps=max_steps,
        verbose=verbose,
        analysis_mode=analysis_mode,
        profile_difficulty_window=profile_difficulty_window,
        search_limits=search_limits,
        cancellation_check=cancellation_check,
        uniqueness_status=sds.UNIQUENESS_VERIFIED,
    )
    grading = grade_difficulty(chain, status)

    return {
        "name": name or "puzzle",
        "original": original,
        "solved_grid": solved_grid,
        "unique_solution": True,
        "uniqueness_status": sds.UNIQUENESS_VERIFIED,
        "chain": chain,
        "status": status,
        "grading": grading,
        "analysis_mode": analysis_mode,
        "search_limits_mode": search_config.search_limits(
            search_limits
        ).mode,
        "profile_difficulty_window": (
            float(profile_difficulty_window)
            if analysis_mode in ("smart_profile", "full_profile")
            else None
        ),
    }
