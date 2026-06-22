#!/usr/bin/env python3
"""Validate collected player stats against ESPN's displayed matchup stats."""

import os
import sys
import argparse
from datetime import date
from urllib.parse import unquote

import db
from driver_utils import setup_driver_with_cookies
from dotenv import load_dotenv
from selenium import webdriver
from bs4 import BeautifulSoup

load_dotenv()

def fetch_espn_matchup_stats(league_id: int, matchup_period: int, scoring_period: int) -> dict:
    """Fetch team stats from ESPN matchup page."""
    swid = os.getenv('SWID')
    espn_s2 = unquote(os.getenv('ESPN_S2'))

    options = webdriver.ChromeOptions()
    options.add_argument('--headless')
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')

    driver = webdriver.Chrome(options=options)
    driver.get("https://fantasy.espn.com")
    driver.add_cookie({'name': 'SWID', 'value': swid})
    driver.add_cookie({'name': 'espn_s2', 'value': espn_s2})

    url = (f"https://fantasy.espn.com/baseball/boxscore?leagueId={league_id}"
           f"&matchupPeriodId={matchup_period}&seasonId=2026&teamId=1&scoringPeriodId={scoring_period}&view=matchup")
    driver.get(url)

    import time
    time.sleep(3)

    soup = BeautifulSoup(driver.page_source, 'html.parser')
    driver.quit()

    tables = soup.find_all('table')
    if len(tables) < 3:
        return {}

    stats_by_team = {}
    table = tables[2]
    rows = table.find_all('tr')

    for row in rows:
        cells = row.find_all(['td', 'th'])
        if cells and len(cells) > 2:
            content = [c.get_text(strip=True) for c in cells]
            team_name = content[0]
            if team_name and team_name not in ('team', 'Team'):
                try:
                    def safe_float(val):
                        if not val:
                            return None
                        try:
                            return float(val)
                        except:
                            return None

                    def safe_int(val):
                        return int(val) if val and val.lstrip('-').isdigit() else None

                    # Column order: team, R, HR, RBI, SB, AVG, OPS, K, QS, SV, HD, ERA, WHIP, Score
                    stats_by_team[team_name] = {
                        'R': safe_int(content[1]) if len(content) > 1 else None,
                        'HR': safe_int(content[2]) if len(content) > 2 else None,
                        'RBI': safe_int(content[3]) if len(content) > 3 else None,
                        'SB': safe_int(content[4]) if len(content) > 4 else None,
                        'AVG': safe_float(content[5]) if len(content) > 5 else None,
                        'OPS': safe_float(content[6]) if len(content) > 6 else None,
                        'K': safe_int(content[7]) if len(content) > 7 else None,
                        'QS': safe_int(content[8]) if len(content) > 8 else None,
                        'SV': safe_int(content[9]) if len(content) > 9 else None,
                        'HD': safe_int(content[10]) if len(content) > 10 else None,
                        'ERA': safe_float(content[11]) if len(content) > 11 else None,
                        'WHIP': safe_float(content[12]) if len(content) > 12 else None,
                    }
                except (ValueError, IndexError):
                    pass

    return stats_by_team

