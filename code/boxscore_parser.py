"""Parse boxscore and team pages for daily player stats."""

from bs4 import BeautifulSoup
import re
from typing import Dict, List


def clean_player_name(raw_name):
    """Extract clean player name from text with team/position codes.

    Examples:
    - "Adley RutschmanBALC" -> "Adley Rutschman"
    - "Nick KurtzATH1B" -> "Nick Kurtz"
    """
    if not raw_name:
        return None

    # Remove position info (comma and what follows)
    if ',' in raw_name:
        raw_name = raw_name.split(',')[0].strip()

    # Split after the last lowercase letter
    last_lower = -1
    for i, c in enumerate(raw_name):
        if c.islower():
            last_lower = i

    if last_lower >= 0:
        return raw_name[:last_lower + 1].strip()

    return raw_name.strip()


def _find_team_tables(soup, team_name):
    """Find the table indices for a given team by locating their Box Score header.

    Args:
        soup: BeautifulSoup object
        team_name: The fantasy team name to find (e.g., "All Betts Are Off")

    Returns:
        Tuple of (batter_roster_idx, batter_stats_idx, pitcher_roster_idx, pitcher_stats_idx)
        or None if not found
    """
    # Find the span containing the team's Box Score header
    team_header = None
    for span in soup.find_all('span', class_='team-name'):
        if team_name in span.get_text(strip=True):
            team_header = span
            break

    if not team_header:
        return None

    # Find all tables on the page
    all_tables = soup.find_all('table')

    # Find the next table after this header (should be Batters roster)
    current = team_header.parent
    first_table = None
    for _ in range(20):
        next_table = current.find_next('table')
        if next_table:
            # Get the index of this table in all_tables
            try:
                table_idx = all_tables.index(next_table)
                if first_table is None:
                    first_table = table_idx
                    # The team's 4 tables should be consecutive: Batters, Batting, Pitchers, Pitching
                    return (table_idx, table_idx + 1, table_idx + 2, table_idx + 3)
            except ValueError:
                pass
            current = next_table.parent
        else:
            break

    return None


