# Bowman's Bingo
As of May 2026 this has been completely replaced with a new algorithm.

It is a property of Forcing Nets that the selection of certain candidates, whether they are ON or OFF - if the consequences are followed through - all other candidates might eventually be linked. If this is possible and there are no un-coloured ambiguous candidates AND there are no contradictions - then the whole board will have been solved in one fell swoop. Each unsolved cell will have one positive ON candidate left.

The reason this strategy is "last resort" is that finding such a candidate is very difficult and for the hardest puzzles, perhaps not present at all until more cells are solved. Also, hand tracing all the links to ensure the criteria is achieved is almost impossible for cluttered boards. For mostly solved boards you can do this but often simpler strategies are preferable.

Before May 2026 I had a very weak version of Bowman's Bingo and the page for this is here. It could occasionally find a candidate to turn off but it was never a positive assertion about the whole board. I labelled the old Bowmans 'trial an error' for being so difficult. But this new version is one hundred percent deterministic and logical. The solver will show all the links and it can be justified, so it does not cross the line in my opinion.

: Load Example or : From the StartLet's take a look at one. This puzzle does not need Bowman's - the next strategy is a W-Wing. But I wanted to start with a puzzle board that isn't too cluttered. To follow along you will need to untick almost all the strategies before "last resort". (Note: Strong links are no longer shown beyond the start candidate).

If found, the solver will highlight the whole board as the eliminations are universal. All the pink coloured candidates are to be removed. It does not do this immediately, however. There is an "Accept?" button in the description box. Use that to remove the candidates and "take step" will show a completed puzzle.

The description also shows the start position - in this case +9[A5]. The solver checks all candidates with a positive assertion, that is it sets them ON and sees if that gives a whole board result. The solver will also put the page into edit mode "chained" and automatically hits the right candidate as if you had manually searched for it. You can try different candidates if you are curious.

I'd like to credit the work of the man behind the dxSudoku Channel for this improvement, particularly the video #103 Improved Bowman's Bingo Puzzle-Solving Technique which is a great resource for truly understanding the technique.

# Aligned Pair Exclusion
This is an interesting strategy, known by the short-hand as APE and sometimes called Subset Exclusion. It can overlap with Y-Wings, XYZ-Wings and WXYZ-Wings but uses very different logic. The overlap is not strict so they are worth looking out for in a tough situation.

