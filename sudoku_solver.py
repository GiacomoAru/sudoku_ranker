'''
## 3. Motore risolutivo

Ad ogni step il motore interroga le tecniche in ordine di difficoltà.
L'analisi `deep`, predefinita, costruisce l'inventario completo; `profile`
si limita a una fascia configurabile sopra la difficoltà minima;
`superficial` conserva soltanto la frontiera minima. In ogni modalità la
mossa scelta è la più semplice e un ordine di tie-break fisso
(`_TECHNIQUE_ORDER`) rende la scelta deterministica.

`solve_and_log` applica una mossa alla volta e registra ogni step nella
catena, fino a soluzione completa, blocco (nessuna tecnica implementata
trova più nulla) o contraddizione (un candidato azzerato, non dovrebbe mai
succedere su un puzzle valido con solo eliminazioni logicamente corrette).

`grade_difficulty` produce sia la difficoltà teorica sia una difficoltà
percepita. La difficoltà percepita assegna a ogni livello tecnico un peso
su una scala logaritmica, quindi un livello intero in più vale circa dieci
volte tanto, e corregge il peso in base al numero di mosse minime disponibili:
poche alternative aumentano il carico, molte lo riducono.
'''


"""
Solver engine with configurable analysis depth. The default deep mode
collects the complete logical inventory, while profile and superficial modes
reduce the scanned difficulty range. Proofs are retained as diagnostics, but
availability is measured primarily through unique logical conclusions.
"""

from collections import defaultdict
import math

import sudoku_data_structure as sds
import sudoku_techniques as st


DIFFICULTY_LABEL = {
    1: "Fondamentale",
    2: "Facile",
    3: "Intermedio",
    4: "Avanzato",
    5: "Esperto",
    6: "Estremo",
    7: "Catene",
    8: "Forcing avanzato",
    9: "Dinamico",
    10: "Nested",
}

DIFFICULTY_WORKLOAD_WEIGHT = {
    1: 0,
    2: 1,
    3: 3,
    4: 8,
    5: 20,
    6: 50,
    7: 125,
    8: 300,
    9: 750,
    10: 1800,
}

# La difficoltà percepita usa una scala per ordini di grandezza:
# L1 = 0.1, L2 = 1, L3 = 10, L4 = 100, L5 = 1000.
# I valori decimali vengono interpolati esponenzialmente.
PERCEIVED_DIFFICULTY_EXPONENT_OFFSET = 2.0

# Quattro mosse minime disponibili rappresentano il caso neutro.
# Con meno alternative il peso aumenta, con più alternative diminuisce.
PERCEIVED_REFERENCE_ALTERNATIVES = 4
PERCEIVED_MIN_SCARCITY_FACTOR = 0.5
PERCEIVED_MAX_SCARCITY_FACTOR = 2.0

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

DEFAULT_PROFILE_DIFFICULTY_WINDOW = 1.0


def _difficulty_score(move):
    """
    Restituisce la difficoltà precisa della tecnica.

    Usa TECHNIQUE_DIFFICULTY come fonte principale e il valore contenuto
    nella mossa solamente come fallback.
    """
    return float(
        st.TECHNIQUE_DIFFICULTY.get(
            move["technique"],
            move.get("difficulty", 99),
        )
    )


def _tie_rank(move):
    return _TECHNIQUE_RANK.get(
        move["technique"],
        len(_TECHNIQUE_RANK),
    )


def _move_sort_key(move):
    return (
        _difficulty_score(move),
        _tie_rank(move),
    )


def _perceived_theoretical_weight(difficulty):
    """
    Converte la difficoltà tecnica in un peso logaritmico.

    Ogni punto intero di difficoltà moltiplica il peso per dieci:
    1 -> 0.1, 2 -> 1, 3 -> 10, 4 -> 100, 5 -> 1000.
    """
    return 10.0 ** (
        float(difficulty) - PERCEIVED_DIFFICULTY_EXPONENT_OFFSET
    )


