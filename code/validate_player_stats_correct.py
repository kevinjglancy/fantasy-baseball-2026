#!/usr/bin/env python3
"""Validate player stats by aggregating correctly (sum per-player first, then team)."""

import sqlite3
import argparse
from collections import defaultdict

def parse_h_ab(h_ab_str):
    """Parse 'H/AB' format, handling '--/--' for no at-bats."""
    if not h_ab_str or h_ab_str == '--/--':
        return 0, 0
    if '/' not in str(h_ab_str):
        return 0, 0
    parts = str(h_ab_str).split('/')
    try:
        return float(parts[0]), float(parts[1])
    except:
        return 0, 0

def validate_week(week_num):
    """Validate player stats aggregation against matchup stats for a week."""
    conn = sqlite3.connect('fantasy_baseball.db')
    cursor = conn.cursor()

    # Get all players for this week
    cursor.execute('''
        SELECT team_name, player_name, h_ab, r, hr, rbi, bb, sb, avg, ops
        FROM player_snapshots
        WHERE week = ? AND player_type = 'batter'
        ORDER BY team_name, player_name
    ''', (week_num,))

    # Aggregate by player first, then by team
    player_agg = defaultdict(lambda: defaultdict(lambda: {'h': 0, 'ab': 0, 'r': 0, 'hr': 0, 'rbi': 0, 'bb': 0, 'sb': 0}))

    for row in cursor.fetchall():
        team_name, player_name, h_ab, r, hr, rbi, bb, sb, avg, ops = row

        hits, ab = parse_h_ab(h_ab)

        player_agg[team_name][player_name]['h'] += hits
        player_agg[team_name][player_name]['ab'] += ab
        player_agg[team_name][player_name]['r'] += r or 0
        player_agg[team_name][player_name]['hr'] += hr or 0
        player_agg[team_name][player_name]['rbi'] += rbi or 0
        player_agg[team_name][player_name]['bb'] += bb or 0
        player_agg[team_name][player_name]['sb'] += sb or 0

    # Now aggregate to team level
    team_agg = {}
    for team_name in player_agg:
        team_h = sum(p['h'] for p in player_agg[team_name].values())
        team_ab = sum(p['ab'] for p in player_agg[team_name].values())
        team_r = sum(p['r'] for p in player_agg[team_name].values())
        team_hr = sum(p['hr'] for p in player_agg[team_name].values())
        team_rbi = sum(p['rbi'] for p in player_agg[team_name].values())
        team_bb = sum(p['bb'] for p in player_agg[team_name].values())
        team_sb = sum(p['sb'] for p in player_agg[team_name].values())

        team_agg[team_name] = {
            'h': team_h, 'ab': team_ab, 'r': team_r, 'hr': team_hr,
            'rbi': team_rbi, 'bb': team_bb, 'sb': team_sb
        }

    # Get official matchup stats
    cursor.execute('''
        SELECT DISTINCT team_name, r, hr, rbi, sb, avg, ops
        FROM team_day_snapshots
        WHERE snapshot_date IN
            (SELECT MAX(snapshot_date) FROM team_day_snapshots
             WHERE snapshot_date BETWEEN
                (SELECT MIN(snapshot_date) FROM player_snapshots WHERE week = ?)
                AND
                (SELECT MAX(snapshot_date) FROM player_snapshots WHERE week = ?))
    ''', (week_num, week_num))

    official_stats = {}
    for row in cursor.fetchall():
        team_name, r, hr, rbi, sb, avg, ops = row
        official_stats[team_name] = {
            'r': int(r), 'hr': int(hr), 'rbi': int(rbi), 'sb': int(sb),
            'avg': avg, 'ops': ops
        }

    # Compare
    print(f"\n{'='*140}")
    print(f"WEEK {week_num} VALIDATION - Aggregated Weekly Player Stats vs Official Matchup Stats")
    print(f"{'='*140}\n")

    print(f"{'Team':<25} {'Stat':<8} {'Official':>12} {'Agg':>12} {'Match':>8}")
    print('-' * 140)

    matches = 0
    total_checks = 0

    for team_name in sorted(team_agg.keys()):
        agg_data = team_agg[team_name]
        official = official_stats.get(team_name, {})

        if not official:
            print(f"{team_name:<25} {'---':<8} {'NO OFFICIAL DATA':>12}")
            continue

        # Check counting stats
        for stat in ['r', 'hr', 'rbi', 'sb']:
            official_val = official[stat]
            agg_val = agg_data[stat]

            match = '✓' if abs(official_val - agg_val) < 1 else '✗'
            print(f"{team_name:<25} {stat.upper():<8} {official_val:>12.0f} {agg_val:>12.0f} {match:>8}")

            if match == '✓':
                matches += 1
            total_checks += 1

        # Check AVG and OPS
        if agg_data['ab'] > 0:
            agg_avg = agg_data['h'] / agg_data['ab']
            # For OPS, would need to calculate OBP and SLG, which requires more info
            official_avg = official.get('avg', 0)

            avg_match = '✓' if abs(official_avg - agg_avg) < 0.01 else '✗'
            print(f"{team_name:<25} {'AVG':<8} {official_avg:>12.3f} {agg_avg:>12.3f} {avg_match:>8}")

            if avg_match == '✓':
                matches += 1
            total_checks += 1

    print(f"\n{'='*140}")
    print(f"✓ Matches: {matches}/{total_checks}")
    print(f"{'='*140}\n")

    conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Validate player stats aggregation')
    parser.add_argument('--week', type=int, default=2, help='Week to validate (default: 2)')
    args = parser.parse_args()

    validate_week(args.week)
