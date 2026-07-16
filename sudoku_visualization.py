'''
## 5. Visualizzazione

- `draw_grid`: disegna una griglia 9×9, con evidenziazione opzionale delle
  celle coinvolte in una tecnica (giallo = celle che definiscono il
  pattern, rosso chiaro = celle su cui avviene l'eliminazione/inserimento) e
  possibilità di mostrare i candidati come "pencil marks".
- `draw_step`: mostra lo stato della griglia **subito prima** di un dato
  step della catena, con il pattern di quello step evidenziato e la
  spiegazione testuale sotto forma di didascalia.
- `plot_difficulty_chain`: la vista d'insieme della catena — un grafico a
  dispersione step→difficoltà colorato per famiglia di tecnica, più un
  istogramma dei livelli usati. È la rappresentazione "bidimensionale"
  della difficoltà richiesta: non solo il picco massimo, ma tutto
  l'andamento del ragionamento.
- `gallery`: griglie finali di più puzzle affiancate, con etichetta di
  difficoltà.
- `summary_dataframe`: la catena come tabella pandas, per ispezione o
  esportazione.
'''

"""
Visualization helpers: draw a single grid (optionally highlighting a
technique instance), draw the difficulty chain of a solved puzzle, and lay
out a gallery of several analysed puzzles.
"""
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import numpy as np
import pandas as pd
from matplotlib.ticker import MaxNLocator

from sudoku_techniques import _TECHNIQUE_ORDER

DIFF_COLORS = {
    1: '#8ecae6',
    2: '#95d5b2',
    3: '#ffd166',
    4: '#f4a261',
    5: '#e76f51',
}
DIFF_LABEL_SHORT = {
    1: 'L1',
    2: 'L2',
    3: 'L3',
    4: 'L4',
    5: 'L5',
}


def _same_technique_instances(move):
    """Numero di istanze disponibili della tecnica scelta nello step."""
    return max(
        int(
            move.get(
                "applicable_by_technique",
                {},
            ).get(
                move.get("technique"),
                1,
            )
        ),
        1,
    )


def _comparable_alternatives(chain):
    """
    Restituisce un conteggio di alternative confrontabile tra tutti gli step.

    Se ogni step contiene ``n_best_alternatives``, usa le mosse disponibili
    alla stessa difficoltà minima. Altrimenti usa il numero di istanze della
    tecnica effettivamente scelta.
    """
    use_best_alternatives = all(
        move.get("n_best_alternatives") is not None
        for move in chain
    )

    if use_best_alternatives:
        values = [
            max(int(move["n_best_alternatives"]), 1)
            for move in chain
        ]
        label = "Alternative alla stessa difficoltà"
    else:
        values = [
            _same_technique_instances(move)
            for move in chain
        ]
        label = "Istanze della tecnica scelta"

    return values, label