There is always a base pair of cells (which now show up as grey cell on the solver). At least one elimination will occur in one of those two cells. The solver will also show a variety of colored cells which are the elements used to make an elimination. I used to distinguish between APE type 1 which only used bi-value cells and type 2 which used 2-cell Almost Locked Sets (ALSs). But the solver will now find a larger variety including 3-cell ALSs and since these merely extend the same logic the solver will return the first of any it finds. A better Type 1 and Type 2 distinction is between the base pair of cells which can be a locked pair (ie can see each other) or not (can't see each other). The logic is subtly different but I'll come to this in the following examples.

Aligned Pair Exclusion - Type 1
APE example 1<br>(requires Y-Wing unchecked)
APE example 1
(requires Y-Wing unchecked) : Load Example or : From the Start

The Aligned Pair Exclusion can be succinctly stated: Any two cells that can see each other CANNOT contain a pair of numbers that will empty a cell in an Almost Locked Set they both entirely see.

Remember - a bi-value cell (with two candidates) is the simplest Almost Locked Set since it is a set of size '1' with size+1 (ie two) candidates.

Let's consider the simplest possible example - two bi-value cell attacking the pair. I have also shown the Y-Wing in the diagram so we can see there is a simpler way to do the same job - but only in some cases.

We consider ALL the possible pairs of numbers that will fit in [G2/G3]. These are for G2 and G3:

2 and 2 (impossible)
2 and 5
2 and 8
4 and 2
4 and 5
4 and 8

Apart from the first being impossible (2 and 2) since G2 and G3 can see each other, we have problems with some of the other combinations. What if 2 and 8 were tried as the solutions? Well, that would duplicate and therefore empty G9. Also 4 and 8 would empty H1.
We are left with a set of combinations that looks like this:

2 and 2 (impossible)
2 and 5
2 and 8 (impossible)
4 and 2
4 and 5
4 and 8 (impossible)

Notice that we now have no 8 left in any pairing? Therefore we can remove 8 from our base pair. Voilà

Credits - Rod Hagglund first popularised this method. (links now dead).

Example 2
APE example 2
APE example 2 : Load Example or : From the Start
The next example has tri-values spread over two pairs of cells as part of the attack. The way we can use double cells is by saying that any two cells with only abc excludes combinations ab, ac and bc from the base pair under consideration. This neat trick greatly extends the usefulness of APE which would otherwise be a just poor man's Y-Wing.

The 2-cell ALS in [A1,B3] contains {1/3/7} so pairs that would cripple the solution for that ALS are {1,3}, {1,7} and {3,7}.

Let's consider all the possible pairs of numbers in our base pair [C2/C3]. These are:

1 and 3 - excluded by A1 + B3
1 and 4 - excluded by C1 + C5
1 and 9 - excluded by C1 + C5
3 and 3
3 and 4
3 and 9
8 and 3 - excluded by C9
8 and 4
8 and 9


Now, we have to be a tiny bit careful here. 3 has definitely been excluded as a possible solution in C3 but look down the list and 3 + 4 is still OK and 3 + 9 is OK. So we can't remove 3 from C2 just yet.

Credits: Myth Jellies came up with the insight for abc = ab/ac/bc

Note: There could be more than two, sometimes three or four ALSs of several sizes in an APE attack. I've considered examples with two for simplicity's sake


Example 3
APE Example 3
APE Example 3 : Load Example or : From the Start
Further into the same puzzle we come across a 3-cell ALS plus a bi-value in H3 attacking A3/B3. The ALS in [A1,C1,C3] contains the four numbers {1,4,7,9} which the solver thinks of as a quadruple combination. The combinations of 'abcd' are ab, ac, ad, bc, bd and cd. Back to the base pair: We can list the combinations for A3/B3 as

4 and 3
4 and 7 - excluded by [A1,C1,C3]
5 and 3
5 and 7 - excluded by H3
7 and 3
7 and 7 (impossible)

The tricky one with the 3-cell ALS is not the fact that the base pair will empty it (it can't since it is two cells and the ALS is 3 cells). It's the fact that a solution of 4 in A3 and 7 in B3 would mean there'd be only two candidates left to fill three cells. Thats enough to rule out the combination.

Aligned Pair Exclusion - Type 2
Aligned Pair Exclusion can also work even if the pair is not aligned. Sounds like a joke, but it's too late now to rename this strategy :) Perhaps 'Subset Exclusion' was a better idea. There is a subtle logical different but I have found many examples and it boosts the usefulness of this strategy.
I'm very grateful to Joseph Aleardi for putting me on the scent of this elegant logic.

APE Example 4 (turn off Y-Wings)
APE Example 4 (turn off Y-Wings) : Load Example or : From the Start
The simplest type of APE2 using just two bi-value cells duplicates the Y-Wing, but I include an example to illustrate how APE2 works.

The diagram here shows first the Y-Wing based on A1 - A4 (the pivot) - B6. It's quite easy to see that 8 must occur in either A1 or B6, thus removing it from B1 and B2.

But let's follow the APE logic with the non-aligned pair A4 and B1. (Note: We could also choose A1 and B2 and eliminate the 8 there also). A4 pairs with B1 using these combinations:

1 and 1 - POSSIBLE!
1 and 6
1 and 8 - excluded by A1
9 and 1
9 and 6
9 and 8 - excluded by B6

The only difference between APE 1 and APE 2 is that with non-aligned pairs the same candidate *could* be a solution in both cells. So 1 and 1 is definitely on the cards. Not that it is critical in this case. The other exclusions mean we can't have an 8 in B1, just as we thought.

APE Example 5
APE Example 5 : Load Example or : From the Start


Here is a more complex APE that does not have a Wing alternative. We have two bi-value cells and one two cell ALS attacking B1 and C7. Let's write out the combinations between those cells:

1 and 4 - excluded by B9
1 and 5 - excluded by B8
1 and 7 - excluded by [C1 + C3]
2 and 4
2 and 5
2 and 7
7 and 4
7 and 5
7 and 7 - Permitted!

Clearly 1 is removed from B1. The exact same formation also removes 1 from B2 (on the next step).
APE Example 6
APE Example 6 : Load Example or : From the Start


To conclude, a non-aligned pair using a bi-value cell and a 3-cell ALS. I'll leave it to the reader to work out why 6 can be removed from D1.

There is a second very nice APE later in the solving sequence using a 2-cell ALS and a 3-cell ALS. You can load the puzzle from the links under the diagram.
An Eight-Cell Aligned Pair
An Eight-Cell Aligned Pair
An Eight-Cell Aligned Pair : Load Example or : From the Start
I love to end these articles with a Sudoku from Klaus Brenner. He has made finding interesting and beautiful examples an art form and in the case of Aligned Pairs has found what we thought was impossible. An eight-cell Aligned Pair elimination! We had found some five-cell examples and wondered if there could be a six-cell or even a seven-cell. This is the first and only eight-cell formation known. Fortunately the solver can handle this many. Each cell is necessary to produce all the pairs used to cross reference with the target cells in D5 and E5 - the solver ignores any other ALSs that are not used. And very pretty it is.

How many difficult puzzles did Klaus have to check to find this? Astonishingly, around 21 million!

# Exocet
a.k.a. jExocet
Full Documentation Coming Soon
Exocet is a pattern that can often occur in very hard puzzles where the candidate density is very high. With few bi-value and bi-location candidates other strategies give up. Exocet takes on three or four candidate sets at a time which is just what is needed in the bottlenecks of extreme puzzles. My first implementation solved 51 out of 123 of the weekly "unsolvables" that were created by David Filmer. We will be replacing any stock known solvable with even harder puzzles.

Phil's concise description is impossible to better: When 2 of the 3 cells in a box-line intersection together contain 3 or 4 candidates, then in each of the two boxes in the same band but in different lines, if there are cells with the same 3 or 4 candidates, any others can be removed.

Order in Strategy List
My instinct is to put this near the end of the Extremes set of strategies but many of the eliminations in Exocet can overlap earlier strategies, I am told. I do not think I have implemented many of those but to test and improve I am putting it at the start of the extremes to give it more exercise. David Bird tells me it can go after the basics but that will have to wait until more variations are in place.

Credits
A number of people explored this strategy and its many variations. I am told the name was coined by forum participant Champagne. The pattern was first discovered by Allan Barker in the "Fata Morgana" puzzle[1],[2]. My main source is the excellent JExocet Compendium written by David P Bird, available in fourteen downloadable documents on the EnjoySudoku Forum and David was kind enough to answer questions as well. I would also like to credit Phil's Sudoku Solver as a source of examples and help. Any other credits not mentioned, please email me.

I don't intend to duplicate David's work but just the parts implemented by the solver and re-expressed in my own way. Terms and references to the original will be supplied.
The Exocet Pattern

Exocet Pattern
Exocet Pattern
Lets start with the pattern.
Pattern Rule 1
Two Base cells (B) exist in alignment in one box and usually contain three or four candidates *in total*. That could mean {1,2,3,4} + {1,2,3,4} but could also mean {1,2,3}+{2,3,4} or even {1,2,3}+{3,4}. I've not found an instance of two bi-value cells like {1,2}+{3,4} yet. To be explored.

Pattern Rule 2
We then check if there are two Target cells (T) that contain all the digits of the Base cell (plus any extras). The Targets cannot 'see' each other or the Base Cells. They must also be in the same Tier or Stack (group of 3x3 boxes in a row or column). The diagram highlights the top tier in red. There are only three possible cells for each Target given that they must not be 'seen'.
If Bases and Targets are aligned in a Tier (as in these diagrams) we look for three Cross-Lines that descend from the Targets and the cell not occupied by the Bases. These are marked in yellow - columns 3, 4 and 7. We are interested in the six cells outside the Tier (or stack). These cells are called S-Cells.

We will be talking about some of the other cells in the pattern as well, so lets introduce them. Each Target has a Companion cell marked with a C. Each Target has two Mirror Cells that are next to each opposite Target, marked M1 and M2.

Lastly, the asterisks are called Escape cells which can hold the candidates that are found to be false in the base.

Pattern Rule 3
To be a real Exocet pattern the Companion Cells must not contain the Base candidates, not even as clues or givens.

Exocet Pattern - Cover Lines
Exocet Pattern - Cover Lines
Pattern Rule 4
Now one last complication before we can be certain we have an Exocet. In the diagram I've set the Base candidates to be {1,2,3}. There is hopefully a scattering of these in the S-Cells. We want them to appear no more than twice each. If the Cross-Lines are columns we consider the rows where each Base candidate appears. These are called Cover-Lines and I've drawn all the cover-lines in the three colours of the three numbers.

I've stated that cover-lines are perpendicular to cross-lines. Usually they are, but to get the maximum number of elimination rules we can be flexible. It is possible that one Base candidate appears twice only in one column. If we were strictly perpendicular it would require two cover-lines, but all we want to do is "cover" the candidates, so in the single-column case we can "cover" them vertically. So the cover-line = the cross-line.
This will be useful later.
Pattern Inferences
If an Exocet pattern can be confirmed, then following inferences occur:
The two Target cells must contain different base digits.
Mirror cells must contain the same base digits as their 'opposite' Target cells together with one digit that is false in the base cells.
The two true base digits must each be true in two 'S' cells
As David writes, "These are a rich source of eliminations, some of which can be made immediately, and some that will become available later as the solution progresses. These can also be incorporated into AICs."

Note: When we talk about "true Base digits" we are talking about the final solution and knowing what those cells actually contain. We don't know that at the start but eliminations here might tell us more and we can go back through the Exocet check-list.

Elimination Rule 1
Exocet Rule 1 (untick X-Cycles)
Exocet Rule 1 (untick X-Cycles) : From the Start

Any candidate in a Target cell that is not one of the Base candidates can be removed. That takes out the 4 in B4 and the 2 and 7 in C7

This example actually contains a whole raft of Exocet eliminations but they rely on another test called the Compatible Digit Check. That I have not implemented so I'm going to ignore those. I will come back to this example in the next update when I've understood this test.
Elimination Rule 3
Bird's definition: A base candidate that is restricted to only one 'S' cell cover house is invalid and is false in the base mini-line and target cells.

Elimination Rule 4
Bird's definition: A base digit in a target that must be true in the other target is false.

Which I take to mean if eliminations thus far reduce one target to one digit ON then it is strongly linked and eliminates like a single.

Elimination Rule 5
Bird's definition: A base candidate that has a cross-line as an 'S' cell cover house must be false in the target cell in that cross-line

Elimination Rule 8
Bird documentation states "If a mirror node contains only one possible non-base digit value, it is true in that node and false in the cells in sight of it."
I couldn't make this work without creating incorrect eliminations. By best implementation that doesn't create incorrect removals goes along the lines of "base digit missing from mirror node or base digits missing in the mirrored target cell".
See Tebo below in the comments for more insight.