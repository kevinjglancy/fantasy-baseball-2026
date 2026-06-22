#!/usr/bin/env python3
"""Complete week validation - validates both batter and pitcher stats against official matchup stats.

This script aggregates individual player stats collected daily and compares them
to official matchup stats from ESPN. Uses proper innings conversion and includes
walks (BB) for accurate ERA and WHIP calculations.
"""

import sqlite3
import argparse
from collections import defaultdict

def convert_innings(ip_str):
    """Convert baseball innings format (5.1 = 5 + 1/3) to decimal.

    In baseball notation, innings are X.Y where Y is outs (0, 1, or 2).
    5.1 = 5 + 1/3 innings, 5.2 = 5 + 2/3 innings
    """
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

def validate_week(week_num):
    """Validate player stats aggregation against official matchup stats for a week."""
    conn = sqlite3.connect('fantasy_baseball.db')
    cursor = conn.cursor()

    print(f"\n{'='*100}")
    print(f"WEEK {week_num} VALIDATION - Complete Player Stats vs Official Matchup Stats")
    print(f"{'='*100}\n")

    # Get all teams for this week
    cursor.execute('''
        SELECT DISTINCT team_name FROM player_snapshots WHERE week = ?
    ''', (week_num,))

    teams = [row[0] for row in cursor.fetchall()]

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

    official_stats = {}
    for row in cursor.fetchall():
        team_name, r, hr, rbi, sb, avg, ops, k, qs, sv, hd, era, whip = row
        official_stats[team_name] = {
            'r': int(r), 'hr': int(hr), 'rbi': int(rbi), 'sb': int(sb),
            'avg': avg, 'ops': ops,
            'k': int(k), 'qs': int(qs), 'sv': int(sv), 'hd': int(hd),
            'era': era, 'whip': whip
        }

    print(f"{'Team':<25} {'Batters':<50} {'Pitchers':<50}")
    print(f"{'':<25} {'R  HR RBI SB  AVG':<50} {'K  QS SV HD  ERA  WHIP':<50}")
    print('-' * 100)

    total_matches = 0
    total_checks = 0

    for team_name in sorted(teams):
        # BATTERS
        cursor.execute('''
            SELECT SUM(CAST(SUBSTR(h_ab, 1, INSTR(h_ab, '/') - 1) AS FLOAT)) as h,
                   SUM(CAST(SUBSTR(h_ab, INSTR(h_ab, '/') + 1) AS FLOAT)) as ab,
                   SUM(r) as r, SUM(hr) as hr, SUM(rbi) as rbi, SUM(bb) as bb, SUM(sb) as sb
            FROM player_snapshots
            WHERE week = ? AND team_name = ? AND player_type = 'batter' AND h_ab LIKE '%/%'
        ''', (week_num, team_name))

        h, ab, r, hr, rbi, bb, sb = cursor.fetchone()
        h = h or 0
        ab = ab or 0
        r = int(r or 0)
        hr = int(hr or 0)
        rbi = int(rbi or 0)
        bb = bb or 0
        sb = int(sb or 0)

        team_avg = h / ab if ab > 0 else 0

        # PITCHERS - Fetch all and aggregate with proper innings conversion
        cursor.execute('''
            SELECT ip, h, bb, er, k, qs, sv, hd
            FROM player_snapshots
            WHERE week = ? AND team_name = ? AND player_type = 'pitcher'
        ''', (week_num, team_name))

        pitcher_rows = cursor.fetchall()
        ip_decimal = 0
        h = 0
        bb = 0
        er = 0
        k = 0
        qs = 0
        sv = 0
        hd = 0

        for ip_str, h_val, bb_val, er_val, k_val, qs_val, sv_val, hd_val in pitcher_rows:
            # Convert innings properly (5.1 = 5 + 1/3, not 5.1)
            if ip_str and float(ip_str) > 0:
                ip_decimal += convert_innings(str(ip_str))

            h += h_val or 0
            bb += bb_val or 0
            er += er_val or 0
            k += k_val or 0
            qs += qs_val or 0
            sv += sv_val or 0
            hd += hd_val or 0

        k = int(k)
        qs = int(qs)
        sv = int(sv)
        hd = int(hd)

        team_era = (er / ip_decimal * 9) if ip_decimal > 0 else 0
        team_whip = ((h + bb) / ip_decimal) if ip_decimal > 0 else 0

        # Compare
        if team_name in official_stats:
            off = official_stats[team_name]

            # Count matches
            checks = [
                abs(r - off['r']) < 1,
                abs(hr - off['hr']) < 1,
                abs(rbi - off['rbi']) < 1,
                abs(sb - off['sb']) < 1,
                abs(team_avg - off['avg']) < 0.01,
                abs(k - off['k']) < 1,
                abs(qs - off['qs']) < 1,
                abs(sv - off['sv']) < 1,
                abs(hd - off['hd']) < 1,
                abs(team_era - off['era']) < 0.1,
                abs(team_whip - off['whip']) < 0.1
            ]

            matches = sum(checks)
            total_matches += matches
            total_checks += len(checks)

            batter_str = f"{r:2} {hr:2} {rbi:3} {sb:2} {team_avg:.3f}"
            pitcher_str = f"{k:2} {qs:2} {sv:2} {hd:2} {team_era:5.2f} {team_whip:5.2f}"
            match_indicator = '✓' if matches == len(checks) else '✗'

            print(f"{team_name:<25} {batter_str:<50} {pitcher_str:<50} {match_indicator}")
        else:
            print(f"{team_name:<25} NO OFFICIAL DATA")

    print('-' * 100)
    print(f"✓ Total Matches: {total_matches}/{total_checks} ({100*total_matches//total_checks}%)")
    print(f"{'='*100}\n")

    conn.close()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Validate complete week of player stats')
    parser.add_argument('--week', type=int, default=2, help='Week to validate (default: 2)')
    args = parser.parse_args()

    validate_week(args.week)
