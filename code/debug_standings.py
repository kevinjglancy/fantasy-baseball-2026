#!/usr/bin/env python3
"""Debug: load standings page and dismiss OneTrust consent popup."""

import os
import sys
import time
from urllib.parse import unquote
from bs4 import BeautifulSoup
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv
from driver_utils import setup_driver_with_cookies, dismiss_consent_if_present

load_dotenv()

LEAGUE_ID = 94668654

def check_for_teams(driver, label):
    soup = BeautifulSoup(driver.page_source, 'html.parser')
    text = soup.get_text(separator='\n', strip=True)
    found = [t for t in ["Pooh's", "Coyotes", "Gamblino", "Orphans", "Piglets", "Dumpers", "Cronen"] if t in text]
    print(f"  [{label}] Team names: {found or 'NONE'}")
    if found:
        print(f"\n=== PAGE TEXT (first 3000 chars) ===")
        print(text[:3000])
    return bool(found)


def main():
    swid = os.getenv('SWID')
    espn_s2 = os.getenv('ESPN_S2')
    if not swid or not espn_s2:
        print("Error: SWID or ESPN_S2 not in .env", file=sys.stderr)
        sys.exit(1)

    espn_s2 = unquote(espn_s2)

    standings_url = f"https://fantasy.espn.com/baseball/league/standings?leagueId={LEAGUE_ID}"

    driver = setup_driver_with_cookies(swid, espn_s2)
    try:
        print("Loading standings...")
        driver.get(standings_url)

        dismissed = dismiss_consent_if_present(driver)
        print(f"  Consent popup dismissed: {dismissed}")

        # Wait for at least one table row to appear (standings data)
        try:
            WebDriverWait(driver, 20).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'table tr'))
            )
            print("  Table row found, waiting 2s for full render...")
            time.sleep(2)
        except Exception:
            print("  Timed out waiting for table — saving HTML for inspection")
            with open('debug_standings.html', 'w') as f:
                f.write(driver.page_source)

        if check_for_teams(driver, "standings"):
            print("\nSUCCESS")
        else:
            print("\nFAILED — saving HTML")
            with open('debug_standings.html', 'w') as f:
                f.write(driver.page_source)
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
