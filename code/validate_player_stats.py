#!/usr/bin/env python3
"""Validate player stats by aggregating and comparing to official matchup stats."""

import sqlite3
import argparse
from collections import defaultdict

def parse_h_ab(h_ab_str):
    """Parse 'H/AB' format into (hits, at_bats)."""
    if not h_ab_str or '/' not in str(h_ab_str):
        return None, None
    parts = str(h_ab_str).split('/')
    try:
        return float(parts[0]), float(parts[1])
    except:
        return None, None

def parse_ip(ip_val):
    """Convert ESPN innings pitched (e.g. 6.1 = 6 1/3 innings) to decimal."""
    if ip_val is None:
        return None
    whole = int(ip_val)
    partial = round(ip_val - whole, 1)
    return whole + partial * 10 / 3


def validate_week(week_num):
    """Validate player stats aggregation against matchup stats for a week."""
    conn = sqlite3.connect('fantasy_baseball.db')
    cursor = conn.cursor()

    # --- BATTING ---
    cursor.execute('''
        SELECT team_name, player_name, h_ab, r, hr, rbi, bb, sb, avg, ops
        FROM player_snapshots
        WHERE week = ? AND player_type = 'batter'
        ORDER BY team_name, player_name
    ''', (week_num,))

    bat_agg = defaultdict(lambda: {
        'ab': 0, 'h': 0, 'r': 0, 'hr': 0, 'rbi': 0, 'bb': 0, 'sb': 0,
        'tb': 0, 'players': set()
    })

    for row in cursor.fetchall():
        team_name, player_name, h_ab, r, hr, rbi, bb, sb, avg, ops = row

        hits, ab = parse_h_ab(h_ab)
        if ab is None:
            continue

        hits = hits or 0
        bb = bb or 0
        ops = ops or 0

        denominator = ab + bb
        obp = (hits + bb) / denominator if denominator > 0 else 0
        slg = ops - obp
        tb = slg * ab

        bat_agg[team_name]['ab'] += ab
        bat_agg[team_name]['h'] += hits
        bat_agg[team_name]['r'] += r or 0
        bat_agg[team_name]['hr'] += hr or 0
        bat_agg[team_name]['rbi'] += rbi or 0
        bat_agg[team_name]['bb'] += bb
        bat_agg[team_name]['sb'] += sb or 0
        bat_agg[team_name]['tb'] += tb
        bat_agg[team_name]['players'].add(player_name)

    # --- PITCHING ---
    cursor.execute('''
        SELECT team_name, player_name, ip, h, er, bb, k, qs, sv, hd
        FROM player_snapshots
        WHERE week = ? AND player_type = 'pitcher'
        ORDER BY team_name, player_name
    ''', (week_num,))

    pit_agg = defaultdict(lambda: {
        'ip': 0.0, 'h': 0, 'er': 0, 'bb': 0, 'k': 0, 'qs': 0, 'sv': 0, 'hd': 0,
        'players': set()
    })

    for row in cursor.fetchall():
        team_name, player_name, ip, h, er, bb, k, qs, sv, hd = row
        if ip is None:
            continue
        ip_dec = parse_ip(ip)
        pit_agg[team_name]['ip'] += ip_dec
        pit_agg[team_name]['h'] += h or 0
        pit_agg[team_name]['er'] += er or 0
        pit_agg[team_name]['bb'] += bb or 0
        pit_agg[team_name]['k'] += k or 0
        pit_agg[team_name]['qs'] += qs or 0
        pit_agg[team_name]['sv'] += sv or 0
        pit_agg[team_name]['hd'] += hd or 0
        pit_agg[team_name]['players'].add(player_name)

    # --- OFFICIAL STATS ---
    cursor.execute('''
        SELECT DISTINCT team_name, r, hr, rbi, sb, avg, ops, k, qs, sv, hd, era, whip
        FROM team_day_snapshots
        WHERE snapshot_date IN
            (SELECT MAX(snapshot_date) FROM team_day_snapshots
             WHERE snapshot_date BETWEEN
                (SELECT MIN(snapshot_date) FROM player_snapshots WHERE week = ?)
                AND
                (SELECT MAX(snapshot_date) FROM player_snapshots WHERE week = ?))
    ''', (week_num, week_num))

    official = {}
    for row in cursor.fetchall():
        team_name, r, hr, rbi, sb, avg, ops, k, qs, sv, hd, era, whip = row
        official[team_name] = {
            'r': r, 'hr': hr, 'rbi': rbi, 'sb': sb, 'avg': avg, 'ops': ops,
            'k': k, 'qs': qs, 'sv': sv, 'hd': hd, 'era': era, 'whip': whip
        }

    # --- COMPARE ---
    print(f"\n{'='*140}")
    print(f"WEEK {week_num} VALIDATION - Aggregated Weekly Player Stats vs Official Matchup Stats")
    print(f"{'='*140}\n")
    print(f"{'Team':<25} {'Stat':<8} {'Official':>12} {'Agg':>12} {'Match':>8} {'Players':>8}")
    print('-' * 140)

    matches = 0
    total_checks = 0
    all_teams = sorted(set(list(bat_agg.keys()) + list(pit_agg.keys())))

    for team_name in all_teams:
        off = official.get(team_name, {})
        if not off:
            print(f"{team_name:<25} {'---':<8} {'NO OFFICIAL DATA':>12}")
            continue

        bat = bat_agg[team_name]
        pit = pit_agg[team_name]

        # Batting counting stats
        for stat in ['r', 'hr', 'rbi', 'sb']:
            ov = off.get(stat, 0) or 0
            av = bat.get(stat, 0)
            m = '✓' if abs(ov - av) < 1 else '✗'
            print(f"{team_name:<25} {stat.upper():<8} {ov:>12.0f} {av:>12.0f} {m:>8} {len(bat['players']):>8}")
            matches += m == '✓'
            total_checks += 1

        # Batting rate stats
        if bat['ab'] > 0:
            agg_avg = bat['h'] / bat['ab']
            agg_obp = (bat['h'] + bat['bb']) / (bat['ab'] + bat['bb']) if (bat['ab'] + bat['bb']) > 0 else 0
            agg_slg = bat['tb'] / bat['ab']
            agg_ops = agg_obp + agg_slg

            for stat, ov, av in [('AVG', off.get('avg', 0) or 0, agg_avg),
                                  ('OPS', off.get('ops', 0) or 0, agg_ops)]:
                m = '✓' if abs(ov - av) < 0.01 else '✗'
                print(f"{team_name:<25} {stat:<8} {ov:>12.3f} {av:>12.3f} {m:>8}")
                matches += m == '✓'
                total_checks += 1

        # Pitching counting stats
        for stat in ['k', 'qs', 'sv', 'hd']:
            ov = off.get(stat, 0) or 0
            av = pit.get(stat, 0)
            m = '✓' if abs(ov - av) < 1 else '✗'
            print(f"{team_name:<25} {stat.upper():<8} {ov:>12.0f} {av:>12.0f} {m:>8} {len(pit['players']):>8}")
            matches += m == '✓'
            total_checks += 1

        # Pitching rate stats
        if pit['ip'] > 0:
            agg_era = (pit['er'] / pit['ip']) * 9
            agg_whip = (pit['h'] + pit['bb']) / pit['ip']

            for stat, ov, av in [('ERA', off.get('era', 0) or 0, agg_era),
                                  ('WHIP', off.get('whip', 0) or 0, agg_whip)]:
                m = '✓' if abs(ov - av) < 0.05 else '✗'
                print(f"{team_name:<25} {stat:<8} {ov:>12.3f} {av:>12.3f} {m:>8}")
                matches += m == '✓'
                total_checks += 1

        print()

    print(f"{'='*140}")
    print(f"✓ Matches: {matches}/{total_checks}")
    print(f"{'='*140}\n")

    conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Validate player stats aggregation')
    parser.add_argument('--week', type=int, default=2, help='Week to validate (default: 2)')
    args = parser.parse_args()

    validate_week(args.week)
