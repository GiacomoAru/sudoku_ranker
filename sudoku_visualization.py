'''
## 5. Visualizzazione

Le visualizzazioni distinguono sempre tra:

- prove logiche enumerate;
- risultati complessivi distinti;
- conclusioni atomiche uniche.

La misura predefinita e il numero di conclusioni atomiche uniche, per evitare
che tecniche basate su catene dominino i grafici soltanto perche possono
produrre molte prove equivalenti.

`plot_technique_activity` offre tre granularita, combinabili con la
profondita `deep` oppure `superficial`:

- vista `compact` per strategie generali;
- vista `family` per famiglie logiche;
- vista `extended` per ogni singola tecnica.

La vista deep usa tutto l inventario registrato nello step. La vista
superficial usa soltanto la frontiera alla difficolta minima. La modalita di
analisi con cui e stato creato il risultato resta comunque vincolante: una
analisi `profile` o `superficial` non contiene un inventario deep completo.
'''

from __future__ import annotations

from collections import defaultdict
import math

import matplotlib.patches as patches
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

from sudoku_techniques import (
    TECHNIQUE_FAMILY,
    TECHNIQUE_FAMILY_ORDER,
    TECHNIQUE_STRATEGY,
    TECHNIQUE_STRATEGY_ORDER,
    _TECHNIQUE_ORDER,
    technique_family,
    technique_strategy,
)


DIFF_COLORS = {
    1: "#8ecae6",
    2: "#95d5b2",
    3: "#ffd166",
    4: "#f4a261",
    5: "#e76f51",
}

DIFF_LABEL_SHORT = {
    1: "L1",
    2: "L2",
    3: "L3",
    4: "L4",
    5: "L5",
}


_HEATMAP_DEPTH_ALIASES = {
    "deep": "deep",
    "full": "deep",
    "complete": "deep",
    "completa": "deep",
    "profonda": "deep",
    "superficial": "superficial",
    "shallow": "superficial",
    "frontier": "superficial",
    "frontiera": "superficial",
    "superficiale": "superficial",
}

# Schema pubblico delle viste della heatmap:
# compact  = strategie generali
# family   = famiglie logiche
# extended = singole tecniche
HEATMAP_VIEW_SCHEMA_VERSION = 2

_HEATMAP_VIEW_ALIASES = {
    # Vista estesa: una riga per ogni singola tecnica specifica.
    "extended": "extended",
    "estesa": "extended",
    "technique": "extended",
    "techniques": "extended",
    "tecnica": "extended",
    "tecniche": "extended",

    # Vista per famiglie: una riga per ogni famiglia logica.
    "family": "family",
    "families": "family",
    "famiglia": "family",
    "famiglie": "family",

    # Vista compatta: una riga per ogni strategia generale.
    "compact": "compact",
    "restricted": "compact",
    "ristretta": "compact",
    "strategy": "compact",
    "strategies": "compact",
    "strategia": "compact",
    "strategie": "compact",
}

_HEATMAP_METRIC_ALIASES = {
    "conclusion": "conclusion_count",
    "conclusions": "conclusion_count",
    "conclusione": "conclusion_count",
    "conclusioni": "conclusion_count",
    "conclusion_count": "conclusion_count",
    "outcome": "distinct_outcome_count",
    "outcomes": "distinct_outcome_count",
    "risultato": "distinct_outcome_count",
    "risultati": "distinct_outcome_count",
    "distinct_outcome_count": "distinct_outcome_count",
    "proof": "proof_count",
    "proofs": "proof_count",
    "prova": "proof_count",
    "prove": "proof_count",
    "proof_count": "proof_count",
}

_HEATMAP_SCALE_ALIASES = {
    "linear": "linear",
    "lineare": "linear",
    "log": "log",
    "logarithmic": "log",
    "logaritmica": "log",
    "sqrt": "sqrt",
    "square_root": "sqrt",
    "radice": "sqrt",
}

_METRIC_LABELS = {
    "conclusion_count": "Conclusioni uniche",
    "distinct_outcome_count": "Risultati distinti",
    "proof_count": "Prove enumerate",
}


# ---------------------------------------------------------------- utilities

def _normalise_choice(value, aliases, parameter_name):
    key = str(value).strip().lower()
    if key not in aliases:
        allowed = ", ".join(sorted(set(aliases.values())))
        raise ValueError(
            f"{parameter_name} non valido: {value!r}. "
            f"Valori ammessi: {allowed}."
        )
    return aliases[key]


def _normalise_heatmap_depth(depth):
    return _normalise_choice(
        depth,
        _HEATMAP_DEPTH_ALIASES,
        "depth",
    )


def _normalise_heatmap_view(view):
    return _normalise_choice(
        view,
        _HEATMAP_VIEW_ALIASES,
        "view",
    )


def _normalise_heatmap_metric(metric):
    return _normalise_choice(
        metric,
        _HEATMAP_METRIC_ALIASES,
        "metric",
    )


def _normalise_heatmap_scale(scale):
    return _normalise_choice(
        scale,
        _HEATMAP_SCALE_ALIASES,
        "scale",
    )


def _ordered_names(active_names, canonical_order, show_inactive=False):
    active_names = set(active_names)

    ordered = [
        name
        for name in canonical_order
        if show_inactive or name in active_names
    ]

    extras = sorted(active_names - set(canonical_order))
    ordered.extend(extras)
    return ordered


def _normalise_analyses(value):
    """Normalizza un'analisi o una collezione ordinata di analisi."""
    is_collection = isinstance(value, (list, tuple))
    analyses = list(value) if is_collection else [value]

    if any(not isinstance(analysis, dict) for analysis in analyses):
        raise TypeError(
            "Ogni analisi deve essere un dizionario prodotto dal solver."
        )

    return analyses, is_collection


