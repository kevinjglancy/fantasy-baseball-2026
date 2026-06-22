#!/usr/bin/env python3
"""Expected record analysis for fantasy baseball season.

For each week, simulates each team playing every other team (round-robin).
A head-to-head matchup is won by winning more of the 12 scoring categories.
Expected record = total simulated wins / total simulated games.

Also shows per-category z-scores to indicate relative strength.
"""

import sqlite3
import argparse
from collections import defaultdict
from espn_schedule import get_week_date_range

# Categories where LOWER is better
LOWER_IS_BETTER = {'era', 'whip'}

# All 12 H2H categories
CATEGORIES = ['r', 'hr', 'rbi', 'sb', 'avg', 'ops', 'k', 'qs', 'sv', 'hd', 'era', 'whip']
CAT_DISPLAY = ['R', 'HR', 'RBI', 'SB', 'AVG', 'OPS', 'K', 'QS', 'SV', 'HD', 'ERA', 'WHIP']


def get_weekly_stats(conn, week):
    """Get each team's final stats for a given week from team_day_snapshots."""
    start, end = get_week_date_range(week)
    cursor = conn.cursor()

    # Get the last snapshot within the week for each team
    cursor.execute("""
        SELECT t.team_name, t.r, t.hr, t.rbi, t.sb, t.avg, t.ops,
               t.k, t.qs, t.sv, t.hd, t.era, t.whip
        FROM team_day_snapshots t
        INNER JOIN (
            SELECT team_name, MAX(snapshot_date) as max_date
            FROM team_day_snapshots
            WHERE snapshot_date BETWEEN ? AND ?
            GROUP BY team_name
        ) latest ON t.team_name = latest.team_name AND t.snapshot_date = latest.max_date
        WHERE t.snapshot_date BETWEEN ? AND ?
    """, (start, end, start, end))

    teams = {}
    for row in cursor.fetchall():
        name = row[0]
        teams[name] = {
            'r': row[1], 'hr': row[2], 'rbi': row[3], 'sb': row[4],
            'avg': row[5], 'ops': row[6], 'k': row[7], 'qs': row[8],
            'sv': row[9], 'hd': row[10], 'era': row[11], 'whip': row[12]
        }
    return teams


def week_category_stds(team_stats):
    """Return mean and std dev for each category across all teams in a week."""
    import math
    stats = {}
    for cat in CATEGORIES:
        vals = [team_stats[t].get(cat) or 0 for t in team_stats]
        mean = sum(vals) / len(vals)
        variance = sum((v - mean) ** 2 for v in vals) / len(vals)
        std = math.sqrt(variance) if variance > 0 else 0
        stats[cat] = (mean, std)
    return stats


def cat_win_prob(val_a, val_b, std, cat):
    """P(team A wins this category) given the field spread (std).

    Normalises the raw difference by the league std so that a 1-unit edge in a
    tight field is barely above 50%, but a large edge is near certain.
    """
    if std == 0:
        return 0.5
    diff = (val_a - val_b) / std
    if cat in LOWER_IS_BETTER:
        diff = -diff
    return norm_cdf(diff)


def poisson_binomial_win_prob(cat_probs):
    """P(winning >6 of 12 categories) via dynamic programming.

    Each category is an independent Bernoulli with its own probability.
    Ties (6-6) are split 50/50.
    """
    n = len(cat_probs)
    # dp[j] = P(exactly j category wins after processing i categories)
    dp = [0.0] * (n + 1)
    dp[0] = 1.0
    for p in cat_probs:
        new_dp = [0.0] * (n + 1)
        for j in range(n + 1):
            if dp[j] == 0:
                continue
            if j + 1 <= n:
                new_dp[j + 1] += dp[j] * p
            new_dp[j] += dp[j] * (1 - p)
        dp = new_dp
    # Win if >6, split tie at exactly 6
    p_win = sum(dp[7:]) + 0.5 * dp[6]
    return p_win


