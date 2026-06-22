"""Parse individual matchup detail pages for player stats"""

from bs4 import BeautifulSoup


def parse_matchup_details(page_source, team_id, expected_teams=None):
    """Extract ALL team totals from matchup detail page.

    Args:
        page_source: HTML from matchup detail page
        team_id: The team ID being viewed (for reference, but we extract all teams)
        expected_teams: Optional list of expected team names (for validation)

    Returns:
        dict with 'all_teams' key containing list of dicts with team name and stats
    """
    soup = BeautifulSoup(page_source, 'html.parser')

    teams_data = []

    # Find the table containing team names and stats
    # Look for a table where first column has team names (full names like "Pooh's On First")
    tables = soup.find_all('table')

    # Known team names to search for
    known_teams = [
        'Phoenix Coyotes', 'The Big Gamblino', "Pooh's On First",
        'The Chicago Orphans', 'Pittsburgh Piglets', 'Pittsburgh Pirates',
        'Seattle Dumpers', 'Lets Go Bucs', 'Cronen-Zone', 'All Betts Are Off'
    ]

    # Find the table with team totals (first column should have full team names)
    totals_table = None
    for table in tables:
        rows = table.find_all('tr')
        if len(rows) > 1:
            # Check if row 1 has a team name in first cell
            first_row_cells = rows[1].find_all(['td', 'th'])
            if first_row_cells:
                first_cell_text = first_row_cells[0].get_text(strip=True)
                if any(team_name in first_cell_text for team_name in known_teams):
                    totals_table = table
                    break

    if not totals_table:
        return {'all_teams': []}

    # Extract all teams from the table
    totals_rows = totals_table.find_all('tr')

    for row_idx, row in enumerate(totals_rows[1:]):  # Skip header row
        cells = row.find_all(['td', 'th'])
        if not cells:
            continue

        team_name = cells[0].get_text(strip=True)

        # Only extract if it's a known team name
        if not any(known_team in team_name for known_team in known_teams):
            continue

        stats = {}
        # Extract stats from cells (skip the team name cell)
        stat_headers = ['R', 'HR', 'RBI', 'SB', 'AVG', 'OPS', 'K', 'QS', 'SV', 'HD', 'ERA', 'WHIP']
        for i, header in enumerate(stat_headers):
            if i + 1 < len(cells):
                stats[header] = cells[i + 1].get_text(strip=True)

        teams_data.append({
            'name': team_name,
            'stats': stats
        })

    return {'all_teams': teams_data}


def _extract_batter_stats(roster_table, stats_table, matchup_data, team_type):
    """Extract batter information and stats"""
    roster_rows = roster_table.find_all('tr')[2:]  # Skip header rows
    stats_rows = stats_table.find_all('tr')[2:]  # Skip header rows

    batters = []

    for roster_row, stats_row in zip(roster_rows, stats_rows):
        roster_cells = roster_row.find_all(['td', 'th'])
        stats_cells = stats_row.find_all(['td', 'th'])

        if len(roster_cells) < 2 or len(stats_cells) < 2:
            continue

        # Extract player name from roster
        player_link = roster_cells[1].find('a')
        player_name = player_link.get_text(strip=True) if player_link else roster_cells[1].get_text(strip=True)

        if not player_name or player_name.lower() == 'empty':
            continue

        # Extract stats
        stat_values = [cell.get_text(strip=True) for cell in stats_cells[1:]]

        batter = {
            'name': player_name,
            'slot': roster_cells[0].get_text(strip=True),
            'stats': {
                'H/AB': stat_values[0] if len(stat_values) > 0 else '0',
                'R': stat_values[1] if len(stat_values) > 1 else '0',
                'HR': stat_values[2] if len(stat_values) > 2 else '0',
                'RBI': stat_values[3] if len(stat_values) > 3 else '0',
                'BB': stat_values[4] if len(stat_values) > 4 else '0',
                'SB': stat_values[5] if len(stat_values) > 5 else '0',
                'AVG': stat_values[6] if len(stat_values) > 6 else '0',
                'OPS': stat_values[7] if len(stat_values) > 7 else '0'
            }
        }

        batters.append(batter)

    if team_type == 'team':
        matchup_data['team_batters'] = batters
    else:
        matchup_data['opponent_batters'] = batters


def _extract_pitcher_stats(roster_table, stats_table, matchup_data, team_type):
    """Extract pitcher information and stats"""
    roster_rows = roster_table.find_all('tr')[2:]  # Skip header rows
    stats_rows = stats_table.find_all('tr')[2:]  # Skip header rows

    pitchers = []

    for roster_row, stats_row in zip(roster_rows, stats_rows):
        roster_cells = roster_row.find_all(['td', 'th'])
        stats_cells = stats_row.find_all(['td', 'th'])

        if len(roster_cells) < 2 or len(stats_cells) < 2:
            continue

        # Extract player name from roster
        player_link = roster_cells[1].find('a')
        player_name = player_link.get_text(strip=True) if player_link else roster_cells[1].get_text(strip=True)

        if not player_name or player_name.lower() == 'empty':
            continue

        # Extract stats
        stat_values = [cell.get_text(strip=True) for cell in stats_cells[1:]]

        pitcher = {
            'name': player_name,
            'slot': roster_cells[0].get_text(strip=True),
            'stats': {
                'IP': stat_values[0] if len(stat_values) > 0 else '0',
                'H': stat_values[1] if len(stat_values) > 1 else '0',
                'ER': stat_values[2] if len(stat_values) > 2 else '0',
                'BB': stat_values[3] if len(stat_values) > 3 else '0',
                'K': stat_values[4] if len(stat_values) > 4 else '0',
                'QS': stat_values[5] if len(stat_values) > 5 else '0',
                'SV': stat_values[6] if len(stat_values) > 6 else '0',
                'HD': stat_values[7] if len(stat_values) > 7 else '0',
                'ERA': stat_values[8] if len(stat_values) > 8 else '0',
                'WHIP': stat_values[9] if len(stat_values) > 9 else '0'
            }
        }

        pitchers.append(pitcher)

    if team_type == 'team':
        matchup_data['team_pitchers'] = pitchers
    else:
        matchup_data['opponent_pitchers'] = pitchers
