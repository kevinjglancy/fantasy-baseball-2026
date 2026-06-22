#!/usr/bin/env python3
"""Daily player stats collection - SEPARATE from team stats.

Collects individual player statistics for each day.
Uses boxscore parser to extract batter and pitcher stats.
Independent from team stats collection (collect_daily.py).
"""

import os
import sys
import argparse
import time
from datetime import date, timedelta
from urllib.parse import unquote
from typing import List, Dict
from dotenv import load_dotenv
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import db
from driver_utils import setup_driver_with_cookies
from boxscore_parser import parse_team_page_daily
from owner_map import TEAM_NAME_TO_OWNER
from espn_schedule import date_to_matchup_period, get_week_date_range

load_dotenv()

SEASON_START_DATE = date(2026, 3, 25)

def date_to_scoring_period(target_date: date) -> int:
    """Convert a date to ESPN's scoringPeriodId (1-indexed from season start).

    Formula: scoringPeriodId = (date - March 25, 2026).days + 1
    Example: April 6 = day 12 = period 13
    """
    days_elapsed = (target_date - SEASON_START_DATE).days
    scoring_period = days_elapsed + 1
    return scoring_period

def get_matchup_schedule(league_id: int, week: int, driver: webdriver.Chrome) -> List[Dict]:
    """Fetch scoreboard and extract matchup pairs with team IDs for a specific week."""
    from bs4 import BeautifulSoup
    import re

    print(f"  Fetching matchup schedule for week {week}...")
    url = f"https://fantasy.espn.com/baseball/league/scoreboard?leagueId={league_id}&matchupPeriodId={week}"
    driver.get(url)

    WebDriverWait(driver, 20).until(
        EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'li.ScoreboardScoreCell__Item'))
    )
    time.sleep(2)

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    matchups = []

    matchup_containers = soup.find_all('div', class_='matchup-score')
    for container in matchup_containers:
        team_items = container.find_all('li', class_='ScoreboardScoreCell__Item')
        if len(team_items) < 2:
            continue

        matchup = {'home': {}, 'away': {}}

        for idx, item in enumerate(team_items[:2]):
            team_name_elem = item.find('div', class_='ScoreCell__TeamName')
            team_name = team_name_elem.get_text(strip=True) if team_name_elem else 'Unknown'

            team_id = None
            links = item.find_all('a')
            for link in links:
                href = link.get('href', '')
                if 'teamId=' in href:
                    match = re.search(r'teamId=(\d+)', href)
                    if match:
                        team_id = int(match.group(1))
                        break

            team_data = {'name': team_name, 'teamId': team_id or idx}

            item_classes = item.get('class', [])
            if 'ScoreboardScoreCell__Item--away' in item_classes:
                matchup['away'] = team_data
            elif 'ScoreboardScoreCell__Item--home' in item_classes:
                matchup['home'] = team_data

        if matchup['home'].get('name') and matchup['away'].get('name'):
            matchups.append(matchup)

    return matchups

def collect_player_stats(league_id: int, week: int, matchups: list,
                        driver: webdriver.Chrome, conn, snapshot_date: str, scoring_period: int) -> bool:
    """Fetch individual player stats from team pages (statSplit=singleScoringPeriod).

    Uses individual team pages which are more reliable than boxscore pages.
    """
    print(f"  Collecting player stats for {snapshot_date}...")
    try:
        stats_collected = 0
        collected_teams = set()

        for matchup in matchups:
            for position in ['away', 'home']:
                team_id = matchup.get(position, {}).get('teamId')
                team_name = matchup.get(position, {}).get('name')

                if not team_id or team_name in collected_teams:
                    continue

                # Fetch team page for this scoring period
                url = (f"https://fantasy.espn.com/baseball/team?leagueId={league_id}"
                       f"&seasonId=2026&teamId={team_id}&scoringPeriodId={scoring_period}"
                       f"&statSplit=singleScoringPeriod")

                driver.get(url)
                time.sleep(1)  # Wait longer for page to fully load

                team_data = parse_team_page_daily(driver.page_source, team_id, team_name=team_name)

                # Store player stats
                for batter in team_data.get('batters', []):
                    db.insert_player_snapshot(conn, snapshot_date, week, team_name, batter, 'batter')
                    stats_collected += 1

                for pitcher in team_data.get('pitchers', []):
                    db.insert_player_snapshot(conn, snapshot_date, week, team_name, pitcher, 'pitcher')
                    stats_collected += 1

                collected_teams.add(team_name)

        db.log_collection(conn, 'player_stats', week, snapshot_date, 'success')
        print(f"    ✓ Collected {stats_collected} player records")
        return bool(stats_collected > 0)
    except Exception as e:
        print(f"    ✗ Error: {e}")
        db.log_collection(conn, 'player_stats', week, snapshot_date, 'error', str(e))
        return False

def main():
    parser = argparse.ArgumentParser(description="Collect daily player stats")
    parser.add_argument("--league-id", type=int, required=True, help="ESPN league ID")
    parser.add_argument("--start-date", help="Start date for collection (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (default today)")
    args = parser.parse_args()

    swid = os.getenv('SWID')
    espn_s2 = os.getenv('ESPN_S2')

    if not swid or not espn_s2:
        print("Error: SWID or ESPN_S2 not found in .env file", file=sys.stderr)
        sys.exit(1)

    espn_s2 = unquote(espn_s2)

    # Determine date range
    end_date = date.fromisoformat(args.end_date) if args.end_date else date.today()

    if args.start_date:
        start_date = date.fromisoformat(args.start_date)
        print(f"Backfill mode: {start_date} to {end_date}")
    else:
        start_date = end_date
        print(f"Collection date: {end_date}")

    # Initialize database
    conn = db.init_db()

    # Set up driver
    driver = setup_driver_with_cookies(swid, espn_s2)

    try:
        print(f"\nCollecting daily player stats from {start_date} to {end_date}...\n")

        current_date = start_date
        current_period = None
        matchups = None

        while current_date <= end_date:
            # Determine matchup period for this date
            try:
                period = date_to_matchup_period(current_date)
            except ValueError:
                print(f"⚠️ {current_date} not in any known ESPN week, skipping")
                current_date += timedelta(days=1)
                continue

            # If we've entered a new period, fetch matchups for that period
            if period != current_period:
                current_period = period
                period_start, period_end = get_week_date_range(period)
                print(f"\n{'='*70}")
                print(f"WEEK {period}: {period_start} to {period_end}")
                print(f"{'='*70}")
                matchups = get_matchup_schedule(args.league_id, period, driver)
                print(f"✓ Found {len(matchups)} matchups for week {period}\n")

            # Collect player data for this day
            snapshot_date = str(current_date)
            scoring_period = date_to_scoring_period(current_date)

            print(f"Date: {snapshot_date} (Week {period}, Period {scoring_period})")

            # Collect player stats for this date, with retry on 0 records
            success = False
            for attempt in range(1, 4):
                success = collect_player_stats(args.league_id, period, matchups, driver, conn, snapshot_date, scoring_period)
                if success:
                    if attempt > 1:
                        print(f"    ✓ Success on attempt {attempt}")
                    break
                elif attempt < 3:
                    print(f"    ⚠ Got 0 records, retrying... (attempt {attempt + 1}/3)")
                    time.sleep(5)  # Longer wait between retries
                    # Refresh driver to clear any stale state
                    try:
                        driver.refresh()
                        time.sleep(1)
                    except:
                        pass

            current_date += timedelta(days=1)

        print("\n✓ Player stats collection complete")

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        driver.quit()
        conn.close()

if __name__ == "__main__":
    main()