def main():
    parser = argparse.ArgumentParser(description="Validate collected stats against ESPN")
    parser.add_argument("--league-id", type=int, required=True, help="ESPN league ID")
    parser.add_argument("--matchup-period", type=int, required=True, help="Matchup period (week)")
    parser.add_argument("--scoring-period", type=int, required=True, help="Scoring period (day of week)")
    parser.add_argument("--start-date", required=True, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end-date", required=True, help="End date (YYYY-MM-DD)")
    args = parser.parse_args()

    conn = db.init_db()

    print("Fetching ESPN stats...")
    espn_stats = fetch_espn_matchup_stats(args.league_id, args.matchup_period, args.scoring_period)

    print("\nValidation Results")
    print("=" * 80)

    all_match = True
    for team_name, espn_expected in espn_stats.items():
        collected = db.aggregate_team_stats(conn, team_name, args.start_date, args.end_date)

        print(f"\n{team_name}:")
        print(f"  Counting Stats:")
        for stat in ['R', 'HR', 'RBI', 'SB', 'K', 'QS', 'SV', 'HD']:
            espn_val = espn_expected.get(stat)
            collected_val = collected.get(stat)

            if espn_val is None and collected_val == 0:
                match = "✅"
            else:
                match = "✅" if espn_val == collected_val else "❌"
                if espn_val != collected_val:
                    all_match = False

            espn_str = str(espn_val) if espn_val is not None else "N/A"
            print(f"    {stat:3}: ESPN={espn_str:>4}  Collected={collected_val:>4}  {match}")

        print(f"  Rate Stats:")
        for stat in ['AVG', 'ERA', 'WHIP']:
            espn_val = espn_expected.get(stat)
            collected_val = collected.get(stat)

            if collected_val is not None and espn_val is not None:
                match = "✅" if abs(espn_val - collected_val) < 0.001 else "❌"
                if abs(espn_val - collected_val) >= 0.001:
                    all_match = False
            else:
                match = "❓"

            espn_str = f"{espn_val:.4f}" if espn_val is not None else "N/A"
            collected_str = f"{collected_val:.4f}" if collected_val is not None else "N/A"
            print(f"    {stat:3}: ESPN={espn_str:>7}  Collected={collected_str:>7}  {match}")

    print("\n" + "=" * 80)
    if all_match:
        print("✅ All stats match!")
        sys.exit(0)
    else:
        print("❌ Some stats don't match")
        sys.exit(1)

def validate_week(league_id: int, matchup_period: int, conn, driver=None) -> bool:
    """Validate a completed week's team totals against ESPN.

    Args:
        league_id: ESPN league ID
        matchup_period: ESPN matchup period (week)
        conn: Database connection
        driver: Optional Selenium driver to reuse (if not provided, creates new one)

    Returns True if all stats match, False otherwise
    """
    from espn_schedule import get_week_date_range
    from datetime import datetime

    start_date_str, end_date_str = get_week_date_range(matchup_period)

    print(f"\n{'='*100}")
    print(f"VALIDATING WEEK {matchup_period} ({start_date_str} to {end_date_str})")
    print(f"{'='*100}\n")

    # Fetch ESPN stats (use last day of week as scoring_period)
    end_date = datetime.strptime(end_date_str, '%Y-%m-%d')
    # ESPN scoringPeriodId is 1-indexed from March 25, 2026
    from datetime import date
    season_start = date(2026, 3, 25)
    scoring_period = (end_date.date() - season_start).days + 1

    espn_stats = fetch_espn_matchup_stats(league_id, matchup_period, scoring_period)

    if not espn_stats:
        print(f"❌ Could not fetch ESPN stats for week {matchup_period}")
        return False

    # Check each team
    all_match = True
    print(f"{'Team':<30}{'R':>4}{'HR':>4}{'RBI':>4}{'SB':>4}{'K':>4}{'QS':>4}{'SV':>4}{'HD':>4}{'Status':>8}\n")

    for team_name, espn_expected in espn_stats.items():
        # Use last day of week to get cumulative week total
        collected = db.aggregate_team_stats(conn, team_name, end_date_str, end_date_str)

        # Compare counting stats
        match = True
        for stat in ['R', 'HR', 'RBI', 'SB', 'K', 'QS', 'SV', 'HD']:
            espn_val = espn_expected.get(stat)
            collected_val = collected.get(stat)
            if espn_val is not None and espn_val != collected_val:
                match = False
                all_match = False

        status = "✅" if match else "❌"

        print(f"{team_name:<30}{collected.get('R', 0):>4}{collected.get('HR', 0):>4}{collected.get('RBI', 0):>4}{collected.get('SB', 0):>4}{collected.get('K', 0):>4}{collected.get('QS', 0):>4}{collected.get('SV', 0):>4}{collected.get('HD', 0):>4}{status:>8}")

    print(f"\n{'='*100}")
    if all_match:
        print(f"✅ Week {matchup_period} validation PASSED\n")
    else:
        print(f"❌ Week {matchup_period} validation FAILED\n")

    return all_match

if __name__ == "__main__":
    main()
