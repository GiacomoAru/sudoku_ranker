'''
## 3. Motore risolutivo

Ad ogni step il motore interroga le tecniche in ordine di difficoltà.
L'analisi `profile`, predefinita con finestra 1.5, si limita a una fascia
configurabile sopra la difficoltà minima; `deep` costruisce invece
l'inventario completo;
`superficial` conserva soltanto la frontiera minima. In ogni modalità la
mossa scelta è la più semplice; il tie-break usa `_TECHNIQUE_ORDER` e,
fra conclusioni equivalenti, le coordinate della forma canonica MinLex.
Anche Sudoku isomorfi seguono così la stessa catena logica nel riferimento
canonico.

`solve_and_log` applica una mossa alla volta e registra ogni step nella
catena, fino a soluzione completa, blocco (nessuna tecnica implementata
trova più nulla) o contraddizione (un candidato azzerato, non dovrebbe mai
succedere su un puzzle valido con solo eliminazioni logicamente corrette).

`grade_difficulty` mantiene separate tre letture: Difficoltà Tecnica (rating
SE invariato), Difficoltà
percepita sulla stessa scala numerica SE. La label usa soltanto il massimo
rating SE; carico cumulativo e scarsità delle mosse restano metriche
indipendenti per il confronto e l'ordinamento.
'''


"""
Solver engine with configurable analysis depth. The default profile mode
scans 1.5 SE points above the minimum difficulty; deep collects the complete
logical inventory and superficial keeps only the minimum frontier. Proofs are
retained as diagnostics, while availability is measured through unique
logical conclusions.
"""

import inspect
import math

from . import canonicalization as sc
from . import data_structure as sds
from . import difficulty as difficulty_model
from . import techniques as st


_TECHNIQUE_RANK = {
    technique: index
    for index, technique in enumerate(st._TECHNIQUE_ORDER)
}


ANALYSIS_MODES = {
    "deep",
    "profile",
    "superficial",
}

ANALYSIS_MODE_ALIASES = {
    "full": "deep",
    "complete": "deep",
    "profilo": "profile",
    "standard": "superficial",
    "shallow": "superficial",
    "superficiale": "superficial",
}

DEFAULT_PROFILE_DIFFICULTY_WINDOW = 1.5
DEFAULT_ANALYSIS_MODE = "profile"
MAX_MOVES_PER_TECHNIQUE = 16

def _difficulty_score(move):
    """Rating canonico usato per scegliere e ordinare le mosse."""
    return float(
        move.get(
            "difficulty",
            difficulty_model.TECHNIQUE_DIFFICULTY.get(
                move["technique"],
                99.0,
            ),
        )
    )


def _technical_difficulty_score(move):
    """
    Restituisce il rating tecnico effettivo mostrato nell'analisi.

    Il rating canonico della mossa resta invariato e continua a governare
    ordinamento, frontiera, pruning e scelta della tecnica. Soltanto le
    Nested Forcing Chain ricevono un incremento moderato basato sulla prova
    concreta conservata in ``logic.metrics``.

    L'incremento cresce in modo logaritmico ed e limitato a un massimo di
    1.0 punti SE, quindi una Nested parte da 9.5 e non supera 10.5.
    """
    base_difficulty = _difficulty_score(move)
    technique = str(move.get("technique", ""))

    if not technique.startswith("Nested "):
        return base_difficulty

    logic = move.get("logic", {}) or {}
    metrics = logic.get("metrics", {}) or {}

    chain_count = max(
        int(metrics.get("chain_count", 0)),
        1,
    )
    node_count = max(
        int(metrics.get("node_count", 0)),
        0,
    )
    max_chain_length = max(
        int(metrics.get("max_chain_length", 0)),
        0,
    )

    secondary_nodes = max(
        0,
        node_count - max_chain_length,
    )

    # Fino a sei nodi la Nested conserva il rating minimo della famiglia.
    length_extra = (
        0.20
        * math.log2(
            1 + max(0, max_chain_length - 6)
        )
    )

    # I nodi fuori dalla catena principale rappresentano rami o sotto-prove.
    branching_extra = (
        0.10
        * math.log2(1 + secondary_nodes)
    )

    # Piu catene aumentano la complessita, ma con rendimento decrescente.
    multiple_chain_extra = (
        0.10
        * math.log2(chain_count)
    )

    total_extra = min(
        1.0,
        length_extra
        + branching_extra
        + multiple_chain_extra,
    )

    return round(
        base_difficulty + total_extra,
        1,
    )


