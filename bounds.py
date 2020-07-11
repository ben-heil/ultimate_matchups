""" This file is from this repo https://github.com/blinkity/metagame based on Alexander Jaffe's
talk here https://www.youtube.com/watch?v=miu3ldl-nY4&feature=youtu.be

It is largely the same as the original, though I've added a function to convert my matchup csv
into the form that the program is looking for and cleaned up the code's style with black
"""

import os

import pandas
import seaborn as sns
import numpy as np
import pulp
from pulp import *
sns.set_context("talk")


def boundsFromCsv(filename):
    allData = pandas.read_csv("allstarMatchups.csv")


def makeMatchups(allRanks, selfRanks):
    overall_beat_probs = (3.0 / 2.0) * selfRanks["beat_opponent_prob"] - 0.25
    overall_beat_probs.name = "overall_beat_opponent_prob"
    overall_beat_probs_df = pandas.DataFrame(overall_beat_probs)
    mergedRanks = allRanks.merge(
        overall_beat_probs_df, left_on="PLAYER_CHAR_COPY", right_index=True
    )
    specific_opponent_probs = (
        3 * mergedRanks["beat_opponent_prob"]
        - 2 * mergedRanks["overall_beat_opponent_prob"]
    )
    matchups = specific_opponent_probs.unstack()
    averagedMatchups = (matchups + (1 - matchups.T)) / 2.0
    return averagedMatchups


def setupBasicProblem(matrix):
    prob = LpProblem("rock_paper_scissors", pulp.LpMaximize)
    the_vars = np.append(matrix.index.values, (["w"]))
    lp_vars = LpVariable.dicts("vrs", the_vars)
    # First add the objective function.
    prob += lpSum([lp_vars["w"]])
    # Now add the non-negativity constraints.
    for row_strat in matrix.index.values:
        prob += lpSum([1.0 * lp_vars[row_strat]]) >= 0
    # Now add the sum=1 constraint.
    prob += lpSum([1.0 * lp_vars[x] for x in matrix.index.values]) == 1
    # Now add the column payoff constraints
    for col_strat in matrix.columns.values:
        stratTerms = [
            matrix.loc[row_strat, col_strat] * lp_vars[row_strat]
            for row_strat in matrix.index.values
        ]
        allTerms = stratTerms + [-1 * lp_vars["w"]]
        prob += lpSum(allTerms) >= 0
    # now write it out and solve
    return prob, lp_vars


def solveGame(matrix):
    prob, lp_vars = setupBasicProblem(matrix)
    prob.writeLP("rockpaperscissors.lp")
    prob.solve()
    # now prepare the value and mixed strategy
    game_val = value(lp_vars["w"])
    strat_probs = {}
    for row_strat in matrix.index.values:
        strat_probs[row_strat] = value(lp_vars[row_strat])
    # and output it
    return prob, game_val, strat_probs


def solveGameWithRowConstraint(matrix, rowname, constraint):
    prob, lp_vars = setupBasicProblem(matrix)
    # add the additional constraint
    prob += lpSum(lp_vars[rowname]) == constraint
    prob.writeLP("rockpaperscissors.lp")
    prob.solve()
    # now prepare the value and mixed strategy
    game_val = value(lp_vars["w"])
    strat_probs = {}
    for row_strat in matrix.index.values:
        strat_probs[row_strat] = value(lp_vars[row_strat])
    # and output it
    return prob, game_val, strat_probs


def getWinRates(rowname, matrix, division=10):
    probs = np.linspace(0, 1, division + 1)
    return pandas.Series(
        [solveGameWithRowConstraint(matrix, rowname, p)[1] for p in probs],
        index=probs,
        name=rowname,
    )


def getAllWinRates(matrix, division=10):
    return pandas.concat(
        [getWinRates(row, matrix, division) for row in matrix.index.values], axis=1
    )


def plotIntervals(winRates, doSort, threshold):
    intervals = winRates.apply(
        lambda x: pandas.Series(
            [
                x[x >= threshold].first_valid_index(),
                x[x >= threshold].last_valid_index(),
            ],
            index=["minv", "maxv"],
        )
    ).T
    intervals["bar1"] = intervals["minv"]
    intervals["bar2"] = intervals["maxv"] - intervals["minv"]
    intervals["bar3"] = 1 - (intervals["bar1"] + intervals["bar2"])
    # Maybe we want to sort by max, min values, or maybe we just want to keep it
    # in its matchup-chart-specified order.
    print(intervals)
    if doSort:
        intervals = intervals.sort_values(by=["maxv", "minv"])
    else:  # else reverse, it's weird
        intervals = intervals.reindex(index=intervals.index[::-1])
    img = intervals[["bar1", "bar2", "bar3"]].plot(
        kind="barh",
        stacked=True,
        color=["w", "g", "w"],
        xticks=np.linspace(0, 1, 21),
        title="Range of Optimal Play Frequencies",
        legend=False,
        fontsize=3.5
    )
    return img


def makeMatchupsFromOverallBeatProbs(allRanks, overall_beat_probs):
    overall_beat_probs.name = "overall_beat_opponent_prob"
    overall_beat_probs_df = pandas.DataFrame(overall_beat_probs)
    mergedRanks = allRanks.merge(
        overall_beat_probs_df, left_on="PLAYER_CHAR_COPY", right_index=True
    )
    specific_opponent_probs = (
        3 * mergedRanks["beat_opponent_prob"]
        - 2 * mergedRanks["overall_beat_opponent_prob"]
    )
    matchups = specific_opponent_probs.unstack()
    return matchups


def parse_matchup_file(matchup_path: str) -> pandas.DataFrame:
    matchups = pandas.read_csv(matchup_path, index_col=0)
    matchups = matchups.pivot(index='char1', columns='char2', values='win_rate')
    matchups[matchups.isnull()] = .5
    return matchups


def main():
    # matplotlib.use('PS')
    if not os.path.exists('solved_lp.csv'):
        matchup_path = 'matchups.csv'
        matchups = parse_matchup_file(matchup_path)
        matchupPayoffs = 2 * matchups - 1
        allWinRates = getAllWinRates(matchupPayoffs, 100)
        print(allWinRates)
        allWinRates.to_csv('solved_lp.csv')
    else:
        allWinRates = pandas.read_csv('solved_lp.csv', index_col=0)
        print(allWinRates)
    img = plotIntervals(allWinRates, True, -0.02)
    img.get_figure().savefig("optimal_frequencies.pdf")


if __name__ == "__main__":
    main()