def _scarcity_factor(n_alternatives):
    """
    Restituisce il moltiplicatore dovuto alla scarsità di mosse.

    Il riferimento neutro è quattro alternative. Il fattore è limitato
    tra 0.5 e 2.0 per evitare che la disponibilità di mosse annulli o
    domini completamente la difficoltà teorica.
    """
    n_alternatives = max(int(n_alternatives), 1)

    factor = math.sqrt(
        PERCEIVED_REFERENCE_ALTERNATIVES / n_alternatives
    )

    return min(
        PERCEIVED_MAX_SCARCITY_FACTOR,
        max(PERCEIVED_MIN_SCARCITY_FACTOR, factor),
    )


def _perceived_step_difficulty(difficulty, n_alternatives):
    """Calcola la difficoltà percepita di un singolo step."""
    theoretical_weight = _perceived_theoretical_weight(difficulty)
    scarcity_factor = _scarcity_factor(n_alternatives)

    return theoretical_weight * scarcity_factor


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


def _move_atomic_conclusions(move):
    """
    Restituisce le conclusioni atomiche prodotte da una mossa.

    Una conclusione e un inserimento oppure l eliminazione di un singolo
    candidato. Prove diverse che raggiungono lo stesso effetto vengono quindi
    contate una sola volta nell inventario analitico.
    """
    conclusions = {
        ("place", int(r), int(c), int(value))
        for r, c, value in move.get("placements", ())
    }
    conclusions.update(
        ("eliminate", int(r), int(c), int(value))
        for r, c, value in move.get("eliminations", ())
    )
    return frozenset(conclusions)


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