def _tie_rank(move):
    return _TECHNIQUE_RANK.get(
        move["technique"],
        len(_TECHNIQUE_RANK),
    )


def _move_sort_key(move, canonical_transform=None):
    key = (
        _difficulty_score(move),
        _tie_rank(move),
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



def _normalise_analysis_mode(mode):
    """Valida e normalizza il livello di profondita dell inventario."""
    if mode is None:
        return "deep"

    normalised = str(mode).strip().lower()
    normalised = ANALYSIS_MODE_ALIASES.get(normalised, normalised)

    if normalised not in ANALYSIS_MODES:
        allowed = ", ".join(sorted(ANALYSIS_MODES))
        raise ValueError(
            f"Modalita di analisi non valida: {mode!r}. "
            f"Valori ammessi: {allowed}."
        )

    return normalised


def _move_outcome_signature(move):
    """Firma dell intero risultato della mossa, indipendente dalla prova."""
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



def _call_technique_with_limit(
    function,
    state,
    max_results,
):
    """Passa il limite dentro la tecnica quando il runner lo supporta."""
    try:
        parameters = inspect.signature(function).parameters.values()
    except (TypeError, ValueError):
        return function(state)

    supports_keyword = any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        or parameter.name == "max_results"
        for parameter in parameters
    )

    if supports_keyword:
        return function(
            state,
            max_results=max_results,
        )

    return function(state)

def collect_moves_for_analysis(
    state,
    mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=DEFAULT_PROFILE_DIFFICULTY_WINDOW,
    canonical_transform=None,
    max_moves_per_technique=MAX_MOVES_PER_TECHNIQUE,
):
    """
    Raccoglie le mosse secondo la granularita richiesta.

    ``deep``
        Interroga tutte le tecniche e produce un inventario completo.

    ``profile``
        Dopo aver trovato la difficolta minima D, continua a interrogare le
        tecniche che possono produrre mosse fino a D + window.

    ``superficial``
        Cerca soltanto la frontiera minima: si ferma appena le tecniche
        rimanenti non possono piu eguagliare la mossa migliore trovata.

    La modalita cambia soltanto l inventario registrato. La mossa scelta resta
    sempre la piu semplice tra quelle applicabili.
    """
    mode = _normalise_analysis_mode(mode)

    if profile_difficulty_window is None:
        profile_difficulty_window = DEFAULT_PROFILE_DIFFICULTY_WINDOW

    profile_difficulty_window = float(profile_difficulty_window)

    if profile_difficulty_window < 0:
        raise ValueError(
            "profile_difficulty_window deve essere maggiore o uguale a 0."
        )
    if (
        isinstance(max_moves_per_technique, bool)
        or int(max_moves_per_technique) < 1
    ):
        raise ValueError("max_moves_per_technique deve essere positivo.")
    max_moves_per_technique = int(max_moves_per_technique)

    moves = []
    best_diff = None
    scanned_function_count = 0
    stopped_early = False
    stop_before_min_difficulty = None
    capped_techniques = set()

    for min_d, fn in st.TECHNIQUE_FUNCS:
        if best_diff is not None:
            if mode == "superficial":
                difficulty_limit = best_diff
            elif mode == "profile":
                difficulty_limit = (
                    best_diff + profile_difficulty_window
                )
            else:
                difficulty_limit = None

            if (
                difficulty_limit is not None
                and float(min_d) > difficulty_limit
            ):
                stopped_early = True
                stop_before_min_difficulty = float(min_d)
                break

        scanned_function_count += 1
        found = _call_technique_with_limit(
            fn,
            state,
            max_results=max_moves_per_technique,
        )

        if not found:
            continue

        unique = {}
        for move in found:
            signature = (
                move.get("technique"),
                _move_outcome_signature(move),
            )
            unique.setdefault(signature, move)

        ordered = sorted(
            unique.values(),
            key=lambda move: _move_sort_key(
                move,
                canonical_transform,
            ),
        )
        counts = {}
        limited = []
        for move in ordered:
            technique = move.get("technique", "Sconosciuta")
            count = counts.get(technique, 0)
            if count >= max_moves_per_technique:
                capped_techniques.add(technique)
                continue
            counts[technique] = count + 1
            limited.append(move)

        found = limited
        moves.extend(found)
        local_min = min(
            _difficulty_score(move)
            for move in found
        )
        best_diff = (
            local_min
            if best_diff is None
            else min(best_diff, local_min)
        )

    metadata = {
        "mode": mode,
        "profile_difficulty_window": (
            profile_difficulty_window
            if mode == "profile"
            else None
        ),
        "best_difficulty": best_diff,
        "scanned_function_count": scanned_function_count,
        "total_function_count": len(st.TECHNIQUE_FUNCS),
        "stopped_early": stopped_early,
        "complete_inventory": not stopped_early,
        "stop_before_min_difficulty": stop_before_min_difficulty,
        "max_moves_per_technique": max_moves_per_technique,
        "capped_techniques": sorted(capped_techniques),
    }

    return moves, metadata


