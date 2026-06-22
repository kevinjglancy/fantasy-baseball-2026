#!/usr/bin/env python3
"""Quick stats queries."""

import sys
import argparse
import pandas as pd
import db

def league_leaders_by_stat(week: int, stat: str, limit: int = 10):
    """Show league leaders for a stat (sum across all dates)."""
    conn = db.init_db()

    try:
        # Load all player snapshots for the week
        df = db.load_player_snapshots(conn, week=week)

        if df.empty:
            print(f"No data for week {week}")
            return

        # Sum by player (across all snapshot dates)
        df[stat] = pd.to_numeric(df[stat], errors='coerce')
        leaders = df.groupby(['player_name', 'team_name', 'player_type']).agg({stat: 'sum'}).reset_index()
        leaders = leaders.sort_values(stat, ascending=False).head(limit)

        print(f"\n=== WEEK {week} {stat.upper()} LEADERS ===\n")
        print(f"{'Rank':<5} {'Player':<20} {'Team':<25} {'Type':<8} {stat.upper():>8}")
        print("-" * 70)

        for idx, row in leaders.iterrows():
            val = row[stat] if row[stat] else 0
            print(f"{idx+1:<5} {row['player_name']:<20} {row['team_name']:<25} {row['player_type']:<8} {val:>8.1f}")

    finally:
        conn.close()

def team_leaders_by_stat(week: int, stat: str, team_name: str):
    """Show a team's leaders for a stat."""
    conn = db.init_db()

    try:
        df = db.load_player_snapshots(conn, week=week, team_name=team_name)

        if df.empty:
            print(f"No data for {team_name} in week {week}")
            return

        # Sum by player
        df[stat] = pd.to_numeric(df[stat], errors='coerce')
        leaders = df.groupby(['player_name', 'player_type']).agg({stat: 'sum'}).reset_index()
        leaders = leaders.sort_values(stat, ascending=False)

        print(f"\n=== {team_name.upper()} - WEEK {week} {stat.upper()} ===\n")
        print(f"{'Player':<20} {'Type':<8} {stat.upper():>8}")
        print("-" * 40)

        for _, row in leaders.iterrows():
            val = row[stat] if row[stat] else 0
            print(f"{row['player_name']:<20} {row['player_type']:<8} {val:>8.1f}")

    finally:
        conn.close()

def main():
    parser = argparse.ArgumentParser(description="Quick fantasy baseball stats")
    parser.add_argument("--league", action='store_true', help="Show league leaders")
    parser.add_argument("--team", help="Show team leaders (e.g., 'Pooh\\'s On First')")
    parser.add_argument("--week", type=int, default=1, help="Week to analyze")
    parser.add_argument("--stat", default='hr', help="Stat to analyze (hr, r, rbi, k, era, etc.)")
    parser.add_argument("--limit", type=int, default=10, help="Top N players")

    args = parser.parse_args()

    if args.league:
        league_leaders_by_stat(args.week, args.stat, args.limit)
    elif args.team:
        team_leaders_by_stat(args.week, args.stat, args.team)
    else:
        print("Use --league or --team flag")
        parser.print_help()

if __name__ == "__main__":
    main()
