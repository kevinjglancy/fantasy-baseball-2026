"""Hardcoded owner mapping for league teams"""

OWNER_MAP = {
    # Based on standings page
    # 1. Phoenix Coyotes (Josh Oremland, Zach Oremland)
    # 2. The Big Gamblino (Ted Zhang)
    # 3. Pooh's On First (Kevin Glancy)
    # 4. The Chicago Orphans (Patrick Booth)
    # 5. Pittsburgh Piglets (Julien Piet)
    # 6. Pittsburgh Pirates (David Glancy)
    # 7. Seattle Dumpers (Devesh Rathee)
    # 8. Lets Go Bucs (Sherri Glancy)
    # 9. Cronen-Zone (Andrew Stephens)
    # 10. All Betts Are Off (Andrew Powell)
}

# Map team names to owners (will be populated from standings scrape or manually)
TEAM_NAME_TO_OWNER = {
    'Phoenix Coyotes': 'Josh Oremland, Zach Oremland',
    'The Big Gamblino': 'Ted Zhang',
    "Pooh's On First": 'Kevin Glancy',
    'The Chicago Orphans': 'Patrick Booth',
    'Pittsburgh Piglets': 'Julien Piet',
    'Pittsburgh Pirates': 'David Glancy',
    'Seattle Dumpers': 'Devesh Rathee',
    'Lets Go Bucs': 'Sherri Glancy',
    'Cronen-Zone': 'Andrew Stephens',
    'All Betts Are Off': 'Andrew Powell'
}


def get_owner_by_name(team_name):
    """Get owner name for a team by team name"""
    return TEAM_NAME_TO_OWNER.get(team_name, 'Unknown')


def get_owner_by_id(team_id):
    """Get owner name for a team by team ID"""
    return OWNER_MAP.get(team_id, 'Unknown')