def parse_boxscore_daily(page_source, team_id, team_name=None):
    """Extract daily player stats from boxscore page (starters only, no bench).

    Args:
        page_source: HTML from boxscore page
        team_id: The team being viewed (currently unused)
        team_name: The fantasy team name (e.g., "All Betts Are Off", "Pooh's On First")
                   Used to locate the correct table set on the page

    Returns:
        dict with batters and pitchers stats for that day (starters only)
    """
    soup = BeautifulSoup(page_source, 'html.parser')

    data = {
        'batters': [],
        'pitchers': []
    }

    tables = soup.find_all('table')
    if len(tables) < 7:  # Need at least 7 tables
        return data

    # Find the correct table indices for this team using their Box Score header
    if team_name:
        table_indices = _find_team_tables(soup, team_name)
        if table_indices:
            batter_idx, batting_idx, pitcher_idx, pitching_idx = table_indices
            batter_roster_rows = tables[batter_idx].find_all('tr')
            batter_stats_rows = tables[batting_idx].find_all('tr')
            pitcher_roster_rows = tables[pitcher_idx].find_all('tr')
            pitcher_stats_rows = tables[pitching_idx].find_all('tr')
        else:
            # Fallback to first set if team name not found
            batter_roster_rows = tables[3].find_all('tr')
            batter_stats_rows = tables[4].find_all('tr')
            pitcher_roster_rows = tables[5].find_all('tr')
            pitcher_stats_rows = tables[6].find_all('tr')
    else:
        # Default to first set if no team name provided
        batter_roster_rows = tables[3].find_all('tr')
        batter_stats_rows = tables[4].find_all('tr')
        pitcher_roster_rows = tables[5].find_all('tr')
        pitcher_stats_rows = tables[6].find_all('tr')

    # Extract starting batters (skip bench and IL)
    batter_names = []
    for row in batter_roster_rows[2:]:  # Skip headers
        cells = row.find_all(['td', 'th'])
        if len(cells) >= 2:
            slot = cells[0].get_text(strip=True)
            player_raw = cells[1].get_text(strip=True)

            # Stop at bench/IL sections or empty rows
            if slot in ('Bench', 'IL') or not slot:
                break

            # Only include starters (non-empty slot)
            if slot and slot.upper() not in ('BENCH', 'IL'):
                clean_name = clean_player_name(player_raw)
                if clean_name and len(clean_name) > 2:
                    batter_names.append(clean_name)

    # Match batters with stats
    for idx, row in enumerate(batter_stats_rows[2:]):  # Skip headers
        cells = row.find_all(['td', 'th'])
        if len(cells) < 8:
            continue

        row_text = row.get_text(strip=True)
        if not row_text or row_text.startswith('Totals'):
            continue

        # Stop if we've gone past the number of starters
        if idx >= len(batter_names):
            break

        player_name = batter_names[idx]

        stat_values = [cell.get_text(strip=True) for cell in cells[:8]]

        batter = {
            'name': player_name,
            'stats': {
                'H/AB': stat_values[0] if len(stat_values) > 0 else '--',
                'R': stat_values[1] if len(stat_values) > 1 else '--',
                'HR': stat_values[2] if len(stat_values) > 2 else '--',
                'RBI': stat_values[3] if len(stat_values) > 3 else '--',
                'BB': stat_values[4] if len(stat_values) > 4 else '--',
                'SB': stat_values[5] if len(stat_values) > 5 else '--',
                'AVG': stat_values[6] if len(stat_values) > 6 else '--',
                'OPS': stat_values[7] if len(stat_values) > 7 else '--'
            }
        }
        data['batters'].append(batter)

    # Extract starting pitchers (skip bench, empty, and IL)
    pitcher_names = []
    for row in pitcher_roster_rows[2:]:  # Skip headers
        cells = row.find_all(['td', 'th'])
        if len(cells) >= 2:
            slot = cells[0].get_text(strip=True)
            player_raw = cells[1].get_text(strip=True)

            # Stop at bench/IL sections
            if slot in ('Bench', 'IL') or not slot:
                break

            # Skip empty slots
            if 'Empty' in player_raw or 'empty' in player_raw.lower():
                continue

            # Only include starters (non-empty slot, must be "P")
            if slot and slot.upper() == 'P':
                clean_name = clean_player_name(player_raw)
                if clean_name and len(clean_name) > 2:
                    pitcher_names.append(clean_name)

    # Match pitchers with stats
    for idx, row in enumerate(pitcher_stats_rows[2:]):  # Skip headers
        cells = row.find_all(['td', 'th'])
        if len(cells) < 10:
            continue

        row_text = row.get_text(strip=True)
        if not row_text or row_text.startswith('Totals'):
            continue

        # Stop if we've gone past the number of starters
        if idx >= len(pitcher_names):
            break

        player_name = pitcher_names[idx]

        stat_values = [cell.get_text(strip=True) for cell in cells[:10]]

        pitcher = {
            'name': player_name,
            'stats': {
                'IP': stat_values[0] if len(stat_values) > 0 else '--',
                'H': stat_values[1] if len(stat_values) > 1 else '--',
                'ER': stat_values[2] if len(stat_values) > 2 else '--',
                'BB': stat_values[3] if len(stat_values) > 3 else '--',
                'K': stat_values[4] if len(stat_values) > 4 else '--',
                'QS': stat_values[5] if len(stat_values) > 5 else '--',
                'SV': stat_values[6] if len(stat_values) > 6 else '--',
                'HD': stat_values[7] if len(stat_values) > 7 else '--',
                'ERA': stat_values[8] if len(stat_values) > 8 else '--',
                'WHIP': stat_values[9] if len(stat_values) > 9 else '--'
            }
        }
        data['pitchers'].append(pitcher)

    return data