def _positive_step_value(move, primary, *fallbacks):
    for key in (primary, *fallbacks):
        value = move.get(key)
        if value is not None:
            return max(int(value), 1)
    return 1


def _difficulty_histogram_levels(difficulties):
    """
    Arrotonda i rating SE al livello intero più vicino.

    Le soglie cadono sui mezzi punti: [1.0, 1.5) appartiene a SE 1,
    [1.5, 2.5) a SE 2 e così via. I valori estremi restano nei livelli 1-10.
    """
    values = np.asarray(difficulties, dtype=float)
    levels = np.floor(values + 0.5).astype(int)
    return np.clip(levels, 1, 10)


def _same_technique_conclusions(move):
    """Numero di conclusioni attribuite alla tecnica scelta nello step."""
    availability = move.get("availability", {})
    technique = move.get("technique")

    entry = availability.get("by_technique", {}).get(technique)
    if entry is not None:
        return max(int(entry.get("conclusion_count", 0)), 1)

    return max(
        int(
            move.get("applicable_by_technique", {}).get(
                technique,
                1,
            )
        ),
        1,
    )


def _comparable_alternatives(chain):
    """Restituisce la numerosità minima più significativa disponibile."""
    if all(
        move.get("n_best_distinct_outcomes") is not None
        for move in chain
    ):
        values = [
            max(int(move["n_best_distinct_outcomes"]), 1)
            for move in chain
        ]
        return values, "Risultati distinti alla difficoltà minima"

    if all(move.get("n_best_conclusions") is not None for move in chain):
        values = [
            max(int(move["n_best_conclusions"]), 1)
            for move in chain
        ]
        return values, "Conclusioni uniche alla difficoltà minima"

    if all(move.get("n_best_alternatives") is not None for move in chain):
        values = [
            max(int(move["n_best_alternatives"]), 1)
            for move in chain
        ]
        return values, "Alternative alla stessa difficoltà"

    values = [_same_technique_conclusions(move) for move in chain]
    return values, "Conclusioni della tecnica scelta"


def aggregate_difficulty_chain(analyses):
    """
    Aggrega catene di lunghezza diversa per indice di step.

    Ogni media allo step ``k`` usa soltanto i puzzle la cui catena contiene
    quello step. ``coverage`` rende esplicita la quota ancora attiva. Il
    risultato contiene dataframe per andamento e istogramma più un riepilogo.
    """
    analyses, _ = _normalise_analyses(analyses)
    chains = [
        analysis.get("chain", [])
        for analysis in analyses
        if analysis.get("chain")
    ]

    if not chains:
        return {
            "steps": pd.DataFrame(),
            "histogram": pd.DataFrame(),
            "summary": {
                "analysis_count": 0,
                "mean_steps": 0.0,
                "std_steps": 0.0,
            },
        }

    analysis_count = len(chains)
    chain_lengths = np.asarray([len(chain) for chain in chains], dtype=float)
    step_rows = []

    for step_index in range(int(chain_lengths.max())):
        active_moves = [
            chain[step_index]
            for chain in chains
            if len(chain) > step_index
        ]
        difficulties = np.asarray([
            float(move["difficulty"])
            for move in active_moves
        ])
        best_outcomes = np.asarray([
            _positive_step_value(
                move,
                "n_best_distinct_outcomes",
                "n_best_conclusions",
                "n_best_alternatives",
            )
            for move in active_moves
        ], dtype=float)
        best_conclusions = np.asarray([
            _positive_step_value(
                move,
                "n_best_conclusions",
                "n_best_alternatives",
            )
            for move in active_moves
        ], dtype=float)
        all_outcomes = np.asarray([
            _positive_step_value(
                move,
                "n_distinct_outcomes",
                "n_conclusions",
                "n_alternatives",
            )
            for move in active_moves
        ], dtype=float)

        step_rows.append({
            "step": step_index + 1,
            "puzzle_count": len(active_moves),
            "coverage": len(active_moves) / analysis_count,
            "mean_difficulty": float(difficulties.mean()),
            "std_difficulty": float(difficulties.std()),
            "median_difficulty": float(np.median(difficulties)),
            "mean_best_distinct_outcomes": float(best_outcomes.mean()),
            "mean_best_conclusions": float(best_conclusions.mean()),
            "mean_distinct_outcomes": float(all_outcomes.mean()),
        })

    per_puzzle_histograms = []
    for chain in chains:
        levels = _difficulty_histogram_levels([
            float(move["difficulty"])
            for move in chain
        ])
        per_puzzle_histograms.append(
            np.asarray([
                int(np.count_nonzero(levels == level))
                for level in range(1, 11)
            ], dtype=float)
        )

    histogram_matrix = np.vstack(per_puzzle_histograms)
    histogram = pd.DataFrame({
        "difficulty_level": np.arange(1, 11),
        "mean_steps": histogram_matrix.mean(axis=0),
        "std_steps": histogram_matrix.std(axis=0),
        "total_steps": histogram_matrix.sum(axis=0).astype(int),
        "puzzle_count": np.count_nonzero(
            histogram_matrix,
            axis=0,
        ),
    })

    max_difficulties = np.asarray([
        max(float(move["difficulty"]) for move in chain)
        for chain in chains
    ])
    labels = [
        analysis.get("grading", {}).get("label", "N/A")
        for analysis in analyses
        if analysis.get("chain")
    ]
    label_counts = {
        label: labels.count(label)
        for label in sorted(set(labels))
    }

    return {
        "steps": pd.DataFrame(step_rows),
        "histogram": histogram,
        "summary": {
            "analysis_count": analysis_count,
            "mean_steps": float(chain_lengths.mean()),
            "std_steps": float(chain_lengths.std()),
            "min_steps": int(chain_lengths.min()),
            "max_steps": int(chain_lengths.max()),
            "mean_max_difficulty": float(max_difficulties.mean()),
            "label_counts": label_counts,
        },
    }