def collect_moves_for_analysis(
    state,
    mode="deep",
    profile_difficulty_window=DEFAULT_PROFILE_DIFFICULTY_WINDOW,
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

    moves = []
    best_diff = None
    scanned_function_count = 0
    stopped_early = False
    stop_before_min_difficulty = None

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
        found = fn(state)

        if not found:
            continue

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


def _build_move_inventory(moves, best_difficulty):
    """
    Aggrega prove, risultati distinti e conclusioni atomiche.

    L inventario mantiene due viste dello stesso stato:

    ``scanned``
        Tutto cio che e stato trovato dalla modalita di analisi corrente.

    ``frontier``
        Soltanto le mosse alla difficolta minima, indipendentemente dalla
        profondita con cui e stato esplorato lo stato.

    Per entrambe sono disponibili aggregazioni per tecnica e per famiglia.
    Questo permette alla visualizzazione di scegliere separatamente la
    profondita della heatmap e la granularita delle righe.
    """
    def new_scope():
        return {
            "proofs_by_technique": defaultdict(int),
            "proofs_by_family": defaultdict(int),
            "outcomes_by_technique": defaultdict(set),
            "outcomes_by_family": defaultdict(set),
            "conclusions_by_technique": defaultdict(set),
            "conclusions_by_family": defaultdict(set),
            "all_outcomes": set(),
            "all_conclusions": set(),
        }

    scanned = new_scope()
    frontier = new_scope()

    technique_families = defaultdict(set)
    technique_difficulties = defaultdict(set)
    family_difficulties = defaultdict(set)

    def add_to_scope(scope, technique, family, outcome, conclusions):
        scope["proofs_by_technique"][technique] += 1
        scope["proofs_by_family"][family] += 1

        scope["outcomes_by_technique"][technique].add(outcome)
        scope["outcomes_by_family"][family].add(outcome)
        scope["all_outcomes"].add(outcome)

        scope["conclusions_by_technique"][technique].update(conclusions)
        scope["conclusions_by_family"][family].update(conclusions)
        scope["all_conclusions"].update(conclusions)

    for move in moves:
        technique = move.get("technique", "Sconosciuta")
        family = move.get("family", technique)
        difficulty = _difficulty_score(move)
        outcome = _move_outcome_signature(move)
        conclusions = _move_atomic_conclusions(move)

        technique_families[technique].add(family)
        technique_difficulties[technique].add(difficulty)
        family_difficulties[family].add(difficulty)

        add_to_scope(
            scanned,
            technique,
            family,
            outcome,
            conclusions,
        )

        if math.isclose(
            difficulty,
            best_difficulty,
            rel_tol=0.0,
            abs_tol=1e-9,
        ):
            add_to_scope(
                frontier,
                technique,
                family,
                outcome,
                conclusions,
            )

    def serialise_scope(scope):
        technique_names = sorted(
            scope["proofs_by_technique"],
            key=lambda name: _TECHNIQUE_RANK.get(
                name,
                len(_TECHNIQUE_RANK),
            ),
        )
        family_names = sorted(scope["proofs_by_family"])

        by_technique = {
            technique: {
                "family": sorted(technique_families[technique]),
                "difficulty_min": min(
                    technique_difficulties[technique]
                ),
                "difficulty_max": max(
                    technique_difficulties[technique]
                ),
                "proof_count": scope[
                    "proofs_by_technique"
                ][technique],
                "distinct_outcome_count": len(
                    scope["outcomes_by_technique"][technique]
                ),
                "conclusion_count": len(
                    scope["conclusions_by_technique"][technique]
                ),
            }
            for technique in technique_names
        }

        by_family = {
            family: {
                "difficulty_min": min(family_difficulties[family]),
                "difficulty_max": max(family_difficulties[family]),
                "proof_count": scope["proofs_by_family"][family],
                "distinct_outcome_count": len(
                    scope["outcomes_by_family"][family]
                ),
                "conclusion_count": len(
                    scope["conclusions_by_family"][family]
                ),
            }
            for family in family_names
        }

        return {
            "proof_count": sum(
                scope["proofs_by_technique"].values()
            ),
            "distinct_outcome_count": len(scope["all_outcomes"]),
            "conclusion_count": len(scope["all_conclusions"]),
            "by_technique": by_technique,
            "by_family": by_family,
        }

    scanned_summary = serialise_scope(scanned)
    frontier_summary = serialise_scope(frontier)

    # I campi principali rappresentano tutto l inventario scandito. La
    # vista ``frontier`` contiene invece soltanto la difficolta minima.
    return {
        **scanned_summary,
        "best_distinct_outcome_count": frontier_summary[
            "distinct_outcome_count"
        ],
        "best_conclusion_count": frontier_summary[
            "conclusion_count"
        ],
        "frontier": frontier_summary,
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
    analysis_mode="deep",
    profile_difficulty_window=DEFAULT_PROFILE_DIFFICULTY_WINDOW,
):
    """
    Risolve il Sudoku e registra l inventario logico di ogni stato.

    ``analysis_mode`` controlla la profondita dell inventario:
    ``deep`` e il default e interroga tutte le tecniche; ``profile`` esplora
    una fascia configurabile sopra la difficolta minima; ``superficial``
    registra soltanto la frontiera minima.

    Lo stato finale, la mossa scelta e il grading non dipendono dalla modalita:
    cambia solo la quantita di informazione analitica raccolta.
    """
    analysis_mode = _normalise_analysis_mode(analysis_mode)

    state = sds.SudokuState(grid)
    chain = []
    step_no = 0

    while not state.is_solved() and step_no < max_steps:
        if state.is_stuck():
            return state, chain, "contradiction"

        moves, collection_metadata = collect_moves_for_analysis(
            state,
            mode=analysis_mode,
            profile_difficulty_window=profile_difficulty_window,
        )

        if not moves:
            return state, chain, "stuck"

        moves.sort(key=_move_sort_key)

        chosen = moves[0]
        chosen_score = _difficulty_score(chosen)
        chosen_level = int(chosen_score)

        inventory = _build_move_inventory(
            moves,
            best_difficulty=chosen_score,
        )

        n_conclusions = max(
            int(inventory["conclusion_count"]),
            1,
        )
        n_best_conclusions = max(
            int(inventory["best_conclusion_count"]),
            1,
        )

        theoretical_weight = _perceived_theoretical_weight(chosen_score)
        scarcity_factor = _scarcity_factor(n_best_conclusions)
        perceived_difficulty = (
            theoretical_weight * scarcity_factor
        )

        apply_move(state, chosen)
        step_no += 1

        record = dict(chosen)
        record["step"] = step_no
        record["grid_after"] = state.grid.copy()

        record["analysis_mode"] = analysis_mode
        record["analysis_scope"] = collection_metadata
        record["availability"] = inventory

        # Conteggi principali: ora rappresentano conclusioni uniche, non
        # il numero grezzo di prove enumerate.
        record["n_conclusions"] = n_conclusions
        record["n_best_conclusions"] = n_best_conclusions
        record["n_distinct_outcomes"] = max(
            int(inventory["distinct_outcome_count"]),
            1,
        )
        record["n_best_distinct_outcomes"] = max(
            int(inventory["best_distinct_outcome_count"]),
            1,
        )
        record["n_proofs"] = int(inventory["proof_count"])

        # Alias temporanei per il codice di visualizzazione esistente.
        # Il loro significato e ora documentato come numero di conclusioni.
        record["n_alternatives"] = n_conclusions
        record["n_best_alternatives"] = n_best_conclusions
        record["applicable_by_technique"] = {
            technique: values["conclusion_count"]
            for technique, values in inventory["by_technique"].items()
        }
        record["applicable_by_family"] = {
            family: values["conclusion_count"]
            for family, values in inventory["by_family"].items()
        }
        record["best_applicable_by_technique"] = {
            technique: values["conclusion_count"]
            for technique, values in inventory[
                "frontier"
            ]["by_technique"].items()
        }
        record["best_applicable_by_family"] = {
            family: values["conclusion_count"]
            for family, values in inventory[
                "frontier"
            ]["by_family"].items()
        }
        record["proofs_by_technique"] = {
            technique: values["proof_count"]
            for technique, values in inventory["by_technique"].items()
        }
        record["proofs_by_family"] = {
            family: values["proof_count"]
            for family, values in inventory["by_family"].items()
        }
        record["best_proofs_by_technique"] = {
            technique: values["proof_count"]
            for technique, values in inventory[
                "frontier"
            ]["by_technique"].items()
        }
        record["best_proofs_by_family"] = {
            family: values["proof_count"]
            for family, values in inventory[
                "frontier"
            ]["by_family"].items()
        }
        record["distinct_outcomes_by_technique"] = {
            technique: values["distinct_outcome_count"]
            for technique, values in inventory["by_technique"].items()
        }
        record["distinct_outcomes_by_family"] = {
            family: values["distinct_outcome_count"]
            for family, values in inventory["by_family"].items()
        }

        record["difficulty"] = chosen_score
        record["difficulty_level"] = chosen_level
        record["perceived_theoretical_weight"] = theoretical_weight
        record["scarcity_factor"] = scarcity_factor
        record["perceived_difficulty"] = perceived_difficulty

        chain.append(record)

        if verbose:
            print(
                f"[{step_no:03d}] "
                f"{chosen['technique']:<30} "
                f"(diff {chosen_score:.1f}, "
                f"percepita {perceived_difficulty:.3f}, "
                f"conclusioni minime {n_best_conclusions}, "
                f"prove {inventory['proof_count']}, "
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
        "is_inclusion_minimal": (
            prune and final_status == "solved"
        ),
    }

def grade_difficulty(chain, status):
    """
    Valuta difficoltà teorica, carico di risoluzione e difficoltà percepita.

    `perceived_difficulty` è la somma dei carichi percepiti dei singoli step.
    La scala tecnica è logaritmica e viene corretta in base alla scarsità
    delle mosse minime disponibili.
    """
    if not chain:
        return {
            "label": "N/A",
            "max_difficulty": 0,
            "max_level": 0,
            "score": 0,
            "workload_score": 0,
            "perceived_difficulty": 0.0,
            "average_perceived_difficulty": 0.0,
            "max_perceived_step": 0.0,
            "histogram": {},
            "se_histogram": {},
            "status": status,
            "n_steps": 0,
        }

    difficulty_scores = [
        float(
            move.get(
                "difficulty",
                st.TECHNIQUE_DIFFICULTY.get(
                    move["technique"],
                    99,
                ),
            )
        )
        for move in chain
    ]

    difficulty_levels = [
        int(score)
        for score in difficulty_scores
    ]

    max_difficulty = max(difficulty_scores)
    max_level = int(max_difficulty)

    histogram = {
        level: difficulty_levels.count(level)
        for level in range(1, max(5, max_level) + 1)
    }
    se_histogram = {
        score: difficulty_scores.count(score)
        for score in sorted(set(difficulty_scores))
    }

    hardest_steps = sum(
        score == max_difficulty
        for score in difficulty_scores
    )

    nontrivial_steps = sum(
        level >= 2
        for level in difficulty_levels
    )

    advanced_steps = sum(
        level >= 4
        for level in difficulty_levels
    )

    workload_score = sum(
        DIFFICULTY_WORKLOAD_WEIGHT.get(
            level,
            round(1800 * (2.4 ** (level - 10))),
        )
        for level in difficulty_levels
    )

    perceived_step_scores = []
    for move, score in zip(chain, difficulty_scores):
        perceived_step_scores.append(
            move.get("perceived_difficulty")
            or _perceived_step_difficulty(
                score,
                move.get(
                    "n_best_conclusions",
                    move.get("n_best_alternatives", 1),
                ),
            )
        )

    perceived_difficulty = math.log10(sum(perceived_step_scores) * math.sqrt(len(perceived_step_scores)))
    max_perceived_step = math.log10(max(perceived_step_scores))

    if status == "solved":
        label = DIFFICULTY_LABEL.get(
            max_level,
            "Sconosciuto",
        )
    else:
        label = "Oltre la copertura del solver"

    return {
        "label": label,
        "max_difficulty": max_difficulty,
        "max_level": max_level,

        # Mantenuto per compatibilità con il notebook.
        "score": workload_score,
        "workload_score": workload_score,

        # Nuovi indicatori di difficoltà percepita.
        "perceived_difficulty": perceived_difficulty,
        "max_perceived_step": max_perceived_step,

        "histogram": histogram,
        "se_histogram": se_histogram,
        "status": status,
        "n_steps": len(chain),

        "hardest_steps": hardest_steps,
        "nontrivial_steps": nontrivial_steps,
        "advanced_steps": advanced_steps,
    }


def analyse_puzzle(
    grid,
    name=None,
    analysis_mode="deep",
    profile_difficulty_window=DEFAULT_PROFILE_DIFFICULTY_WINDOW,
    max_steps=10000,
    verbose=False,
):
    """
    Risolve, valuta e confeziona l analisi completa del puzzle.

    La modalita predefinita e ``deep``. ``profile`` e ``superficial`` sono
    disponibili per analisi piu rapide e meno granulari senza cambiare la
    strategia di scelta delle mosse.
    """
    analysis_mode = _normalise_analysis_mode(analysis_mode)
    original = sds.SudokuState(grid).grid.copy()

    state, chain, status = solve_and_log(
        grid,
        max_steps=max_steps,
        verbose=verbose,
        analysis_mode=analysis_mode,
        profile_difficulty_window=profile_difficulty_window,
    )
    grading = grade_difficulty(chain, status)

    bt = sds.backtracking_solve(original)
    verified = bt is not None

    return {
        "name": name or "puzzle",
        "original": original,
        "solved_grid": state.grid.copy(),
        "chain": chain,
        "status": status,
        "grading": grading,
        "analysis_mode": analysis_mode,
        "profile_difficulty_window": (
            float(profile_difficulty_window)
            if analysis_mode == "profile"
            else None
        ),
        "backtracking_verified_solvable": verified,
    }