def calculate_expected_record(weeks_stats):
    """Round-robin simulation using probabilistic category wins.

    For each matchup, each category win probability is derived from the
    normalised difference (diff / league_std). Small edges give ~50/50;
    large edges give high confidence. Matchup win prob uses Poisson binomial.
    """
    team_exp_wins = defaultdict(float)
    team_exp_losses = defaultdict(float)
    team_cat_exp_wins = defaultdict(lambda: defaultdict(float))

    for week, team_stats in weeks_stats.items():
        cat_stats = week_category_stds(team_stats)
        teams = list(team_stats.keys())

        for i, team_a in enumerate(teams):
            for team_b in teams[i+1:]:
                cat_probs_a = []
                for cat in CATEGORIES:
                    va = team_stats[team_a].get(cat) or 0
                    vb = team_stats[team_b].get(cat) or 0
                    _, std = cat_stats[cat]
                    p = cat_win_prob(va, vb, std, cat)
                    cat_probs_a.append(p)
                    team_cat_exp_wins[team_a][cat] += p
                    team_cat_exp_wins[team_b][cat] += (1 - p)

                p_a_wins = poisson_binomial_win_prob(cat_probs_a)
                p_b_wins = 1 - p_a_wins

                team_exp_wins[team_a] += p_a_wins
                team_exp_losses[team_a] += p_b_wins
                team_exp_wins[team_b] += p_b_wins
                team_exp_losses[team_b] += p_a_wins

    return team_exp_wins, team_exp_losses, team_cat_exp_wins


def norm_cdf(z):
    """Normal CDF via math.erf — no scipy needed."""
    import math
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))


def calculate_zscore_summary(weeks_stats):
    """For each team, calculate average z-score per category across all weeks.

    Returns avg_zscores and also win_prob_by_cat (norm_cdf of avg z-score).
    win_prob represents probability of beating a randomly-drawn opponent in that
    category given the observed field distribution — so being 1 run above a
    tight field barely moves the needle above 50%.
    """
    import math

    team_zscores = defaultdict(lambda: defaultdict(list))

    for week, team_stats in weeks_stats.items():
        teams = list(team_stats.keys())
        for cat in CATEGORIES:
            vals = [(t, team_stats[t].get(cat) or 0) for t in teams]
            values = [v for _, v in vals]
            if len(values) < 2:
                continue
            mean = sum(values) / len(values)
            variance = sum((v - mean) ** 2 for v in values) / len(values)
            std = math.sqrt(variance) if variance > 0 else 0
            if std == 0:
                continue
            for team, val in vals:
                z = (val - mean) / std
                if cat in LOWER_IS_BETTER:
                    z = -z
                team_zscores[team][cat].append(z)

    avg_zscores = {}
    win_probs = {}
    for team in team_zscores:
        avg_zscores[team] = {}
        win_probs[team] = {}
        for cat in CATEGORIES:
            zlist = team_zscores[team].get(cat, [])
            avg_z = sum(zlist) / len(zlist) if zlist else 0.0
            avg_zscores[team][cat] = avg_z
            win_probs[team][cat] = norm_cdf(avg_z)

    return avg_zscores, win_probs


def print_expected_record(weeks_stats, completed_weeks):
    team_exp_wins, team_exp_losses, team_cat_exp_wins = calculate_expected_record(weeks_stats)

    all_teams = sorted(team_exp_wins.keys(), key=lambda t: team_exp_wins[t], reverse=True)
    total_games = (len(all_teams) - 1) * len(completed_weeks)

    print(f"\n{'='*110}")
    print(f"EXPECTED RECORD — Season (Weeks {min(completed_weeks)}-{max(completed_weeks)}, "
          f"{len(completed_weeks)} weeks × {len(all_teams)-1} simulated games/week = {total_games} total games per team)")
    print(f"Uses field spread to weight category edges — small edges ≈ 50/50")
    print(f"{'='*110}")
    print(f"\n{'Team':<25} {'Exp W':>7} {'Exp L':>7} {'Win%':>7}")
    print("-" * 50)

    for team in all_teams:
        w = team_exp_wins[team]
        l = team_exp_losses[team]
        pct = w / (w + l) if (w + l) > 0 else 0
        print(f"{team:<25} {w:>7.1f} {l:>7.1f} {pct:>7.3f}")

    print()