def _family_to_strategy_map():
    mapping = {}

    for technique, family in TECHNIQUE_FAMILY.items():
        strategy = TECHNIQUE_STRATEGY.get(
            technique,
            technique_strategy(technique, family),
        )
        mapping.setdefault(family, strategy)

    return mapping


_FAMILY_TO_STRATEGY = _family_to_strategy_map()


def _scope_for_step(step, depth):
    """Restituisce lo scope di inventario richiesto per uno step."""
    availability = step.get("availability")

    if availability:
        if depth == "superficial":
            return availability.get("frontier", {})
        return availability

    # Compatibilita con analisi precedenti al nuovo inventario.
    if depth == "superficial":
        by_technique = step.get(
            "best_applicable_by_technique",
            step.get("applicable_by_technique", {}),
        )
        by_family = step.get(
            "best_applicable_by_family",
            step.get("applicable_by_family", {}),
        )
    else:
        by_technique = step.get("applicable_by_technique", {})
        by_family = step.get("applicable_by_family", {})

    return {
        "by_technique": {
            name: {"conclusion_count": int(value)}
            for name, value in by_technique.items()
        },
        "by_family": {
            name: {"conclusion_count": int(value)}
            for name, value in by_family.items()
        },
    }


def _scope_values(scope, view, metric):
    """Estrae i valori usando la granularita richiesta.

    ``extended`` legge direttamente ``by_technique``;
    ``family`` legge direttamente ``by_family``;
    ``compact`` aggrega le famiglie nella strategia generale corrispondente.
    """
    if view == "extended":
        return {
            name: int(values.get(metric, 0))
            for name, values in scope.get("by_technique", {}).items()
        }

    family_values = {
        name: int(values.get(metric, 0))
        for name, values in scope.get("by_family", {}).items()
    }

    if view == "family":
        return family_values

    # La vista compact somma le famiglie appartenenti alla stessa strategia.
    # Con il solo inventario serializzato non e possibile ricostruire
    # l unione esatta delle conclusioni condivise fra famiglie. La somma e
    # quindi una misura di attivita della strategia, non un nuovo conteggio
    # globale deduplicato fra tutte le sue famiglie.
    strategy_values = defaultdict(int)

    for family, value in family_values.items():
        strategy = _FAMILY_TO_STRATEGY.get(family, "Altro")
        strategy_values[strategy] += int(value)

    return dict(strategy_values)


def _view_order(view):
    if view == "extended":
        return list(_TECHNIQUE_ORDER)
    if view == "family":
        return list(TECHNIQUE_FAMILY_ORDER)
    return list(TECHNIQUE_STRATEGY_ORDER)


def _view_axis_label(view):
    if view == "extended":
        return "Tecnica"
    if view == "family":
        return "Famiglia"
    return "Strategia"


def _view_title(view):
    if view == "extended":
        return "tecniche"
    if view == "family":
        return "famiglie"
    return "strategie"


def _depth_title(depth):
    return "profonda" if depth == "deep" else "superficiale"


def _transform_heatmap_values(matrix, scale):
    matrix = np.asarray(matrix, dtype=float)

    if scale == "linear":
        return matrix
    if scale == "sqrt":
        return np.sqrt(matrix)
    return np.log1p(matrix)


def _scale_label(scale, metric_label):
    if scale == "linear":
        return metric_label
    if scale == "sqrt":
        return f"sqrt({metric_label.lower()})"
    return f"log1p({metric_label.lower()})"


def _analysis_scope_note(analysis, depth):
    if depth != "deep":
        return None

    analysis_mode = analysis.get("analysis_mode", "legacy")
    if analysis_mode == "deep":
        return None

    if analysis_mode == "profile":
        window = analysis.get("profile_difficulty_window")
        return (
            "L analisi sorgente e profile"
            + (f" (+{window:g} SE)" if window is not None else "")
            + ": la vista profonda mostra tutto l inventario registrato, "
              "non tutte le tecniche esistenti."
        )

    return (
        "L analisi sorgente e superficial: la vista profonda coincide con "
        "l inventario limitato registrato dal solver."
    )


# --------------------------------------------------------------- grid views