def draw_grid(grid, ax=None, highlight=None, candidates=None,
              title=None, given_mask=None):
    """Draw one 9x9 sudoku grid.
    highlight: dict with 'primary' / 'secondary' lists of (r,c) cells.
    candidates: optional 9x9 list-of-sets, drawn as small pencil marks in
        empty cells (used for close-up "what did the engine see" views).
    given_mask: optional 9x9 bool array; True cells are drawn bold (the
        puzzle's original clues) vs. thin (cells solved by the engine).
    """
    own_fig = ax is None
    if ax is None:
        fig, ax = plt.subplots(figsize=(4.2, 4.2))

    grid = np.array(grid)
    highlight = highlight or {}
    primary = set(highlight.get('primary', []))
    secondary = set(highlight.get('secondary', [])) - primary

    ax.set_xlim(0, 9)
    ax.set_ylim(0, 9)
    ax.set_aspect('equal')
    ax.invert_yaxis()
    ax.set_xticks([])
    ax.set_yticks([])

    for (r, c) in primary:
        ax.add_patch(patches.Rectangle((c, r), 1, 1, facecolor='#ffe28a', zorder=0))
    for (r, c) in secondary:
        ax.add_patch(patches.Rectangle((c, r), 1, 1, facecolor='#ffc2c2', zorder=0))

    for i in range(10):
        lw = 2.2 if i % 3 == 0 else 0.6
        ax.axhline(i, color='black', linewidth=lw, zorder=2)
        ax.axvline(i, color='black', linewidth=lw, zorder=2)

    for r in range(9):
        for c in range(9):
            v = grid[r, c]
            if v != 0:
                bold = given_mask is None or given_mask[r, c]
                ax.text(c + 0.5, r + 0.62, str(v), ha='center', va='center',
                         fontsize=16, fontweight='bold' if bold else 'normal',
                         color='black' if bold else '#1d3557', zorder=3)
            elif candidates is not None:
                cand = sorted(candidates[r][c])
                for v in cand:
                    cx = c + 0.18 + ((v - 1) % 3) * 0.32
                    cy = r + 0.22 + ((v - 1) // 3) * 0.28
                    ax.text(cx, cy, str(v), ha='center', va='center',
                            fontsize=6, color='#555555', zorder=3)

    if title:
        ax.set_title(title, fontsize=11)
    if own_fig:
        plt.tight_layout()
    return ax


def draw_step(analysis, step_index, figsize=(5.2, 5.2)):
    """Mostra la griglia prima dello step e le alternative disponibili."""
    chain = analysis["chain"]

    if not chain:
        print(
            "Nessun passaggio registrato "
            "(il puzzle era gia risolto o bloccato subito)."
        )
        return

    step_index = max(0, min(step_index, len(chain) - 1))
    move = chain[step_index]

    if step_index == 0:
        grid_before = analysis["original"]
    else:
        grid_before = chain[step_index - 1]["grid_after"]

    technique_instances = _same_technique_instances(move)
    other_technique_instances = max(technique_instances - 1, 0)

    alternatives_text = (
        f"Altre istanze della stessa tecnica: "
        f"{other_technique_instances}"
    )

    if move.get("n_best_alternatives") is not None:
        other_best_alternatives = max(
            int(move["n_best_alternatives"]) - 1,
            0,
        )
        alternatives_text += (
            f" | Altre mosse alla stessa difficoltà: "
            f"{other_best_alternatives}"
        )

    fig, ax = plt.subplots(figsize=figsize)
    draw_grid(
        grid_before,
        ax=ax,
        highlight=move["highlight"],
    )

    caption = (
        f"Step {move['step']}/{len(chain)} - "
        f"{move['technique']} "
        f"(difficolta {move['difficulty']})\n"
        f"{alternatives_text}\n"
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
    plt.show()


def plot_difficulty_chain(analysis, figsize=(12, 4.6)):
    """
    Mostra l'andamento della difficoltà e le alternative disponibili.

    Il colore dei punti identifica la famiglia della tecnica. La linea sul
    secondo asse mostra quante alternative comparabili erano disponibili:
    preferibilmente quelle alla stessa difficoltà minima, oppure, come
    fallback, le istanze della tecnica scelta.
    """
    chain = analysis["chain"]

    if not chain:
        print("Catena vuota: nulla da visualizzare.")
        return

    steps = [move["step"] for move in chain]
    diffs = [float(move["difficulty"]) for move in chain]
    families = [move["family"] for move in chain]

    alternative_counts, alternative_label = _comparable_alternatives(
        chain
    )

    family_list = sorted(set(families))
    cmap = plt.get_cmap("tab10")
    family_color = {
        family: cmap(index % 10)
        for index, family in enumerate(family_list)
    }
    point_colors = [
        family_color[family]
        for family in families
    ]

    fig, (ax1, ax2) = plt.subplots(
        1,
        2,
        figsize=figsize,
        gridspec_kw={"width_ratios": [2.6, 1]},
    )

    ax1.plot(
        steps,
        diffs,
        linewidth=0.9,
        alpha=0.45,
        zorder=1,
    )
    ax1.scatter(
        steps,
        diffs,
        c=point_colors,
        s=30,
        zorder=3,
        edgecolor="black",
        linewidth=0.35,
    )

    ax1.set_xlabel("Step di risoluzione")
    ax1.set_ylabel("Difficoltà della tecnica usata")
    difficulty_ticks = np.arange(1.0, 5.01, 0.5)

    ax1.set_yticks(difficulty_ticks)
    ax1.set_ylim(0.75, 5.25)
    ax1.set_title(
        f"Catena logica ({analysis['name']}) - "
        f"{analysis['grading']['label']}"
    )
    ax1.grid(
        axis="both",
        alpha=0.22,
        linewidth=0.7,
    )

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
    alternative_top = max(alternative_counts) + 1
    alternative_axis.set_ylim(
        (18 - alternative_top) / 17,
        alternative_top,
    )
    alternative_axis.yaxis.set_major_locator(
        MaxNLocator(integer=True)
    )

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

    # Nove barre fisse: L1, L1.5, ..., L5.
    difficulty_values = np.arange(1.0, 5.01, 0.5)

    # Assegna ogni difficoltà al mezzo punto più vicino.
    rounded_diffs = [
        round(difficulty * 2) / 2
        for difficulty in diffs
    ]

    counts = [
        sum(
            np.isclose(value, difficulty)
            for value in rounded_diffs
        )
        for difficulty in difficulty_values
    ]

    labels = [
        f"L{difficulty:g}"
        for difficulty in difficulty_values
    ]

    histogram_cmap = plt.get_cmap("YlOrRd")
    bar_colors = [
        histogram_cmap(
            np.clip(
                (difficulty - 1.0) / 4.0,
                0.0,
                1.0,
            )
        )
        for difficulty in difficulty_values
    ]

    ax2.bar(
        difficulty_values,
        counts,
        width=0.38,
        color=bar_colors,
        edgecolor="black",
        linewidth=0.6,
    )

    ax2.set_xticks(difficulty_values)
    ax2.set_xticklabels(
        labels,
        rotation=45,
        ha="right",
    )

    ax2.set_xlim(0.7, 5.3)
    ax2.set_title("Passaggi per difficoltà")
    ax2.set_xlabel("Difficoltà")
    ax2.set_ylabel("Numero di step")

    ax2.yaxis.set_major_locator(
        MaxNLocator(integer=True)
    )

    ax2.grid(
        axis="y",
        alpha=0.22,
        linewidth=0.7,
    )

    ax2.set_axisbelow(True)
    ax2.tick_params(
        axis="x",
        labelrotation=45,
    )

    plt.tight_layout()
    plt.show()


def gallery(analyses, 
            solved=False,
            ncols=3, 
            figsize_per_cell=(3.4, 4.0)):
    """Show the solved grid of several analysed puzzles side by side, with
    their difficulty label."""
    n = len(analyses)
    ncols = min(ncols, n) if n > 0 else 1
    nrows = int(np.ceil(n / ncols))
    fig, axes = plt.subplots(nrows, ncols,
                              figsize=(figsize_per_cell[0] * ncols, figsize_per_cell[1] * nrows))
    axes = np.array(axes).reshape(-1)

    for i, res in enumerate(analyses):
        ax = axes[i]
        given_mask = res['original'] != 0
        if solved:
            draw_grid(res['solved_grid'], ax=ax, given_mask=given_mask)
        else:
            draw_grid(res['original'], ax=ax, given_mask=given_mask)
        g = res['grading']
        subtitle = f"{res['name']}\n{g['label']} (max L{g['max_difficulty']}, {g.get('n_steps', 0)} step)"
        ax.set_title(subtitle, fontsize=9)

    for j in range(n, len(axes)):
        axes[j].axis('off')

    plt.tight_layout()
    plt.show()


def summary_dataframe(analysis):
    rows = []
    for m in analysis['chain']:
        rows.append({
            'step': m['step'], 'tecnica': m['technique'], 'famiglia': m['family'],
            'difficolta': m['difficulty'], 'n_alternative': m['n_alternatives'],
            'descrizione': m['description'],
        })
    return pd.DataFrame(rows)


def plot_technique_activity(
    analysis,
    show_inactive=False,
    annotate=True,
    figsize=None,
):
    """
    Mostra quante istanze di ogni tecnica erano applicabili a ogni step.

    Righe: tecniche.
    Colonne: step della risoluzione.
    Valori: numero di mosse applicabili.
    """
    chain = analysis["chain"]

    if not chain:
        print("Catena vuota: nessuna attività da visualizzare.")
        return

    techniques = list(_TECHNIQUE_ORDER)

    if not show_inactive:
        techniques = [
            technique
            for technique in techniques
            if any(
                step.get("applicable_by_technique", {}).get(
                    technique, 0
                ) > 0
                for step in chain
            )
        ]

    matrix = np.array([
        [
            step.get("applicable_by_technique", {}).get(
                technique, 0
            )
            for step in chain
        ]
        for technique in techniques
    ])

    if figsize is None:
        width = max(8, len(chain) * 0.35)
        height = max(4, len(techniques) * 0.45)
        figsize = (width, height)

    fig, ax = plt.subplots(figsize=figsize)

    image = ax.imshow(
        matrix,
        aspect="auto",
        interpolation="nearest",
    )

    ax.set_xticks(range(len(chain)))
    ax.set_xticklabels(
        [step["step"] for step in chain],
        fontsize=8,
    )

    ax.set_yticks(range(len(techniques)))
    ax.set_yticklabels(techniques)

    ax.set_xlabel("Step di risoluzione")
    ax.set_ylabel("Tecnica")
    ax.set_title(
        f"Attività delle tecniche: {analysis['name']}"
    )

    if annotate:
        for row in range(matrix.shape[0]):
            for column in range(matrix.shape[1]):
                value = matrix[row, column]

                if value > 0:
                    ax.text(
                        column,
                        row,
                        str(value),
                        ha="center",
                        va="center",
                        fontsize=8,
                    )

    colorbar = fig.colorbar(image, ax=ax)
    colorbar.set_label("Numero di applicazioni disponibili")

    plt.tight_layout()
    plt.show()
    
    
def analyses_summary_dataframe(analyses):
    """Crea il riepilogo sintetico di una lista di analisi Sudoku."""
    rows = []

    for analysis in analyses:
        grading = analysis["grading"]

        rows.append({
            "nome": analysis["name"],
            "stato": analysis["status"],
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
            "numero_step": grading.get(
                "n_steps",
                len(analysis["chain"]),
            ),
            "step_non_banali": grading.get(
                "nontrivial_steps"
            ),
            "step_avanzati": grading.get(
                "advanced_steps"
            ),
            "solvibile_verificato": analysis.get(
                "backtracking_verified_solvable"
            ),
        })

    return pd.DataFrame(rows)
