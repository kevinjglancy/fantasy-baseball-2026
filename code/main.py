#!/usr/bin/env python3
"""Fantasy Baseball League Analyzer"""

import sys
import os
import json
import argparse
import time
import re
from urllib.parse import unquote
from dotenv import load_dotenv
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from analyzer import WeeklyAnalyzer
from standings_parser import parse_standings
from matchup_detail_parser import parse_matchup_details
from owner_map import get_owner_by_name
from driver_utils import setup_driver_with_cookies

load_dotenv()

def fetch_league_data(league_id, year):
    """Fetch league data from ESPN using Selenium"""
    print(f"Fetching league {league_id} for {year}...\n")

    swid = os.getenv('SWID')
    espn_s2 = os.getenv('ESPN_S2')

    if not swid or not espn_s2:
        raise ValueError("SWID or ESPN_S2 not found in .env file")

    espn_s2 = unquote(espn_s2)

    driver = setup_driver_with_cookies(swid, espn_s2)

    try:

        # Fetch standings and extract owner mapping
        owner_map, roto_standings = fetch_standings(league_id, driver)

        # Fetch scoreboard
        print("Fetching scoreboard...")
        url = f"https://fantasy.espn.com/baseball/league/scoreboard?leagueId={league_id}"
        driver.get(url)

        # Wait for matchup data to render
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'li.ScoreboardScoreCell__Item'))
        )
        time.sleep(2)

        # Parse scoreboard HTML
        soup = BeautifulSoup(driver.page_source, 'html.parser')

        # Extract league info
        league_name = "League"
        title_elem = soup.find('title')
        if title_elem:
            league_name = title_elem.text.split(' - ')[0]

        # Extract matchups
        matchups = []
        matchup_containers = soup.find_all('div', class_='matchup-score')

        for container in matchup_containers:
            team_items = container.find_all('li', class_='ScoreboardScoreCell__Item')
            if len(team_items) < 2:
                continue

            matchup = {'home': {}, 'away': {}, 'matchupPeriodId': 1}

            for idx, item in enumerate(team_items[:2]):
                team_name_elem = item.find('div', class_='ScoreCell__TeamName')
                team_name = team_name_elem.get_text(strip=True) if team_name_elem else 'Unknown'

                score_elem = item.find('div', class_=lambda x: x and 'ScoreCell__Score' in x)
                score_str = score_elem.get_text(strip=True) if score_elem else '0'

                try:
                    score = float(score_str.split('-')[0])
                except (ValueError, IndexError):
                    score = 0

                # Extract team ID from link href
                team_id = None
                links = item.find_all('a')
                for link in links:
                    href = link.get('href', '')
                    if 'teamId=' in href:
                        match = re.search(r'teamId=(\d+)', href)
                        if match:
                            team_id = int(match.group(1))
                            break

                team_data = {'name': team_name, 'totalPoints': score, 'teamId': team_id or idx}

                item_classes = item.get('class', [])
                if 'ScoreboardScoreCell__Item--away' in item_classes:
                    matchup['away'] = team_data
                elif 'ScoreboardScoreCell__Item--home' in item_classes:
                    matchup['home'] = team_data

            if matchup['home'].get('name') and matchup['away'].get('name'):
                matchups.append(matchup)

        # Build owner map from team names (using hardcoded mapping)
        from owner_map import TEAM_NAME_TO_OWNER
        owner_map_from_names = {}
        for matchup in matchups:
            away_name = matchup.get('away', {}).get('name')
            home_name = matchup.get('home', {}).get('name')
            if away_name:
                owner_map_from_names[away_name] = TEAM_NAME_TO_OWNER.get(away_name, 'Unknown')
            if home_name:
                owner_map_from_names[home_name] = TEAM_NAME_TO_OWNER.get(home_name, 'Unknown')

        # Return structured data (matchup details will be fetched separately by week)
        return {
            'league': {'id': league_id, 'name': league_name},
            'teams': [],
            'schedule': matchups,
            'owner_map': owner_map_from_names,
            'roto_standings': roto_standings
        }

    finally:
        driver.quit()


def fetch_standings(league_id, driver):
    """Fetch league standings page and extract owner mapping"""
    print("Fetching standings...")
    url = f"https://fantasy.espn.com/baseball/league/standings?leagueId={league_id}"
    driver.get(url)
    time.sleep(2)

    page_source = driver.page_source
    owner_map, roto_standings = parse_standings(page_source)

    print(f"✓ Found {len(owner_map)} teams with owner info")
    return owner_map, roto_standings


def fetch_matchup_details(league_id, matchup, week, driver):
    """Fetch matchup detail page using fantasycast (works for all weeks)"""
    away_id = matchup.get('away', {}).get('teamId')
    home_id = matchup.get('home', {}).get('teamId')

    if not away_id or not home_id:
        return None

    # Use fantasycast with view=matchup (works for both current and past weeks)
    url = (f"https://fantasy.espn.com/baseball/fantasycast?leagueId={league_id}"
           f"&matchupPeriodId={week}&seasonId=2026&teamId={away_id}&view=matchup")

    try:
        driver.get(url)
        time.sleep(1)  # Brief wait for page load

        page_source = driver.page_source
        details = parse_matchup_details(page_source, away_id)
        return details
    except Exception as e:
        return None


def fetch_week_details(league_id, week, matchups, driver):
    """Fetch matchup details for a specific week"""
    print(f"\nFetching matchup details for week {week}...")
    matchup_details = {}

    for i, matchup in enumerate(matchups):
        away_name = matchup.get('away', {}).get('name')
        home_name = matchup.get('home', {}).get('name')
        print(f"  Matchup {i+1}/{len(matchups)}: {away_name} vs {home_name}")

        details = fetch_matchup_details(league_id, matchup, week, driver)
        if details:
            key = f"{matchup['away'].get('teamId')}_vs_{matchup['home'].get('teamId')}"
            matchup_details[key] = details

    print(f"✓ Retrieved {len(matchup_details)} matchup detail sets")
    return matchup_details


def main():
    parser = argparse.ArgumentParser(description="Fantasy Baseball League Analyzer")
    parser.add_argument("--league-id", type=int, help="ESPN league ID")
    parser.add_argument("--year", type=int, default=2026, help="League year (default 2026)")
    parser.add_argument("--week", type=int, help="Week to analyze (default: current week)")
    args = parser.parse_args()

    league_id = args.league_id
    if not league_id:
        league_id = input("Enter your ESPN league ID: ")

    year = args.year
    if not args.league_id:
        year_input = input(f"Enter the year (default {year}): ")
        if year_input:
            year = int(year_input)

    week = args.week

    try:
        league_data = fetch_league_data(int(league_id), int(year))
        league_name = league_data.get('league', {}).get('name', 'League')
        print(f"✓ Retrieved league: {league_name}")

        # If week is specified, fetch matchup details for that week
        if week:
            # Need to re-initialize driver to fetch week details
            swid = os.getenv('SWID')
            espn_s2 = unquote(os.getenv('ESPN_S2'))

            driver = setup_driver_with_cookies(swid, espn_s2)

            try:

                matchup_details = fetch_week_details(int(league_id), week, league_data.get('schedule', []), driver)
                league_data['matchup_details'] = matchup_details
            finally:
                driver.quit()

        analyzer = WeeklyAnalyzer(league_data)
        analyzer.analyze_current_week(week)

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    main()