def print_category_breakdown(weeks_stats, completed_weeks):
    team_exp_wins, team_exp_losses, team_cat_exp_wins = calculate_expected_record(weeks_stats)
    all_teams = sorted(team_exp_wins.keys(), key=lambda t: team_exp_wins[t], reverse=True)
    total_matchups = (len(all_teams) - 1) * len(completed_weeks)

    print(f"\n{'='*140}")
    print(f"EXPECTED CATEGORY WIN % (probabilistic, normalised by field spread)")
    print(f"{'='*140}")

    header = f"{'Team':<25}" + "".join(f" {c:>6}" for c in CAT_DISPLAY) + f"  {'Avg':>6}"
    print(header)
    print("-" * 140)

    for team in all_teams:
        row = f"{team:<25}"
        probs = []
        for cat in CATEGORIES:
            exp = team_cat_exp_wins[team].get(cat, 0)
            p = exp / total_matchups if total_matchups > 0 else 0
            probs.append(p)
            row += f" {p:>6.2f}"
        row += f"  {sum(probs)/len(probs):>6.2f}"
        print(row)

    print()


def print_zscore_table(weeks_stats):
    avg_zscores, win_probs = calculate_zscore_summary(weeks_stats)
    all_teams = sorted(avg_zscores.keys(),
                       key=lambda t: sum(avg_zscores[t].values()), reverse=True)

    # --- Raw z-score table ---
    print(f"\n{'='*140}")
    print(f"AVERAGE Z-SCORE BY CATEGORY (positive = above league avg, negative = below)")
    print(f"Higher z-score is always better (ERA/WHIP inverted)")
    print(f"{'='*140}")

    header = f"{'Team':<25}" + "".join(f" {c:>6}" for c in CAT_DISPLAY) + f"  {'Total':>7}"
    print(header)
    print("-" * 140)

    for team in all_teams:
        row = f"{team:<25}"
        total = 0
        for cat in CATEGORIES:
            z = avg_zscores[team].get(cat, 0)
            total += z
            row += f" {z:>6.2f}"
        row += f"  {total:>7.2f}"
        print(row)

    # --- Win probability table (norm CDF of z-score) ---
    print(f"\n{'='*140}")
    print(f"CATEGORY WIN PROBABILITY vs RANDOM OPPONENT (derived from z-score via normal CDF)")
    print(f"50% = exactly league average. Being 1 run above avg in a tight field ≈ 50%.")
    print(f"{'='*140}")

    header = f"{'Team':<25}" + "".join(f" {c:>6}" for c in CAT_DISPLAY) + f"  {'Avg':>7}"
    print(header)
    print("-" * 140)

    for team in all_teams:
        row = f"{team:<25}"
        probs = []
        for cat in CATEGORIES:
            p = win_probs[team].get(cat, 0.5)
            probs.append(p)
            row += f" {p:>6.2f}"
        avg_p = sum(probs) / len(probs)
        row += f"  {avg_p:>7.2f}"
        print(row)

    print()


def main():
    parser = argparse.ArgumentParser(description='Expected record and category analysis')
    parser.add_argument('--db', default='fantasy_baseball.db')
    parser.add_argument('--weeks', default='2-11',
                        help='Week range to analyze (e.g. "2-11" or "2,3,5")')
    args = parser.parse_args()

    conn = sqlite3.connect(args.db)

    # Parse week range
    if '-' in args.weeks:
        start_w, end_w = args.weeks.split('-')
        completed_weeks = list(range(int(start_w), int(end_w) + 1))
    else:
        completed_weeks = [int(w) for w in args.weeks.split(',')]

    print(f"\nLoading stats for weeks: {completed_weeks}")

    weeks_stats = {}
    for week in completed_weeks:
        stats = get_weekly_stats(conn, week)
        if len(stats) < 10:
            print(f"  Week {week}: only {len(stats)} teams found, skipping")
            continue
        weeks_stats[week] = stats
        print(f"  Week {week}: {len(stats)} teams loaded")

    conn.close()

    if not weeks_stats:
        print("No data found.")
        return

    print_expected_record(weeks_stats, list(weeks_stats.keys()))
    print_category_breakdown(weeks_stats, list(weeks_stats.keys()))
    print_zscore_table(weeks_stats)


if __name__ == '__main__':
    main()