def collect_all_moves(state, early_stop=True):
    """
    Interfaccia storica mantenuta per compatibilita.

    ``early_stop=True`` equivale a ``superficial``;
    ``early_stop=False`` equivale a ``deep``.
    """
    mode = "superficial" if early_stop else "deep"
    moves, _ = collect_moves_for_analysis(state, mode=mode)
    return moves


def collect_all_moves_full(state):
    """Restituisce l inventario completo di tutte le tecniche applicabili."""
    moves, _ = collect_moves_for_analysis(state, mode="deep")
    return moves



def _effective_nearby_move_count(
    moves,
    best_difficulty,
    max_moves=MAX_MOVES_PER_TECHNIQUE,
):
    """
    Calcola il numero effettivo di mosse accessibili.

    Ogni tecnica ha già prodotto al massimo max_moves esiti.

    Gli esiti distinti vengono ordinati per difficoltà SE.
    Le prime max_moves mosse hanno peso di posizione pieno.
    Le successive continuano a contribuire, ma con peso
    rapidamente decrescente.

    Il contributo dipende anche dalla distanza SE rispetto
    alla mossa più semplice disponibile.
    """
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
    """Riassume soltanto gli esiti distinti utili a rating e heatmap."""
    all_outcomes = set()
    frontier_outcomes = set()
    by_technique = {}
    frontier_by_technique = {}

    for move in moves:
        technique = move.get("technique", "Sconosciuta")
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
                key=lambda item: _TECHNIQUE_RANK.get(
                    item[0],
                    len(_TECHNIQUE_RANK),
                ),
            )
        },
        "frontier_by_technique": {
            technique: len(outcomes)
            for technique, outcomes in sorted(
                frontier_by_technique.items(),
                key=lambda item: _TECHNIQUE_RANK.get(
                    item[0],
                    len(_TECHNIQUE_RANK),
                ),
            )
        },
    }

def apply_move(state, move):
    for r, c, v in move["placements"]:
        state.place(r, c, v)

    for r, c, v in move["eliminations"]:
        state.eliminate(r, c, v)