def draw_grid(
    grid,
    ax=None,
    highlight=None,
    candidates=None,
    title=None,
    given_mask=None,
):
    """Disegna una griglia Sudoku 9x9."""
    own_fig = ax is None

    if ax is None:
        _, ax = plt.subplots(figsize=(4.2, 4.2))

    grid = np.asarray(grid)
    highlight = highlight or {}
    primary = set(highlight.get("primary", []))
    secondary = set(highlight.get("secondary", [])) - primary

    ax.set_xlim(0, 9)
    ax.set_ylim(0, 9)
    ax.set_aspect("equal")
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_yticks([])

    for r, c in primary:
        ax.add_patch(
            patches.Rectangle(
                (c, r),
                1,
                1,
                facecolor="#ffe28a",
                zorder=0,
            )
        )

    for r, c in secondary:
        ax.add_patch(
            patches.Rectangle(
                (c, r),
                1,
                1,
                facecolor="#ffc2c2",
                zorder=0,
            )
        )

    for index in range(10):
        linewidth = 2.2 if index % 3 == 0 else 0.6
        ax.axhline(index, color="black", linewidth=linewidth, zorder=2)
        ax.axvline(index, color="black", linewidth=linewidth, zorder=2)

    for row in range(9):
        for column in range(9):
            value = grid[row, column]

            if value != 0:
                bold = given_mask is None or given_mask[row, column]
                ax.text(
                    column + 0.5,
                    row + 0.62,
                    str(value),
                    ha="center",
                    va="center",
                    fontsize=16,
                    fontweight="bold" if bold else "normal",
                    color="black" if bold else "#1d3557",
                    zorder=3,
                )
            elif candidates is not None:
                for candidate in sorted(candidates[row][column]):
                    x = column + 0.18 + ((candidate - 1) % 3) * 0.32
                    y = row + 0.22 + ((candidate - 1) // 3) * 0.28
                    ax.text(
                        x,
                        y,
                        str(candidate),
                        ha="center",
                        va="center",
                        fontsize=6,
                        color="#555555",
                        zorder=3,
                    )

    if title:
        ax.set_title(title, fontsize=11)

    if own_fig:
        plt.tight_layout()

    return ax


def draw_step(analysis, step_index, figsize=(5.4, 5.4), show=True):
    """Mostra lo stato precedente allo step e i dati di disponibilita."""
    chain = analysis["chain"]

    if not chain:
        print(
            "Nessun passaggio registrato "
            "(il puzzle era gia risolto o bloccato subito)."
        )
        return None

    step_index = max(0, min(int(step_index), len(chain) - 1))
    move = chain[step_index]

    grid_before = (
        analysis["original"]
        if step_index == 0
        else chain[step_index - 1]["grid_after"]
    )

    same_technique = _same_technique_conclusions(move)
    best_conclusions = max(
        int(
            move.get(
                "n_best_conclusions",
                move.get("n_best_alternatives", 1),
            )
        ),
        1,
    )
    total_conclusions = max(
        int(
            move.get(
                "n_conclusions",
                move.get("n_alternatives", 1),
            )
        ),
        1,
    )
    proofs = move.get("n_proofs")

    availability_text = (
        f"Conclusioni della tecnica: {same_technique} | "
        f"alla difficoltà minima: {best_conclusions} | "
        f"nell inventario: {total_conclusions}"
    )

    if proofs is not None:
        availability_text += f" | prove consolidate: {int(proofs)}"

    fig, ax = plt.subplots(figsize=figsize)
    draw_grid(
        grid_before,
        ax=ax,
        highlight=move.get("highlight"),
    )

    caption = (
        f"Step {move['step']}/{len(chain)} - "
        f"{move['technique']} "
        f"(SE {float(move['difficulty']):g})\n"
        f"{availability_text}\n"
        f"{move['description']}"
    )

    ax.text(
        4.5,
        9.55,
        caption,
        ha="center",
        va="top",
        fontsize=9,
        wrap=True,
    )

    plt.tight_layout()

    if show:
        plt.show()

    return fig, ax


# --------------------------------------------------------- difficulty chain

def _plot_difficulty_chain_single(analysis, figsize=(13, 4.6), show=True):
    """Mostra difficolta usata e conclusioni minime disponibili per step."""
    chain = analysis["chain"]

    if not chain:
        print("Catena vuota: nulla da visualizzare.")
        return None

    steps = [move["step"] for move in chain]
    difficulties = [float(move["difficulty"]) for move in chain]
    families = [
        move.get("family") or technique_family(move["technique"])
        for move in chain
    ]

    alternative_counts, alternative_label = _comparable_alternatives(chain)

    family_list = sorted(set(families))
    cmap = plt.get_cmap("tab10")
    family_color = {
        family: cmap(index % 10)
        for index, family in enumerate(family_list)
    }
    point_colors = [family_color[family] for family in families]

    fig, (ax1, ax2) = plt.subplots(
        1,
        2,
        figsize=figsize,
        gridspec_kw={"width_ratios": [2, 1]},
    )

    ax1.plot(
        steps,
        difficulties,
        linewidth=0.9,
        alpha=0.45,
        zorder=1,
    )
    ax1.scatter(
        steps,
        difficulties,
        c=point_colors,
        s=30,
        zorder=3,
        edgecolor="black",
        linewidth=0.35,
    )

    ax1.set_xlabel("Step di risoluzione")
    ax1.set_ylabel("Difficoltà della tecnica usata")

    difficulty_ticks = sorted(set(difficulties))
    difficulty_top = max(5.0, max(difficulty_ticks))
    ax1.set_yticks(difficulty_ticks)
    ax1.set_yticklabels(
        [f"SE {value:g}" for value in difficulty_ticks]
    )
    ax1.set_ylim(0.75, difficulty_top + 0.25)

    grading = analysis.get("grading", {})
    ax1.set_title(
        f"Catena logica ({analysis.get('name', 'puzzle')}) - "
        f"{grading.get('label', 'non classificato')}"
    )
    ax1.grid(axis="both", alpha=0.22, linewidth=0.7)

    alternative_axis = ax1.twinx()
    alternative_line, = alternative_axis.plot(
        steps,
        alternative_counts,
        marker=".",
        markersize=4,
        linewidth=1,
        alpha=0.55,
        zorder=2,
        label=alternative_label,
    )
    alternative_axis.fill_between(
        steps,
        alternative_counts,
        0,
        alpha=0.05,
    )
    alternative_axis.set_ylabel(alternative_label)
    alternative_axis.set_ylim(0, max(alternative_counts) + 1)
    alternative_axis.yaxis.set_major_locator(MaxNLocator(integer=True))

    family_handles = [
        plt.Line2D(
            [0],
            [0],
            marker="o",
            color="w",
            label=family,
            markerfacecolor=family_color[family],
            markersize=7,
            markeredgecolor="black",
        )
        for family in family_list
    ]

    family_legend = ax1.legend(
        handles=family_handles,
        loc="upper left",
        fontsize=7,
        ncol=1,
        frameon=True,
    )
    ax1.add_artist(family_legend)
    alternative_axis.legend(
        handles=[alternative_line],
        loc="upper right",
        fontsize=7,
        frameon=True,
    )

    histogram_levels = _difficulty_histogram_levels(difficulties)

    counts, _, histogram_patches = ax2.hist(
        histogram_levels,
        bins=np.arange(0.5, 11.5, 1),
        edgecolor="black",
        linewidth=0.6,
    )

    histogram_cmap = plt.get_cmap("YlOrRd")
    for bin_index, patch in enumerate(histogram_patches):
        bin_difficulty = bin_index + 1
        patch.set_facecolor(
            histogram_cmap(
                np.clip(
                    (bin_difficulty - 1.0)
                    / max(difficulty_top - 1.0, 1.0),
                    0.0,
                    1.0,
                )
            )
        )

    ax2.set_xlim(0.5, 10.5)
    ax2.set_xticks(
        np.arange(1, 11, 1),
        labels=[
            f"SE {value}"  for value in list(range(1,11))
        ],
        rotation=45,
        ha="right",
    )
    ax2.set_title("Passaggi per difficoltà")
    ax2.set_xlabel("Difficoltà SE")
    ax2.set_ylabel("Numero di step")
    ax2.yaxis.set_major_locator(MaxNLocator(integer=True))
    ax2.grid(axis="y", alpha=0.22, linewidth=0.7)
    ax2.set_axisbelow(True)

    for index, count in enumerate(counts):
        if count > 0:
            ax2.text(
                index + 1,
                count,
                str(int(count)),
                ha="center",
                va="bottom",
                fontsize=8,
            )

    plt.tight_layout()

    if show:
        plt.show()

    return fig, (ax1, ax2, alternative_axis)


def _plot_difficulty_chain_aggregate(
    analyses,
    figsize=(14.5, 5.0),
    show=True,
):
    """Disegna il riepilogo medio di più catene logiche."""
    aggregate = aggregate_difficulty_chain(analyses)
    steps_frame = aggregate["steps"]
    histogram = aggregate["histogram"]
    summary = aggregate["summary"]

    if steps_frame.empty:
        print("Nessuna catena disponibile nella lista.")
        return None

    steps = steps_frame["step"].to_numpy(dtype=int)
    mean_difficulty = steps_frame[
        "mean_difficulty"
    ].to_numpy(dtype=float)
    std_difficulty = steps_frame[
        "std_difficulty"
    ].to_numpy(dtype=float)
    mean_best_outcomes = steps_frame[
        "mean_best_distinct_outcomes"
    ].to_numpy(dtype=float)
    mean_best_conclusions = steps_frame[
        "mean_best_conclusions"
    ].to_numpy(dtype=float)

    fig, (ax1, ax2) = plt.subplots(
        1,
        2,
        figsize=figsize,
        gridspec_kw={"width_ratios": [2.15, 1]},
    )

    ax1.plot(
        steps,
        mean_difficulty,
        color="#1d3557",
        linewidth=1.8,
        marker="o",
        markersize=3.5,
        label="Difficoltà media",
        zorder=3,
    )
    ax1.fill_between(
        steps,
        np.maximum(mean_difficulty - std_difficulty, 0),
        mean_difficulty + std_difficulty,
        color="#457b9d",
        alpha=0.18,
        label="± 1 deviazione standard",
        zorder=1,
    )
    ax1.set_xlabel("Step di risoluzione")
    ax1.set_ylabel("Difficoltà SE media")
    ax1.xaxis.set_major_locator(MaxNLocator(integer=True))
    ax1.grid(axis="both", alpha=0.22, linewidth=0.7)

    alternative_axis = ax1.twinx()
    alternative_axis.plot(
        steps,
        mean_best_outcomes,
        color="#e76f51",
        linewidth=1.35,
        label="Risultati distinti minimi medi",
    )
    alternative_axis.plot(
        steps,
        mean_best_conclusions,
        color="#2a9d8f",
        linewidth=1.1,
        linestyle="--",
        label="Conclusioni minime medie",
    )
    alternative_axis.set_ylabel("Numerosità media alla difficoltà minima")
    alternative_axis.set_ylim(
        0,
        max(
            float(mean_best_outcomes.max()),
            float(mean_best_conclusions.max()),
        ) * 1.12 + 0.2,
    )

    handles_left, labels_left = ax1.get_legend_handles_labels()
    handles_right, labels_right = (
        alternative_axis.get_legend_handles_labels()
    )
    ax1.legend(
        handles_left + handles_right,
        labels_left + labels_right,
        loc="upper left",
        fontsize=8,
        frameon=True,
    )

    title = (
        f"Catena media di {summary['analysis_count']} puzzle — "
        f"{summary['mean_steps']:.1f} ± {summary['std_steps']:.1f} step, "
        f"max SE medio {summary['mean_max_difficulty']:.2f}"
    )
    ax1.set_title(title)

    levels = histogram["difficulty_level"].to_numpy(dtype=int)
    mean_steps = histogram["mean_steps"].to_numpy(dtype=float)
    std_steps = histogram["std_steps"].to_numpy(dtype=float)
    bars = ax2.bar(
        levels,
        mean_steps,
        yerr=std_steps,
        capsize=2.5,
        color=plt.get_cmap("YlOrRd")(
            np.linspace(0.2, 0.92, len(levels))
        ),
        edgecolor="black",
        linewidth=0.55,
    )
    ax2.set_xticks(levels, [f"SE {level}" for level in levels], rotation=45)
    ax2.set_xlabel("Livello di difficoltà")
    ax2.set_ylabel("Numero medio di step per puzzle")
    ax2.set_title("Istogramma medio della catena")
    ax2.grid(axis="y", alpha=0.22, linewidth=0.7)
    ax2.set_axisbelow(True)

    for bar, value in zip(bars, mean_steps):
        if value > 0:
            ax2.text(
                bar.get_x() + bar.get_width() / 2,
                bar.get_height(),
                f"{value:.1f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    final_coverage = float(steps_frame.iloc[-1]["coverage"])
    fig.text(
        0.5,
        0.006,
        "Le medie allo step k usano soltanto i puzzle ancora attivi; "
        f"copertura all'ultimo step: {final_coverage:.1%}.",
        ha="center",
        va="bottom",
        fontsize=8,
    )
    plt.tight_layout(rect=(0, 0.035, 1, 1))

    if show:
        plt.show()

    return fig, (ax1, ax2, alternative_axis)


def plot_difficulty_chain(analysis, figsize=None, show=True):
    """
    Visualizza una catena singola oppure il riepilogo medio di una lista.

    Per una lista, le medie sono allineate per numero di step e calcolate sui
    puzzle ancora attivi. I dati numerici sono ottenibili separatamente con
    :func:`aggregate_difficulty_chain`.
    """
    _, is_collection = _normalise_analyses(analysis)

    if is_collection:
        return _plot_difficulty_chain_aggregate(
            analysis,
            figsize=figsize or (14.5, 5.0),
            show=show,
        )

    return _plot_difficulty_chain_single(
        analysis,
        figsize=figsize or (13, 4.6),
        show=show,
    )


# ------------------------------------------------------------- main heatmap

def _single_technique_activity_dataframe(
    analysis,
    depth="deep",
    view="extended",
    metric="conclusions",
    show_inactive=False,
):
    """
    Costruisce la matrice numerica usata dalla heatmap.

    Significato esatto di ``view``
    --------------------------------
    ``compact``
        Raggruppa l'attivita nelle poche strategie generali definite da
        ``TECHNIQUE_STRATEGY_ORDER``. Ogni riga rappresenta una strategia,
        per esempio "Catene statiche" o "Forcing dinamici".

    ``family``
        Raggruppa l'attivita nelle famiglie logiche definite da
        ``TECHNIQUE_FAMILY_ORDER``. Ogni riga rappresenta una famiglia,
        per esempio "Fish", "Wings" o "Cicli bidirezionali".

    ``extended``
        Non aggrega le tecniche. Ogni riga rappresenta una singola voce di
        ``_TECHNIQUE_ORDER``, per esempio "X-Wing", "XY-Chain" o "Nishio".

    ``depth="deep"`` usa tutto l'inventario registrato nello step;
    ``depth="superficial"`` usa soltanto la frontiera alla difficolta minima.

    Gli alias ``technique``, ``techniques``, ``tecnica`` e ``tecniche``
    indicano tutti la vista ``extended``.
    """
    depth = _normalise_heatmap_depth(depth)
    view = _normalise_heatmap_view(view)
    metric = _normalise_heatmap_metric(metric)

    chain = analysis.get("chain", [])
    if not chain:
        return pd.DataFrame()

    step_values = []
    active_names = set()

    for step in chain:
        scope = _scope_for_step(step, depth)
        values = _scope_values(scope, view, metric)
        step_values.append(values)
        active_names.update(
            name for name, value in values.items() if value > 0
        )

    names = _ordered_names(
        active_names,
        _view_order(view),
        show_inactive=show_inactive,
    )

    if not names:
        return pd.DataFrame(
            columns=[step.get("step", index + 1) for index, step in enumerate(chain)]
        )

    matrix = [
        [values.get(name, 0) for values in step_values]
        for name in names
    ]

    columns = [
        step.get("step", index + 1)
        for index, step in enumerate(chain)
    ]

    dataframe = pd.DataFrame(
        matrix,
        index=pd.Index(names, name=_view_axis_label(view)),
        columns=pd.Index(columns, name="Step"),
        dtype=int,
    )

    dataframe.attrs.update({
        "depth": depth,
        "view": view,
        "metric": metric,
        "analysis_mode": analysis.get("analysis_mode"),
        "scope_note": _analysis_scope_note(analysis, depth),
    })

    return dataframe


def aggregate_technique_activity_dataframe(
    analyses,
    depth="deep",
    view="extended",
    metric="conclusions",
    show_inactive=False,
):
    """
    Media l'attività logica di più puzzle, allineandola per indice di step.

    Allo step ``k`` il denominatore contiene soltanto le catene che arrivano
    almeno a ``k``. Una tecnica assente in un puzzle ancora attivo vale zero.
    """
    analyses, _ = _normalise_analyses(analyses)
    depth = _normalise_heatmap_depth(depth)
    view = _normalise_heatmap_view(view)
    metric = _normalise_heatmap_metric(metric)
    entries = []
    active_names = set()

    for analysis in analyses:
        chain = analysis.get("chain", [])
        if not chain:
            continue

        dataframe = _single_technique_activity_dataframe(
            analysis,
            depth=depth,
            view=view,
            metric=metric,
            show_inactive=show_inactive,
        )
        entries.append((analysis, dataframe, len(chain)))
        active_names.update(dataframe.index)

    if not entries:
        return pd.DataFrame()

    names = _ordered_names(
        active_names,
        _view_order(view),
        show_inactive=show_inactive,
    )
    max_steps = max(length for _, _, length in entries)
    active_counts = []
    matrix = np.zeros((len(names), max_steps), dtype=float)

    for step_index in range(max_steps):
        active_entries = [
            (dataframe, length)
            for _, dataframe, length in entries
            if length > step_index
        ]
        active_counts.append(len(active_entries))

        if not active_entries:
            continue

        for row_index, name in enumerate(names):
            values = []

            for dataframe, _ in active_entries:
                if (
                    name in dataframe.index
                    and step_index < dataframe.shape[1]
                ):
                    values.append(float(dataframe.iloc[
                        dataframe.index.get_loc(name),
                        step_index,
                    ]))
                else:
                    values.append(0.0)

            matrix[row_index, step_index] = float(np.mean(values))

    notes = sorted({
        note
        for analysis, _, _ in entries
        for note in [_analysis_scope_note(analysis, depth)]
        if note
    })
    dataframe = pd.DataFrame(
        matrix,
        index=pd.Index(names, name=_view_axis_label(view)),
        columns=pd.Index(range(1, max_steps + 1), name="Step"),
        dtype=float,
    )
    dataframe.attrs.update({
        "depth": depth,
        "view": view,
        "metric": metric,
        "aggregate": True,
        "aggregation": "mean_active_puzzles",
        "analysis_count": len(entries),
        "active_puzzle_count": active_counts,
        "analysis_modes": sorted({
            str(analysis.get("analysis_mode", "legacy"))
            for analysis, _, _ in entries
        }),
        "scope_note": (
            "Una o più analisi sorgente hanno inventario limitato. "
            "La media usa tutto ciò che è stato registrato in ciascuna."
            if notes
            else None
        ),
    })
    return dataframe


def technique_activity_dataframe(
    analysis,
    depth="deep",
    view="extended",
    metric="conclusions",
    show_inactive=False,
):
    """Costruisce la heatmap numerica per un'analisi o una lista."""
    _, is_collection = _normalise_analyses(analysis)

    if is_collection:
        return aggregate_technique_activity_dataframe(
            analysis,
            depth=depth,
            view=view,
            metric=metric,
            show_inactive=show_inactive,
        )

    return _single_technique_activity_dataframe(
        analysis,
        depth=depth,
        view=view,
        metric=metric,
        show_inactive=show_inactive,
    )


def plot_technique_activity(
    analysis,
    depth="deep",
    view="extended",
    metric="conclusions",
    scale="log",
    show_inactive=False,
    annotate="auto",
    show_totals=True,
    figsize=None,
    cmap="viridis",
    show=True,
):
    """
    Visualizza l'attività logica di un puzzle o la media di una lista.

    PARAMETRO ``view``
    ==================
    ``view="compact"``
        Vista piu sintetica. Le righe sono STRATEGIE GENERALI. Tecniche e
        famiglie affini vengono sommate nella stessa riga.

    ``view="family"``
        Vista intermedia. Le righe sono FAMIGLIE LOGICHE. Le singole tecniche
        appartenenti alla stessa famiglia vengono aggregate.

    ``view="extended"``
        Vista piu dettagliata. Le righe sono SINGOLE TECNICHE. Non viene
        applicata alcuna aggregazione tassonomica.

    In breve::

        compact  -> strategie
        family   -> famiglie
        extended -> tecniche

    PARAMETRO ``depth``
    ===================
    ``depth="deep"`` usa tutto l'inventario disponibile nello step.
    ``depth="superficial"`` usa solo le conclusioni alla difficolta minima.

    Le tre view possono essere combinate con entrambe le profondita, per un
    totale di sei visualizzazioni.

    PARAMETRO ``metric``
    ====================
    ``conclusions`` conta le conclusioni atomiche uniche ed e la metrica
    consigliata. ``outcomes`` conta gli esiti complessivi distinti.
    ``proofs`` conta le prove enumerate dal motore.

    ``scale`` modifica soltanto il colore della heatmap. Le annotazioni e il
    dataframe restituito mantengono sempre i conteggi reali. Sono disponibili
    ``log``, ``sqrt`` e ``linear``.

    ``technique`` e ``techniques`` restano alias compatibili di
    ``extended``.

    Per una lista, ogni cella è la media sui puzzle ancora attivi allo step
    corrispondente. Il dataframe restituito espone la numerosità campionaria
    per colonna in ``attrs["active_puzzle_count"]``.
    """
    _, is_collection = _normalise_analyses(analysis)
    depth = _normalise_heatmap_depth(depth)
    view = _normalise_heatmap_view(view)
    metric = _normalise_heatmap_metric(metric)
    scale = _normalise_heatmap_scale(scale)

    dataframe = technique_activity_dataframe(
        analysis,
        depth=depth,
        view=view,
        metric=metric,
        show_inactive=show_inactive,
    )

    if dataframe.empty:
        print("Catena vuota o nessuna attività disponibile da visualizzare.")
        return None

    raw_matrix = dataframe.to_numpy(dtype=float)
    display_matrix = _transform_heatmap_values(raw_matrix, scale)

    row_count, column_count = raw_matrix.shape

    if annotate == "auto":
        annotate_enabled = row_count * column_count <= 450
    elif isinstance(annotate, str):
        key = annotate.strip().lower()
        if key in {"true", "yes", "si", "sì", "on"}:
            annotate_enabled = True
        elif key in {"false", "no", "off"}:
            annotate_enabled = False
        else:
            raise ValueError(
                "annotate deve essere True, False oppure 'auto'."
            )
    else:
        annotate_enabled = bool(annotate)

    if figsize is None:
        width = max(9.0, min(24.0, 3.5 + column_count * 0.38))
        height = max(3.8, min(20.0, 1.8 + row_count * 0.48))
        figsize = (width, height)

    fig, ax = plt.subplots(figsize=figsize)

    image = ax.imshow(
        display_matrix,
        aspect="auto",
        interpolation="nearest",
        cmap=cmap,
    )

    ax.set_xticks(range(column_count))
    ax.set_xticklabels(dataframe.columns, fontsize=8)
    ax.set_yticks(range(row_count))

    row_totals = raw_matrix.sum(axis=1)
    if show_totals:
        if is_collection:
            row_labels = [
                f"{name}  (Σμ {total:.1f})"
                for name, total in zip(dataframe.index, row_totals)
            ]
        else:
            row_labels = [
                f"{name}  (Σ {int(total)})"
                for name, total in zip(dataframe.index, row_totals)
            ]
    else:
        row_labels = list(dataframe.index)

    ax.set_yticklabels(row_labels, fontsize=9)
    ax.set_xlabel("Step di risoluzione")
    ax.set_ylabel(_view_axis_label(view))

    metric_label = _METRIC_LABELS[metric]
    if is_collection:
        title = (
            f"Attività logica media {_depth_title(depth)} per "
            f"{_view_title(view)} — "
            f"{dataframe.attrs.get('analysis_count', 0)} puzzle\n"
            f"Valore medio: {metric_label.lower()} | "
            f"scala colore: {scale}"
        )
    else:
        title = (
            f"Attività logica {_depth_title(depth)} per "
            f"{_view_title(view)}: {analysis.get('name', 'puzzle')}\n"
            f"Valore: {metric_label.lower()} | scala colore: {scale}"
        )
    ax.set_title(title)

    if column_count > 35:
        for label in ax.get_xticklabels():
            label.set_rotation(90)
            label.set_ha("center")

    if annotate_enabled:
        max_display = float(display_matrix.max()) if display_matrix.size else 0.0

        for row in range(row_count):
            for column in range(column_count):
                raw_value = float(raw_matrix[row, column])

                if raw_value <= 0:
                    continue

                transformed_value = float(display_matrix[row, column])
                text_color = (
                    "white"
                    if max_display > 0 and transformed_value > max_display * 0.55
                    else "black"
                )

                ax.text(
                    column,
                    row,
                    (
                        f"{raw_value:.1f}"
                        if is_collection
                        else str(int(raw_value))
                    ),
                    ha="center",
                    va="center",
                    fontsize=7.5,
                    color=text_color,
                )

    colorbar = fig.colorbar(image, ax=ax, pad=0.015)
    colorbar_label = _scale_label(scale, metric_label)
    if is_collection:
        colorbar_label = f"Media: {colorbar_label.lower()}"
    colorbar.set_label(colorbar_label)

    note = dataframe.attrs.get("scope_note")
    if note:
        fig.text(
            0.5,
            0.005,
            note,
            ha="center",
            va="bottom",
            fontsize=8,
        )

    plt.tight_layout(rect=(0, 0.035 if note else 0, 1, 1))

    if show:
        plt.show()

    return fig, ax, dataframe


# ---------------------------------------------------------- galleries/tables

def gallery(
    analyses,
    solved=False,
    ncols=3,
    figsize_per_cell=(3.4, 4.0),
    show=True,
):
    """Mostra piu puzzle affiancati con il rispettivo grading."""
    count = len(analyses)
    ncols = min(ncols, count) if count > 0 else 1
    nrows = int(np.ceil(count / ncols)) if count > 0 else 1

    fig, axes = plt.subplots(
        nrows,
        ncols,
        figsize=(
            figsize_per_cell[0] * ncols,
            figsize_per_cell[1] * nrows,
        ),
    )
    axes = np.asarray(axes).reshape(-1)

    for index, analysis in enumerate(analyses):
        ax = axes[index]
        given_mask = analysis["original"] != 0
        grid = (
            analysis["solved_grid"]
            if solved
            else analysis["original"]
        )
        draw_grid(grid, ax=ax, given_mask=given_mask)

        grading = analysis["grading"]
        subtitle = (
            f"{analysis['name']}\n"
            f"{grading['label']} "
            f"(max SE {grading['max_difficulty']}, "
            f"{grading.get('n_steps', 0)} step)"
        )
        ax.set_title(subtitle, fontsize=9)

    for index in range(count, len(axes)):
        axes[index].axis("off")

    plt.tight_layout()

    if show:
        plt.show()

    return fig, axes


def summary_dataframe(analysis):
    """Restituisce la catena con i nuovi conteggi analitici."""
    rows = []

    for move in analysis["chain"]:
        family = move.get("family") or technique_family(move["technique"])
        strategy = move.get("strategy") or technique_strategy(
            move["technique"],
            family,
        )

        rows.append({
            "step": move["step"],
            "tecnica": move["technique"],
            "famiglia": family,
            "strategia": strategy,
            "difficolta": move["difficulty"],
            "conclusioni": move.get(
                "n_conclusions",
                move.get("n_alternatives"),
            ),
            "conclusioni_minime": move.get(
                "n_best_conclusions",
                move.get("n_best_alternatives"),
            ),
            "risultati_distinti": move.get("n_distinct_outcomes"),
            "prove": move.get("n_proofs"),
            "modalita_analisi": move.get(
                "analysis_mode",
                analysis.get("analysis_mode"),
            ),
            "descrizione": move["description"],
        })

    return pd.DataFrame(rows)


def analyses_summary_dataframe(analyses):
    """Crea il riepilogo sintetico di una lista di analisi Sudoku."""
    rows = []

    for analysis in analyses:
        grading = analysis["grading"]
        chain = analysis.get("chain", [])

        rows.append({
            "nome": analysis["name"],
            "stato": analysis["status"],
            "modalita_analisi": analysis.get("analysis_mode", "legacy"),
            "finestra_profile": analysis.get("profile_difficulty_window"),
            "difficolta": grading["label"],
            "difficolta_tecnica": grading.get(
                "technique_label",
                grading["label"],
            ),
            "punteggio_classificazione": grading.get(
                "classification_score",
                grading["max_difficulty"],
            ),
            "carico": grading.get(
                "workload_score",
                grading.get("score", 0),
            ),
            "difficolta_percepita": grading.get(
                "perceived_difficulty",
                0,
            ),
            "difficolta_massima": grading["max_difficulty"],
            "numero_step": grading.get("n_steps", len(chain)),
            "conclusioni_totali_osservate": sum(
                int(step.get("n_conclusions", 0))
                for step in chain
            ),
            "prove_totali_osservate": sum(
                int(step.get("n_proofs", 0))
                for step in chain
            ),
            "step_non_banali": grading.get("nontrivial_steps"),
            "step_avanzati": grading.get("advanced_steps"),
            "solvibile_verificato": analysis.get(
                "backtracking_verified_solvable"
            ),
            "id": analysis.get("puzzle_id"),
        })

    return pd.DataFrame(rows)
