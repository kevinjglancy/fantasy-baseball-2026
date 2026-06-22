#!/usr/bin/env python3
"""Backfill weeks 3-12 with player stats and validate coverage.

For each week:
1. Collect all 7 days for all teams
2. Validate that every team has data every day
3. Validate that player stats aggregate to match official matchup stats
"""

import subprocess
import sqlite3
import argparse
from datetime import date, timedelta
from espn_schedule import get_week_date_range

def get_week_dates(week_num: int) -> tuple:
    """Get start and end date for a week."""
    start_date, end_date = get_week_date_range(week_num)
    return date.fromisoformat(str(start_date)), date.fromisoformat(str(end_date))

def validate_team_daily_coverage(week_num: int) -> bool:
    """Validate that every team has data every day of the week."""
    conn = sqlite3.connect('fantasy_baseball.db')
    cursor = conn.cursor()

    # Get week date range
    week_start, week_end = get_week_dates(week_num)
    num_days = (week_end - week_start).days + 1

    # Get all unique dates for this week
    cursor.execute('''
        SELECT DISTINCT snapshot_date FROM player_snapshots
        WHERE week = ?
        ORDER BY snapshot_date
    ''', (week_num,))

    dates_with_data = [row[0] for row in cursor.fetchall()]

    # Get all teams for this week
    cursor.execute('''
        SELECT DISTINCT team_name FROM player_snapshots
        WHERE week = ?
    ''', (week_num,))

    teams = [row[0] for row in cursor.fetchall()]

    print(f"\n{'='*100}")
    print(f"COVERAGE CHECK - Week {week_num}")
    print(f"{'='*100}\n")
    print(f"Expected: {num_days} days, {len(teams)} teams = {num_days * len(teams)} total combinations")
    print(f"Dates collected: {len(dates_with_data)}/7")

    # Check coverage for each team
    missing = []
    for team in sorted(teams):
        cursor.execute('''
            SELECT DISTINCT snapshot_date FROM player_snapshots
            WHERE week = ? AND team_name = ?
        ''', (week_num, team))

        team_dates = set(row[0] for row in cursor.fetchall())
        expected_dates = set(str(week_start + timedelta(days=i)) for i in range(num_days))
        missing_dates = expected_dates - team_dates

        if missing_dates:
            missing.append((team, sorted(missing_dates)))
            print(f"✗ {team:<25} MISSING: {', '.join(sorted(missing_dates))}")
        else:
            print(f"✓ {team:<25} Complete (all {num_days} days)")

    conn.close()

    if missing:
        print(f"\n⚠️  {len(missing)} teams have missing dates. Need to re-collect.")
        return False
    else:
        print(f"\n✓ All teams have complete daily coverage")
        return True

def validate_stats_match(week_num: int) -> bool:
    """Validate that player stats aggregate to match official matchup stats."""
    print(f"\nRunning full stats validation...")
    result = subprocess.run(
        ['python', 'validate_week_complete.py', '--week', str(week_num)],
        capture_output=True,
        text=True
    )
    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    # Check if validation passed (all ✓)
    return '✓' in result.stdout and ('✗' not in result.stdout or result.returncode == 0)

def backfill_week(league_id: int, week_num: int) -> bool:
    """Backfill a complete week with player stats."""
    week_start, week_end = get_week_dates(week_num)

    print(f"\n{'='*100}")
    print(f"BACKFILLING WEEK {week_num}: {week_start} to {week_end}")
    print(f"{'='*100}\n")

    # Collect player stats for all days
    cmd = [
        'python', 'collect_player_daily.py',
        '--league-id', str(league_id),
        '--start-date', str(week_start),
        '--end-date', str(week_end)
    ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    print(result.stdout)
    if result.stderr:
        print(result.stderr)

    if result.returncode != 0:
        print(f"✗ Collection failed for week {week_num}")
        return False

    # Validate coverage
    if not validate_team_daily_coverage(week_num):
        print(f"\n⚠️  Week {week_num} has missing data. Retry collection.")
        return False

    # Validate stats match
    if not validate_stats_match(week_num):
        print(f"\n⚠️  Week {week_num} stats don't fully match. Check validation output above.")
        return False

    print(f"\n✓ Week {week_num} complete and validated\n")
    return True

def main():
    parser = argparse.ArgumentParser(description="Backfill weeks with player stats")
    parser.add_argument("--league-id", type=int, required=True, help="ESPN league ID")
    parser.add_argument("--start-week", type=int, default=3, help="Start week (default: 3)")
    parser.add_argument("--end-week", type=int, default=12, help="End week (default: 12)")
    args = parser.parse_args()

    completed = []
    failed = []

    for week in range(args.start_week, args.end_week + 1):
        try:
            if backfill_week(args.league_id, week):
                completed.append(week)
            else:
                failed.append(week)
        except Exception as e:
            print(f"✗ Exception during week {week}: {e}")
            failed.append(week)

    # Summary
    print(f"\n{'='*100}")
    print(f"BACKFILL SUMMARY")
    print(f"{'='*100}")
    print(f"✓ Completed: {completed if completed else 'none'}")
    print(f"✗ Failed: {failed if failed else 'none'}")
    print(f"{'='*100}\n")

    if failed:
        print(f"⚠️  Please re-run backfill for weeks: {failed}")
        return 1
    else:
        print(f"✓ All weeks backfilled and validated")
        return 0

if __name__ == "__main__":
    import sys
    sys.exit(main())
