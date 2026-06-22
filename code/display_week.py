#!/usr/bin/env python3
"""Display weekly matchup stats for all teams with sample player."""

import sys
import argparse
import db

def display_week_stats(start_date: str, end_date: str):
    """Display all team stats and 1 player sample from each team."""
    conn = db.init_db()

    teams = [
        'All Betts Are Off',
        'Cronen-Zone',
        'Lets Go Bucs',
        'Phoenix Coyotes',
        'Pittsburgh Piglets',
        'Pittsburgh Pirates',
        "Pooh's On First",
        'Seattle Dumpers',
        'The Big Gamblino',
        'The Chicago Orphans'
    ]

    print(f"\n{'='*120}")
    print(f"MATCHUP STATS: {start_date} to {end_date}")
    print(f"{'='*120}")

    print(f"\n{'Team':<25} {'R':>3} {'HR':>3} {'RBI':>3} {'SB':>3} {'AVG':>8} {'OPS':>8} {'K':>3} {'QS':>3} {'SV':>3} {'HD':>3} {'ERA':>7} {'WHIP':>7}")
    print(f"{'-'*120}")

    for team in teams:
        stats = db.aggregate_team_stats(conn, team_name=team, start_date=start_date, end_date=end_date)

        avg_str = f"{stats['AVG']:.4f}" if stats['AVG'] is not None else "---"
        ops_str = f"{stats['OPS']:.4f}" if stats['OPS'] is not None else "---"
        era_str = f"{stats['ERA']:.3f}" if stats['ERA'] is not None else "---"
        whip_str = f"{stats['WHIP']:.3f}" if stats['WHIP'] is not None else "---"

        print(f"{team:<25} {stats['R']:>3} {stats['HR']:>3} {stats['RBI']:>3} {stats['SB']:>3} {avg_str:>8} {ops_str:>8} {stats['K']:>3} {stats['QS']:>3} {stats['SV']:>3} {stats['HD']:>3} {era_str:>7} {whip_str:>7}")

    # Show sample players
    print(f"\n{'='*120}")
    print(f"SAMPLE PLAYERS (1 from each team)")
    print(f"{'='*120}")

    import sqlite3
    cursor = conn.cursor()

    for team in teams:
        # Get 1 batter and 1 pitcher
        cursor.execute('''
            SELECT player_name, player_type, r, hr, rbi, sb, k, sv, ip
            FROM player_snapshots
            WHERE team_name = ? AND snapshot_date >= ? AND snapshot_date <= ?
            AND player_type IN ('batter', 'pitcher')
            GROUP BY player_name, player_type
            HAVING MAX(snapshot_date)
            LIMIT 2
        ''', (team, start_date, end_date))

        players = cursor.fetchall()

        print(f"\n{team}:")
        for player in players:
            name, ptype, r, hr, rbi, sb, k, sv, ip = player
            if ptype == 'batter':
                print(f"  ⚾ {name}: R={int(r) if r else 0} HR={int(hr) if hr else 0} RBI={int(rbi) if rbi else 0} SB={int(sb) if sb else 0}")
            else:
                print(f"  ⚾ {name}: K={int(k) if k else 0} SV={int(sv) if sv else 0} IP={ip if ip else 0}")

    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Display weekly matchup stats")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    display_week_stats(args.start_date, args.end_date)
