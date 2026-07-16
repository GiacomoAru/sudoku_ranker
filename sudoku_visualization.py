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

from sudoku_techniques import _TECHNIQUE_ORDER

DIFF_COLORS = {
    1: '#8ecae6', 2: '#95d5b2', 3: '#ffd166',
    4: '#f4a261', 5: '#e76f51', 6: '#9d0208',
}
DIFF_LABEL_SHORT = {1: 'L1', 2: 'L2', 3: 'L3', 4: 'L4', 5: 'L5', 6: 'L6'}


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
    """Draw the grid state right after a given step in the chain, with the
    technique's pattern highlighted, plus a caption describing the move."""
    chain = analysis['chain']
    if not chain:
        print("Nessun passaggio registrato (il puzzle era gia risolto o bloccato subito).")
        return
    step_index = max(0, min(step_index, len(chain) - 1))
    move = chain[step_index]

    if step_index == 0:
        grid_before = analysis['original']
    else:
        grid_before = chain[step_index - 1]['grid_after']

    fig, ax = plt.subplots(figsize=figsize)
    draw_grid(grid_before, ax=ax, highlight=move['highlight'])
    caption = (f"Step {move['step']}/{len(chain)} - {move['technique']} "
               f"(difficolta {move['difficulty']})\n{move['description']}")
    ax.text(4.5, 9.55, caption, ha='center', va='top', fontsize=9, wrap=True)
    plt.tight_layout()
    plt.show()


def plot_difficulty_chain(analysis, figsize=(11, 4)):
    """Plot the difficulty level used at every step of the solving chain,
    colored by technique. This is the 'bidimensional' view of the chain:
    x = step number (progress through the solve), y = difficulty of the
    technique needed at that point, color = technique family."""
    chain = analysis['chain']
    if not chain:
        print("Catena vuota: nulla da visualizzare.")
        return

    steps = [m['step'] for m in chain]
    diffs = [m['difficulty'] for m in chain]
    families = [m['family'] for m in chain]
    fam_list = sorted(set(families))
    cmap = plt.get_cmap('tab10')
    fam_color = {f: cmap(i % 10) for i, f in enumerate(fam_list)}
    colors = [fam_color[f] for f in families]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=figsize, gridspec_kw={'width_ratios': [2.4, 1]})

    ax1.scatter(steps, diffs, c=colors, s=45, zorder=3, edgecolor='black', linewidth=0.4)
    ax1.plot(steps, diffs, color='#cccccc', linewidth=1, zorder=1)
    ax1.set_xlabel('Step di risoluzione')
    ax1.set_ylabel('Difficolta della tecnica usata')
    ax1.set_yticks(range(1, 7))
    ax1.set_ylim(0.5, 6.5)
    ax1.set_title(f"Catena logica ({analysis['name']}) - {analysis['grading']['label']}")
    ax1.grid(alpha=0.3)

    handles = [plt.Line2D([0], [0], marker='o', color='w', label=f,
                           markerfacecolor=fam_color[f], markersize=8, markeredgecolor='black')
               for f in fam_list]
    ax1.legend(handles=handles, loc='upper left', fontsize=7, ncol=1,
               bbox_to_anchor=(1.02, 1.0), borderaxespad=0)

    hist = analysis['grading']['histogram']
    levels = list(range(1, 7))
    counts = [hist.get(l, 0) for l in levels]
    bar_colors = [DIFF_COLORS[l] for l in levels]
    ax2.bar([DIFF_LABEL_SHORT[l] for l in levels], counts, color=bar_colors, edgecolor='black')
    ax2.set_title('Passaggi per livello')
    ax2.set_ylabel('Numero di step')

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
            "difficolta_massima": grading["max_difficulty"],
            "livello_massimo": grading.get(
                "max_level",
                int(grading["max_difficulty"]),
            ),
            "punteggio": grading.get(
                "workload_score",
                grading.get("score", 0),
            ),
            "numero_step": grading.get(
                "n_steps",
                len(analysis["chain"]),
            ),
            "step_massimi": grading.get("hardest_steps"),
            "step_non_banali": grading.get("nontrivial_steps"),
            "step_avanzati": grading.get("advanced_steps"),
            "solvibile_verificato": analysis.get(
                "backtracking_verified_solvable"
            ),
        })

    return pd.DataFrame(rows)