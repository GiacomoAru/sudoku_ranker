'''
## 5. Visualizzazione

Le visualizzazioni distinguono sempre tra:

- prove logiche enumerate;
- risultati complessivi distinti;
- conclusioni atomiche uniche.

La misura predefinita e il numero di conclusioni atomiche uniche, per evitare
che tecniche basate su catene dominino i grafici soltanto perche possono
produrre molte prove equivalenti.

`plot_technique_activity` offre quattro viste principali, ottenute combinando:

- profondita `deep` oppure `superficial`;
- vista `extended` per famiglie oppure `compact` per strategie generali.

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
from sudoku_solver import DIFFICULTY_LABEL


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

_HEATMAP_VIEW_ALIASES = {
    "extended": "extended",
    "estesa": "extended",
    "family": "extended",
    "families": "extended",
    "famiglia": "extended",
    "famiglie": "extended",
    "compact": "compact",
    "restricted": "compact",
    "ristretta": "compact",
    "strategy": "compact",
    "strategies": "compact",
    "strategia": "compact",
    "strategie": "compact",
    # Vista aggiuntiva utile per il debug fine. Le quattro combinazioni
    # principali restano deep/superficial x extended/compact.
    "technique": "technique",
    "techniques": "technique",
    "tecnica": "technique",
    "tecniche": "technique",
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
    """Restituisce il numero di conclusioni minime disponibili per step."""
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
    """Estrae i valori di una cella heatmap dallo scope dello step."""
    if view == "technique":
        return {
            name: int(values.get(metric, 0))
            for name, values in scope.get("by_technique", {}).items()
        }

    family_values = {
        name: int(values.get(metric, 0))
        for name, values in scope.get("by_family", {}).items()
    }

    if view == "extended":
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
    if view == "technique":
        return list(_TECHNIQUE_ORDER)
    if view == "extended":
        return list(TECHNIQUE_FAMILY_ORDER)
    return list(TECHNIQUE_STRATEGY_ORDER)


def _view_axis_label(view):
    if view == "technique":
        return "Tecnica"
    if view == "extended":
        return "Famiglia"
    return "Strategia"


def _view_title(view):
    if view == "technique":
        return "tecniche"
    if view == "extended":
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

def plot_difficulty_chain(analysis, figsize=(13, 4.6), show=True):
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

    histogram_values = np.clip(
        np.asarray(difficulties, dtype=float),
        0.0,
        10.0,
    )
    adjusted_values = np.where(
        histogram_values > 0,
        histogram_values - 1e-9,
        histogram_values,
    )

    counts, _, histogram_patches = ax2.hist(
        adjusted_values,
        bins=np.arange(0, 11, 1),
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

    ax2.set_xlim(-0.25, 10.25)
    ax2.set_xticks(
        np.arange(0.5, 10, 1),
        labels=[
            f"SE {value}"
            for value in list(DIFFICULTY_LABEL.keys())
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
                index + 0.5,
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


# ------------------------------------------------------------- main heatmap

def technique_activity_dataframe(
    analysis,
    depth="deep",
    view="extended",
    metric="conclusions",
    show_inactive=False,
):
    """
    Costruisce i dati della heatmap tecnica.

    Le quattro configurazioni principali sono:

    - `depth="deep", view="extended"`: inventario registrato per famiglia;
    - `depth="deep", view="compact"`: inventario registrato per strategia;
    - `depth="superficial", view="extended"`: frontiera minima per famiglia;
    - `depth="superficial", view="compact"`: frontiera minima per strategia.

    `view="technique"` e disponibile come dettaglio diagnostico aggiuntivo.
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
    Mostra l attivita logica lungo l intera risoluzione.

    Parametri principali
    --------------------
    depth:
        `deep` usa tutto l inventario registrato; `superficial` usa soltanto
        le conclusioni alla difficolta minima.
    view:
        `extended` aggrega per famiglia; `compact` aggrega per strategia.
        Le due opzioni, combinate con depth, formano le quattro heatmap
        principali richieste. `technique` aggiunge una vista di debug fine.
    metric:
        `conclusions` e il default. Sono disponibili anche `outcomes` e
        `proofs` per confronto diagnostico.
    scale:
        `log` usa log1p soltanto per il colore; le annotazioni e il dataframe
        mantengono sempre i conteggi reali. Sono disponibili anche `linear`
        e `sqrt`.
    """
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

    row_totals = raw_matrix.sum(axis=1).astype(int)
    if show_totals:
        row_labels = [
            f"{name}  (Σ {total})"
            for name, total in zip(dataframe.index, row_totals)
        ]
    else:
        row_labels = list(dataframe.index)

    ax.set_yticklabels(row_labels, fontsize=9)
    ax.set_xlabel("Step di risoluzione")
    ax.set_ylabel(_view_axis_label(view))

    metric_label = _METRIC_LABELS[metric]
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
                raw_value = int(raw_matrix[row, column])

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
                    str(raw_value),
                    ha="center",
                    va="center",
                    fontsize=7.5,
                    color=text_color,
                )

    colorbar = fig.colorbar(image, ax=ax, pad=0.015)
    colorbar.set_label(_scale_label(scale, metric_label))

    note = _analysis_scope_note(analysis, depth)
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
