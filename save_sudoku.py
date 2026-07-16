import random
import time

import matplotlib.pyplot as plt
import pandas as pd

import sudoku_solver as ss
import sudoku_archive as sa
import sudoku_visualization as sv
import sudoku_generator as sg
i= 0
"""
000 000 000
000 000 000
000 000 000

000 000 000
000 000 000
000 000 000

000 000 000
000 000 000
000 000 000
"""

puzzle = """
870000024003000500600409007010904050020306040090802070400105008007000200180000036
"""
diffculty = 've'
puzzle = sa.parse_sudoku(puzzle)
puzzle_name = f'coach_{diffculty}_{i}'
pr = 'campain'
i+=1

sv.draw_grid(
    puzzle,
    title=puzzle_name,
)
plt.show()


saved_info = sa.save_sudoku(
    puzzle,
    name=puzzle_name,
    metadata={
        "provenienza": pr,
    },
)