def solve_and_log(
    grid,
    max_steps=10000,
    verbose=False,
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=DEFAULT_PROFILE_DIFFICULTY_WINDOW,
):
    """
    Risolve il Sudoku e registra l inventario logico di ogni stato.

    ``analysis_mode`` controlla la profondita dell inventario:
    ``profile`` e il default ed esplora una fascia configurabile sopra la
    difficolta minima; ``deep`` interroga tutte le tecniche; ``superficial``
    registra soltanto la frontiera minima.

    Lo stato finale, la mossa scelta e il grading non dipendono dalla modalita:
    cambia solo la quantita di informazione analitica raccolta.
    """
    analysis_mode = _normalise_analysis_mode(analysis_mode)

    state = sds.SudokuState(grid)
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
        )

        if not moves:
            return state, chain, "stuck"

        moves.sort(
            key=lambda move: _move_sort_key(
                move,
                canonical_transform,
            )
        )

        chosen = moves[0]

        # Il rating canonico governa esclusivamente il comportamento del
        # solver. Il rating tecnico effettivo serve soltanto a grading,
        # visualizzazione e carico risolutivo.
        chosen_score = _difficulty_score(chosen)
        technical_score = _technical_difficulty_score(chosen)

        inventory = _build_move_inventory(
            moves,
            best_difficulty=chosen_score,
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
            best_difficulty=chosen_score,
            max_moves=MAX_MOVES_PER_TECHNIQUE,
        )
        
        move_discovery_difficulty = (
            difficulty_model.step_move_discovery_difficulty(
                effective_move_count=effective_move_count,
                max_moves=MAX_MOVES_PER_TECHNIQUE,
            )
        )
        effective_move_count = round(effective_move_count, 2)
        
        resolution_load = (
            difficulty_model.step_resolution_load(
                technical_score
            )
        )

        apply_move(state, chosen)
        step_no += 1

        record = {
            key: chosen[key]
            for key in (
                "technique",
                "family",
                "description",
                "placements",
                "eliminations",
                "highlight",
                "logic",
            )
            if key in chosen
        }
        record["step"] = step_no
        record["grid_after"] = state.grid.copy()
        record["base_difficulty"] = chosen_score
        record["technical_difficulty"] = technical_score
        record["resolution_load"] = resolution_load
        record["move_discovery_difficulty"] = move_discovery_difficulty
        record["available_move_count"] = available_move_count
        record["frontier_move_count"] = frontier_move_count
        record["effective_move_count"] = effective_move_count
        record["available_by_technique"] = inventory[
            "available_by_technique"
        ]
        record["frontier_by_technique"] = inventory[
            "frontier_by_technique"
        ]
        if collection_metadata.get("capped_techniques"):
            record["capped_techniques"] = collection_metadata[
                "capped_techniques"
            ]

        chain.append(record)

        if verbose:
            print(
                f"[{step_no:03d}] "
                f"{chosen['technique']:<30} "
                f"(SE {technical_score:.1f}"
                + (
                    f", base {chosen_score:.1f}"
                    if not math.isclose(
                        technical_score,
                        chosen_score,
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
                f"modo {analysis_mode}) "
                f"{chosen['description']}"
            )

    status = "solved" if state.is_solved() else "stuck"
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

        apply_move(state, chosen)

        record = dict(chosen)
        record["step"] = len(chain) + 1
        record["grid_after"] = state.grid.copy()
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
            "step_count": 0,
        }

    difficulty_scores = [
        float(
            move.get(
                "technical_difficulty",
                difficulty_model.TECHNIQUE_DIFFICULTY.get(
                    move["technique"],
                    99.0,
                ),
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
                        move.get(
                            "frontier_move_count",
                            1,
                        ),
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
        "step_count": len(chain),
    }
    

def analyse_puzzle(
    grid,
    name=None,
    analysis_mode=DEFAULT_ANALYSIS_MODE,
    profile_difficulty_window=DEFAULT_PROFILE_DIFFICULTY_WINDOW,
    max_steps=10000,
    verbose=False,
):
    """
    Risolve, valuta e confeziona l analisi completa del puzzle.

    La modalita predefinita e ``profile`` con finestra 1.5. ``deep`` produce
    l'inventario totale e ``superficial`` conserva soltanto la frontiera,
    senza cambiare la strategia di scelta delle mosse.
    """
    analysis_mode = _normalise_analysis_mode(analysis_mode)
    original = sds.SudokuState(grid).grid.copy()
    solution_count = sds.count_solutions(original, limit=2)
    if solution_count == 0:
        raise ValueError("Il Sudoku non ha alcuna soluzione.")
    if solution_count > 1:
        raise ValueError(
            "Il Sudoku deve avere una soluzione unica; ne esiste più di una."
        )

    solved_grid = sds.backtracking_solve(original)

    state, chain, status = solve_and_log(
        grid,
        max_steps=max_steps,
        verbose=verbose,
        analysis_mode=analysis_mode,
        profile_difficulty_window=profile_difficulty_window,
    )
    grading = grade_difficulty(chain, status)

    return {
        "name": name or "puzzle",
        "original": original,
        "solved_grid": solved_grid,
        "unique_solution": True,
        "chain": chain,
        "status": status,
        "grading": grading,
        "analysis_mode": analysis_mode,
        "profile_difficulty_window": (
            float(profile_difficulty_window)
            if analysis_mode == "profile"
            else None
        ),
    }
