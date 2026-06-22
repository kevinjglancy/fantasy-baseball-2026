#!/usr/bin/env python3
"""Validate collection completeness and retry missing dates."""

import os
import sys
import argparse
import subprocess
import time
from datetime import date, timedelta
from urllib.parse import unquote
from dotenv import load_dotenv

import db
from driver_utils import setup_driver_with_cookies
from selenium import webdriver

EXPECTED_TEAMS = {
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
}

def check_missing_dates(start_date: str, end_date: str) -> dict:
    """Check which teams are missing data for which dates.

    Returns: {date: [missing_teams]} or {} if all complete
    """
    conn = db.init_db()
    cursor = conn.cursor()

    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    missing_by_date = {}

    while current <= end:
        date_str = str(current)

        cursor.execute('''
            SELECT DISTINCT team_name FROM player_snapshots
            WHERE snapshot_date = ?
        ''', (date_str,))

        teams_with_data = {row[0] for row in cursor.fetchall()}
        missing = EXPECTED_TEAMS - teams_with_data

        if missing:
            missing_by_date[date_str] = sorted(list(missing))
            print(f"❌ {date_str}: Missing {len(missing)} teams: {', '.join(missing)}")
        else:
            print(f"✓ {date_str}: All 10 teams present")

        current += timedelta(days=1)

    conn.close()
    return missing_by_date

def retry_collection(league_id: int, start_date: str, end_date: str, max_retries: int = 2):
    """Retry collection for date range and validate."""
    load_dotenv()

    for attempt in range(max_retries):
        print(f"\n{'='*80}")
        print(f"Collection attempt {attempt + 1}/{max_retries}")
        print(f"{'='*80}")

        # Run collection
        cmd = f"python collect_daily.py --league-id {league_id} --start-date {start_date} --end-date {end_date}"
        result = subprocess.run(cmd, shell=True, cwd=os.path.dirname(os.path.abspath(__file__)))

        if result.returncode != 0:
            print(f"❌ Collection failed with exit code {result.returncode}")
            continue

        # Wait a moment for DB to sync
        time.sleep(2)

        # Check what's still missing
        missing = check_missing_dates(start_date, end_date)

        if not missing:
            print(f"\n✅ All data complete after {attempt + 1} attempt(s)")
            return True

        if attempt < max_retries - 1:
            print(f"\n⏳ Retrying collection (attempt {attempt + 2}/{max_retries})...")
            time.sleep(3)

    if missing:
        print(f"\n⚠️ Still missing data after {max_retries} attempts:")
        for date_str, teams in sorted(missing.items()):
            print(f"   {date_str}: {', '.join(teams)}")
        return False

    return True

def main():
    parser = argparse.ArgumentParser(description="Validate collection completeness")
    parser.add_argument("--league-id", type=int, required=True, help="ESPN league ID")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    parser.add_argument("--retry", action="store_true", help="Auto-retry missing dates")
    parser.add_argument("--max-retries", type=int, default=2, help="Max retry attempts")
    args = parser.parse_args()

    print(f"\n{'='*80}")
    print(f"COLLECTION VALIDATION: {args.start_date} to {args.end_date}")
    print(f"{'='*80}\n")

    # Check completeness
    missing = check_missing_dates(args.start_date, args.end_date)

    if not missing:
        print(f"\n✅ All data complete!")
        sys.exit(0)

    if not args.retry:
        print(f"\n❌ Missing data detected. Run with --retry to auto-retry collection")
        sys.exit(1)

    # Retry collection
    success = retry_collection(args.league_id, args.start_date, args.end_date, args.max_retries)
    sys.exit(0 if success else 1)

if __name__ == "__main__":
    main()
