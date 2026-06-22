#!/usr/bin/env python3
"""Validate player stats by aggregating daily (starters only, no bench)."""

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
    """Validate by aggregating daily starters only (no bench players)."""
    conn = sqlite3.connect('fantasy_baseball.db')
    cursor = conn.cursor()

    # Get all players for this week, organized by day
    cursor.execute('''
        SELECT snapshot_date, team_name, player_name, h_ab, r, hr, rbi, bb, sb
        FROM player_snapshots
        WHERE week = ? AND player_type = 'batter'
        ORDER BY snapshot_date, team_name, player_name
    ''', (week_num,))

    # Aggregate: day -> team -> stats
    # Note: we only collected the active starters (before Bench marker),
    # so every player we have is a valid starter for that day
    daily_team_stats = defaultdict(lambda: defaultdict(lambda: {
        'h': 0, 'ab': 0, 'r': 0, 'hr': 0, 'rbi': 0, 'bb': 0, 'sb': 0, 'players': 0
    }))

    for row in cursor.fetchall():
        snapshot_date, team_name, player_name, h_ab, r, hr, rbi, bb, sb = row

        hits, ab = parse_h_ab(h_ab)

        stats = daily_team_stats[snapshot_date][team_name]
        stats['h'] += hits
        stats['ab'] += ab
        stats['r'] += r or 0
        stats['hr'] += hr or 0
        stats['rbi'] += rbi or 0
        stats['bb'] += bb or 0
        stats['sb'] += sb or 0
        stats['players'] += 1

    # Now sum across the week for each team
    team_weekly = defaultdict(lambda: {
        'h': 0, 'ab': 0, 'r': 0, 'hr': 0, 'rbi': 0, 'bb': 0, 'sb': 0
    })

    for snapshot_date in daily_team_stats:
        for team_name in daily_team_stats[snapshot_date]:
            daily_stats = daily_team_stats[snapshot_date][team_name]
            weekly = team_weekly[team_name]
            weekly['h'] += daily_stats['h']
            weekly['ab'] += daily_stats['ab']
            weekly['r'] += daily_stats['r']
            weekly['hr'] += daily_stats['hr']
            weekly['rbi'] += daily_stats['rbi']
            weekly['bb'] += daily_stats['bb']
            weekly['sb'] += daily_stats['sb']

    # Get official matchup stats (cumulative for the week)
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
    print(f"WEEK {week_num} VALIDATION - Daily Starters Aggregated (No Bench)")
    print(f"{'='*140}\n")

    print(f"{'Team':<25} {'Stat':<8} {'Official':>12} {'Agg':>12} {'Match':>8}")
    print('-' * 140)

    matches = 0
    total_checks = 0

    for team_name in sorted(team_weekly.keys()):
        agg_data = team_weekly[team_name]
        official = official_stats.get(team_name, {})

        if not official:
            print(f"{team_name:<25} {'---':<8} {'NO OFFICIAL DATA':>12}")
            continue

        # Check counting stats
        for stat in ['r', 'hr', 'rbi', 'sb']:
            official_val = official[stat]
            agg_val = int(agg_data[stat])

            match = '✓' if abs(official_val - agg_val) < 1 else '✗'
            print(f"{team_name:<25} {stat.upper():<8} {official_val:>12} {agg_val:>12} {match:>8}")

            if match == '✓':
                matches += 1
            total_checks += 1

        # Check AVG
        if agg_data['ab'] > 0:
            agg_avg = agg_data['h'] / agg_data['ab']
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
