#!/usr/bin/env python3
"""Display season-to-date roto leaderboard for a given date."""

import sys
import argparse
from datetime import date
import db

def display_leaderboard(target_date: str):
    """Display season-to-date roto leaderboard for a given date."""
    conn = db.init_db()

    # Load all team data for that date
    df = db.load_team_day_snapshots(conn, start_date=target_date, end_date=target_date)

    if df.empty:
        print(f"No data for {target_date}")
        sys.exit(1)

    # Sort by R (runs) descending
    df_sorted = df.sort_values('r', ascending=False, na_position='last')

    print(f"\n{'='*160}")
    print(f"SEASON-TO-DATE ROTO LEADERBOARD - {target_date}")
    print(f"{'='*160}\n")

    print(f"{'RK':<4}{'TEAM':<30}{'R':>4}{'HR':>4}{'RBI':>4}{'SB':>4}{'AVG':>8}{'OPS':>8}{'K':>4}{'QS':>4}{'SV':>4}{'HD':>4}{'ERA':>8}{'WHIP':>8}")
    print(f"{'-'*160}")

    for rank, (_, row) in enumerate(df_sorted.iterrows(), 1):
        avg_str = f"{row['avg']:.4f}" if row['avg'] is not None else "---"
        ops_str = f"{row['ops']:.4f}" if row['ops'] is not None else "---"
        era_str = f"{row['era']:.3f}" if row['era'] is not None else "---"
        whip_str = f"{row['whip']:.3f}" if row['whip'] is not None else "---"

        print(f"{rank:<4}{row['team_name']:<30}{int(row['r']):>4}{int(row['hr']):>4}{int(row['rbi']):>4}{int(row['sb']):>4}{avg_str:>8}{ops_str:>8}{int(row['k']):>4}{int(row['qs']):>4}{int(row['sv']):>4}{int(row['hd']):>4}{era_str:>8}{whip_str:>8}")

    print(f"\n{'='*160}")

    conn.close()

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Display season-to-date roto leaderboard")
    parser.add_argument("--date", required=True, help="Target date (YYYY-MM-DD), default: today")
    args = parser.parse_args()

    display_leaderboard(args.date)
