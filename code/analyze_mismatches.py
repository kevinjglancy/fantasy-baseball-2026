#!/usr/bin/env python3
"""Detailed analysis of stat mismatches between player aggregates and official stats."""

import sqlite3
import argparse
from collections import defaultdict

def convert_innings(ip_str):
    """Convert baseball innings format to decimal."""
    if not ip_str or ip_str == 'None':
        return 0
    ip = float(ip_str)
    whole = int(ip)
    frac = ip - whole
    if frac > 0:
        frac = frac * 10
        frac_decimal = frac / 3
        return whole + frac_decimal
    return whole

def analyze_week(week_num):
    """Show detailed mismatches for a week."""
    conn = sqlite3.connect('fantasy_baseball.db')
    cursor = conn.cursor()

    print(f"\n{'='*120}")
    print(f"DETAILED MISMATCH ANALYSIS - WEEK {week_num}")
    print(f"{'='*120}\n")

    # Get all teams
    cursor.execute('SELECT DISTINCT team_name FROM player_snapshots WHERE week = ?', (week_num,))
    teams = sorted([row[0] for row in cursor.fetchall()])

    # Get official stats
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
        team_name = row[0]
        official[team_name] = {
            'r': int(row[1]), 'hr': int(row[2]), 'rbi': int(row[3]), 'sb': int(row[4]),
            'avg': row[5], 'ops': row[6],
            'k': int(row[7]), 'qs': int(row[8]), 'sv': int(row[9]), 'hd': int(row[10]),
            'era': row[11], 'whip': row[12]
        }

    # For each team, aggregate player stats
    for team_name in teams:
        # BATTERS
        cursor.execute('''
            SELECT SUM(CAST(SUBSTR(h_ab, 1, INSTR(h_ab, '/') - 1) AS FLOAT)) as h,
                   SUM(CAST(SUBSTR(h_ab, INSTR(h_ab, '/') + 1) AS FLOAT)) as ab,
                   SUM(r) as r, SUM(hr) as hr, SUM(rbi) as rbi, SUM(sb) as sb
            FROM player_snapshots
            WHERE week = ? AND team_name = ? AND player_type = 'batter' AND h_ab LIKE '%/%'
        ''', (week_num, team_name))

        h, ab, r, hr, rbi, sb = cursor.fetchone()
        h = h or 0
        ab = ab or 0
        r = int(r or 0)
        hr = int(hr or 0)
        rbi = int(rbi or 0)
        sb = int(sb or 0)
        team_avg = h / ab if ab > 0 else 0

        # PITCHERS
        cursor.execute('''
            SELECT SUM(CASE WHEN ip IS NOT NULL AND ip > 0 THEN ip ELSE 0 END) as ip,
                   SUM(h) as h, SUM(bb) as bb, SUM(er) as er, SUM(k) as k,
                   SUM(qs) as qs, SUM(sv) as sv, SUM(hd) as hd
            FROM player_snapshots
            WHERE week = ? AND team_name = ? AND player_type = 'pitcher'
        ''', (week_num, team_name))

        ip, h_pit, bb, er, k, qs, sv, hd = cursor.fetchone()
        ip = ip or 0
        h_pit = h_pit or 0
        bb = bb or 0
        er = er or 0
        k = int(k or 0)
        qs = int(qs or 0)
        sv = int(sv or 0)
        hd = int(hd or 0)

        if ip > 0:
            ip_decimal = convert_innings(str(ip))
        else:
            ip_decimal = 0

        team_era = (er / ip_decimal * 9) if ip_decimal > 0 else 0
        team_whip = ((h_pit + bb) / ip_decimal) if ip_decimal > 0 else 0

        # Compare
        if team_name not in official:
            continue

        off = official[team_name]

        # Check each stat
        mismatches = []

        # Batting stats
        if abs(r - off['r']) >= 1:
            mismatches.append(f"R: {off['r']} (official) vs {r} (agg) = {r - off['r']:+d}")
        if abs(hr - off['hr']) >= 1:
            mismatches.append(f"HR: {off['hr']} vs {hr} = {hr - off['hr']:+d}")
        if abs(rbi - off['rbi']) >= 1:
            mismatches.append(f"RBI: {off['rbi']} vs {rbi} = {rbi - off['rbi']:+d}")
        if abs(sb - off['sb']) >= 1:
            mismatches.append(f"SB: {off['sb']} vs {sb} = {sb - off['sb']:+d}")
        if abs(team_avg - off['avg']) >= 0.01:
            mismatches.append(f"AVG: {off['avg']:.3f} vs {team_avg:.3f} = {team_avg - off['avg']:+.3f}")

        # Pitching stats
        if abs(k - off['k']) >= 1:
            mismatches.append(f"K: {off['k']} vs {k} = {k - off['k']:+d}")
        if abs(qs - off['qs']) >= 1:
            mismatches.append(f"QS: {off['qs']} vs {qs} = {qs - off['qs']:+d}")
        if abs(sv - off['sv']) >= 1:
            mismatches.append(f"SV: {off['sv']} vs {sv} = {sv - off['sv']:+d}")
        if abs(hd - off['hd']) >= 1:
            mismatches.append(f"HD: {off['hd']} vs {hd} = {hd - off['hd']:+d}")
        if abs(team_era - off['era']) >= 0.1:
            mismatches.append(f"ERA: {off['era']:.2f} vs {team_era:.2f} = {team_era - off['era']:+.2f}")
        if abs(team_whip - off['whip']) >= 0.1:
            mismatches.append(f"WHIP: {off['whip']:.2f} vs {team_whip:.2f} = {team_whip - off['whip']:+.2f}")

        if mismatches:
            print(f"{team_name}:")
            for mismatch in mismatches:
                print(f"  ✗ {mismatch}")
            print()
        else:
            print(f"{team_name}: ✓ All stats match")
            print()

    conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Analyze stat mismatches')
    parser.add_argument('--week', type=int, required=True, help='Week to analyze')
    args = parser.parse_args()

    analyze_week(args.week)