def parse_team_page_daily(page_source: str, team_id: int, team_name: str = None) -> Dict:
    """Extract daily player stats from team page (statSplit=singleScoringPeriod).

    Team pages have structure: Batter Roster, Batter Stats, Pitcher Roster, Pitcher Stats
    Tables 0 & 1 are batting, Tables 2 & 3 are pitching.

    Args:
        page_source: HTML from team page
        team_id: The team ID (unused, kept for compatibility)
        team_name: The fantasy team name (unused, kept for compatibility)

    Returns:
        dict with batters and pitchers stats for that day
    """
    soup = BeautifulSoup(page_source, 'html.parser')

    data = {
        'batters': [],
        'pitchers': []
    }

    tables = soup.find_all('table')
    if len(tables) < 4:
        return data

    # Extract batter names from roster table (Table 0)
    batter_names = []
    batter_rows = tables[0].find_all('tr')[2:]  # Skip header rows
    for idx, row in enumerate(batter_rows):
        if idx >= 15:  # Hard limit: 15 active batters max
            break

        cells = row.find_all(['td', 'th'])
        if len(cells) >= 2:
            slot = cells[0].get_text(strip=True)
            player_raw = cells[1].get_text(strip=True)

            # Break on exact match for bench/IL - end of active batters (UTIL contains "IL", so use exact match)
            if slot in ('Bench', 'IL'):
                break

            # Keep empty slots as placeholder to stay index-aligned with stats table
            if 'Empty' in player_raw:
                batter_names.append('__Empty__')
                continue

            clean_name = clean_player_name(player_raw)
            if clean_name and len(clean_name) > 2:
                batter_names.append(clean_name)


    # Extract batter stats from stats table (Table 1), match by row index
    stat_rows = tables[1].find_all('tr')[2:]  # Skip header rows
    stat_idx = 0
    for row in stat_rows:
        if stat_idx >= len(batter_names):
            break

        cells = row.find_all(['td', 'th'])
        if len(cells) < 8:
            continue

        row_text = row.get_text(strip=True)
        # Skip totals and bench/IL rows
        if any(skip in row_text for skip in ['Total', 'Bench', 'IL']):
            continue

        stat_values = [cell.get_text(strip=True) for cell in cells[:8]]

        # If this slot was empty in the roster, consume the stats row without recording
        if batter_names[stat_idx] == '__Empty__':
            stat_idx += 1
            continue

        # Skip rows with no stats (--/--) without advancing — player didn't play
        if stat_values[0] == '--/--':
            stat_idx += 1
            continue

        batter = {
            'name': batter_names[stat_idx],
            'stats': {
                'H/AB': stat_values[0] if len(stat_values) > 0 else '--',
                'R': stat_values[1] if len(stat_values) > 1 else '--',
                'HR': stat_values[2] if len(stat_values) > 2 else '--',
                'RBI': stat_values[3] if len(stat_values) > 3 else '--',
                'BB': stat_values[4] if len(stat_values) > 4 else '--',
                'SB': stat_values[5] if len(stat_values) > 5 else '--',
                'AVG': stat_values[6] if len(stat_values) > 6 else '--',
                'OPS': stat_values[7] if len(stat_values) > 7 else '--'
            }
        }
        data['batters'].append(batter)
        stat_idx += 1

    # Extract pitcher names from roster table (Table 2)
    pitcher_names = []
    pitcher_rows = tables[2].find_all('tr')[2:]  # Skip header rows
    for idx, row in enumerate(pitcher_rows):
        if idx >= 15:  # Hard limit: 15 active pitchers max
            break

        cells = row.find_all(['td', 'th'])
        if len(cells) >= 2:
            slot = cells[0].get_text(strip=True)
            player_raw = cells[1].get_text(strip=True)

            # Break on exact match for bench/IL - end of active pitchers
            if slot in ('Bench', 'IL'):
                break

            # Keep empty slots as placeholder to stay index-aligned with stats table
            if 'Empty' in player_raw:
                pitcher_names.append('__Empty__')
                continue

            clean_name = clean_player_name(player_raw)
            if clean_name and len(clean_name) > 2:
                pitcher_names.append(clean_name)

    # Extract pitcher stats from stats table (Table 3), match by row index
    stat_rows = tables[3].find_all('tr')[2:]  # Skip header rows
    stat_idx = 0
    for row in stat_rows:
        if stat_idx >= len(pitcher_names):
            break

        cells = row.find_all(['td', 'th'])
        if len(cells) < 10:
            continue

        row_text = row.get_text(strip=True)
        # Skip totals and bench/IL rows
        if any(skip in row_text for skip in ['Total', 'Bench', 'IL']):
            continue

        stat_values = [cell.get_text(strip=True) for cell in cells[:10]]

        # If this slot was empty in the roster, consume the stats row without recording
        if pitcher_names[stat_idx] == '__Empty__':
            stat_idx += 1
            continue

        # Skip rows with no stats (--/-- in first stat) without advancing — pitcher didn't pitch
        if stat_values[0] == '--/--' or stat_values[0] == '--':
            stat_idx += 1
            continue

        pitcher = {
            'name': pitcher_names[stat_idx],
            'stats': {
                'IP': stat_values[0] if len(stat_values) > 0 else '--',
                'H': stat_values[1] if len(stat_values) > 1 else '--',
                'ER': stat_values[2] if len(stat_values) > 2 else '--',
                'BB': stat_values[3] if len(stat_values) > 3 else '--',
                'K': stat_values[4] if len(stat_values) > 4 else '--',
                'QS': stat_values[5] if len(stat_values) > 5 else '--',
                'SV': stat_values[6] if len(stat_values) > 6 else '--',
                'HD': stat_values[7] if len(stat_values) > 7 else '--',
                'ERA': stat_values[8] if len(stat_values) > 8 else '--',
                'WHIP': stat_values[9] if len(stat_values) > 9 else '--'
            }
        }
        data['pitchers'].append(pitcher)
        stat_idx += 1

    return data
