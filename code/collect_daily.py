#!/usr/bin/env python3
"""Daily data collection for fantasy baseball standings and player stats."""

import os
import sys
import argparse
import time
from datetime import date, timedelta
from urllib.parse import unquote
from typing import List, Dict
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

import db
from driver_utils import setup_driver_with_cookies
from standings_parser import fetch_standings
from boxscore_parser import parse_boxscore_daily
from matchup_detail_parser import parse_matchup_details
from owner_map import TEAM_NAME_TO_OWNER
from espn_schedule import date_to_matchup_period, get_week_date_range
import validate_matchup

load_dotenv()

SEASON_START_DATE = date(2026, 3, 25)  # Day before first game day

def date_to_scoring_period(target_date: date) -> int:
    """Convert a date to ESPN's scoringPeriodId (day of season, 1-indexed)."""
    days_elapsed = (target_date - SEASON_START_DATE).days
    return days_elapsed + 1

def scoring_period_to_date(scoring_period: int) -> date:
    """Convert scoringPeriodId back to date."""
    return SEASON_START_DATE + timedelta(days=scoring_period - 1)

def compute_current_week(target_date: date) -> int:
    """Compute current week number from season start date."""
    days_elapsed = (target_date - SEASON_START_DATE).days
    week = (days_elapsed // 7) + 1
    return max(1, week)

def get_matchup_schedule(league_id: int, driver: webdriver.Chrome) -> List[Dict]:
    """Fetch scoreboard and extract matchup pairs with team IDs."""
    print("Fetching matchup schedule...")
    url = f"https://fantasy.espn.com/baseball/league/scoreboard?leagueId={league_id}"
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
                    import re
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

    print(f"  Found {len(matchups)} matchups")
    return matchups

def collect_matchup_stats(league_id: int, week: int, matchups: list,
                          driver: webdriver.Chrome, conn, snapshot_date: str) -> bool:
    """Fetch official team stats from matchup detail pages using matchup parser.

    This is the PRIMARY method for collecting matchup stats (team totals).
    Extracts ALL teams from each page (may contain multiple matchups).
    """
    print(f"Collecting matchup stats for week {week} (official team totals)...")
    try:
        stats_collected = set()  # Track which teams we've already stored

        # Calculate scoring period: first week (2) = 19, then +7 for each week after
        scoring_period = 19 + (week - 2) * 7

        for matchup in matchups:
            away_id = matchup.get('away', {}).get('teamId')
            away_name = matchup.get('away', {}).get('name')
            home_name = matchup.get('home', {}).get('name')

            if not away_id or not away_name or not home_name:
                continue

            # Fetch matchup detail page with correct scoring period
            url = (f"https://fantasy.espn.com/baseball/boxscore?leagueId={league_id}"
                   f"&matchupPeriodId={week}&scoringPeriodId={scoring_period}&seasonId=2026&teamId={away_id}&view=matchup")

            driver.get(url)
            time.sleep(1)

            # Parse ALL team totals from the page
            result = parse_matchup_details(driver.page_source, away_id, expected_teams=[away_name, home_name])

            # Store all teams found on this page
            for team_data in result.get('all_teams', []):
                team_name = team_data['name']
                if team_name not in stats_collected:  # Avoid duplicates
                    stats = team_data['stats']
                    db.insert_team_day_snapshot_from_dict(conn, snapshot_date, team_name, stats)
                    stats_collected.add(team_name)

        db.log_collection(conn, 'matchup_stats', week, snapshot_date, 'success')
        print(f"  ✓ Collected stats for {len(stats_collected)} teams")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        db.log_collection(conn, 'matchup_stats', week, snapshot_date, 'error', str(e))
        return False


def compute_and_store_day_totals(conn, snapshot_date: str) -> None:
    """Compute season-to-date stats for all teams on a given day and store in team_day_snapshots.

    DEPRECATED: This was the old method that aggregated player stats.
    Now we get official team totals directly from matchup_stats collection above.
    """
    from espn_schedule import ESPN_WEEKS

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

    for team_name in teams:
        try:
            season_stats = db.compute_season_to_date(conn, team_name, snapshot_date, ESPN_WEEKS)
            db.insert_team_day_snapshot(conn, snapshot_date, team_name, season_stats)
        except Exception as e:
            print(f"  ⚠️ Error computing season totals for {team_name}: {e}")

def collect_standings(league_id: int, swid: str, espn_s2: str, conn,
                     snapshot_date: str) -> bool:
    """Fetch and store standings snapshot via ESPN API (no browser needed)."""
    print(f"Collecting standings for {snapshot_date}...")
    try:
        _, roto_standings = fetch_standings(league_id, swid, espn_s2)
        db.insert_standings_snapshot(conn, snapshot_date, roto_standings)
        db.log_collection(conn, 'standings', None, snapshot_date, 'success')
        print(f"  ✓ Stored {len(roto_standings)} teams")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        db.log_collection(conn, 'standings', None, snapshot_date, 'error', str(e))
        return False

def get_matchup_schedule_for_week(league_id: int, matchup_period: int, driver: webdriver.Chrome) -> List[Dict]:
    """Fetch matchup schedule for a specific week (including historical weeks)."""
    print(f"Fetching matchup schedule for week {matchup_period}...")
    url = f"https://fantasy.espn.com/baseball/league/scoreboard?leagueId={league_id}&matchupPeriodId={matchup_period}"
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
                    import re
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

def collect_matchup_week(league_id: int, week: int, matchups: list,
                        driver: webdriver.Chrome, conn, snapshot_date: str, scoring_period: int) -> bool:
    """Fetch and store player stats for a specific day using boxscore."""
    print(f"Collecting week {week} (period {scoring_period}) player stats...")
    try:
        stats_collected = 0

        for matchup in matchups:
            away_id = matchup.get('away', {}).get('teamId')
            home_id = matchup.get('home', {}).get('teamId')
            away_name = matchup.get('away', {}).get('name')
            home_name = matchup.get('home', {}).get('name')

            if not away_id or not home_id:
                continue

            # Fetch boxscore for away team with specific scoring period (daily stats)
            url = (f"https://fantasy.espn.com/baseball/boxscore?leagueId={league_id}"
                   f"&matchupPeriodId={week}&seasonId=2026&teamId={away_id}&scoringPeriodId={scoring_period}")
            driver.get(url)
            time.sleep(1)

            away_data = parse_boxscore_daily(driver.page_source, away_id, team_name=away_name)

            # Store away team player stats
            for batter in away_data.get('batters', []):
                db.insert_player_snapshot(conn, snapshot_date, week, away_name, batter, 'batter')
                stats_collected += 1

            for pitcher in away_data.get('pitchers', []):
                db.insert_player_snapshot(conn, snapshot_date, week, away_name, pitcher, 'pitcher')
                stats_collected += 1

            # Fetch boxscore for home team with specific scoring period (daily stats)
            url = (f"https://fantasy.espn.com/baseball/boxscore?leagueId={league_id}"
                   f"&matchupPeriodId={week}&seasonId=2026&teamId={home_id}&scoringPeriodId={scoring_period}")
            driver.get(url)
            time.sleep(1)

            home_data = parse_boxscore_daily(driver.page_source, home_id, team_name=home_name)

            # Store home team player stats
            for batter in home_data.get('batters', []):
                db.insert_player_snapshot(conn, snapshot_date, week, home_name, batter, 'batter')
                stats_collected += 1

            for pitcher in home_data.get('pitchers', []):
                db.insert_player_snapshot(conn, snapshot_date, week, home_name, pitcher, 'pitcher')
                stats_collected += 1

        db.log_collection(conn, 'matchup_week', week, snapshot_date, 'success')
        print(f"  ✓ Collected {stats_collected} player stats")
        return True
    except Exception as e:
        print(f"  ✗ Error: {e}")
        db.log_collection(conn, 'matchup_week', week, snapshot_date, 'error', str(e))
        return False

def main():
    parser = argparse.ArgumentParser(description="Collect daily fantasy baseball data")
    parser.add_argument("--league-id", type=int, required=True, help="ESPN league ID")
    parser.add_argument("--start-date", help="Start date for backfill (YYYY-MM-DD)")
    parser.add_argument("--end-date", help="End date (default today)")
    args = parser.parse_args()

    # Get credentials
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
        # 1. ALWAYS collect today's standings (always current, overwrite old ones)
        today_str = str(date.today())
        print(f"Collecting current standings...")
        collect_standings(args.league_id, swid, espn_s2, conn, today_str)

        # 2. Group dates by matchup period and collect by week
        print(f"\nCollecting daily matchup stats from {start_date} to {end_date}...\n")

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
                matchups = get_matchup_schedule_for_week(args.league_id, period, driver)
                print(f"✓ Found {len(matchups)} matchups for week {period}\n")

            # Collect data for this day
            snapshot_date = str(current_date)
            scoring_period = date_to_scoring_period(current_date)

            print(f"Date: {snapshot_date} (Week {period}, Period {scoring_period})")

            # PHASE 1: Collect official matchup stats (team totals from matchup detail pages)
            collect_matchup_stats(args.league_id, period, matchups, driver, conn, snapshot_date)

            # TODO: PHASE 2 (future): Collect player stats for cross-validation
            # collect_matchup_week(args.league_id, period, matchups, driver, conn, snapshot_date, scoring_period)

            # Validate week if we just completed it
            period_start, period_end = get_week_date_range(period)
            if snapshot_date == period_end:
                print(f"\n  Validating week {period}...")
                validate_matchup.validate_week(args.league_id, period, conn, driver)

            current_date += timedelta(days=1)

        print("\n✓ Collection complete")

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
