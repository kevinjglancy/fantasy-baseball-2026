"""Fetch ESPN fantasy baseball standings directly from the ESPN API."""

import requests

STAT_ID_MAP = {
    20: 'R',
    5:  'HR',
    21: 'RBI',
    23: 'SB',
    2:  'AVG',
    18: 'OPS',
    48: 'K',
    63: 'QS',
    57: 'SV',
    60: 'HD',
    47: 'ERA',
    41: 'WHIP',
}

BASE_URL = 'https://lm-api-reads.fantasy.espn.com/apis/v3/games/flb/seasons/2026/segments/0/leagues'


def fetch_standings(league_id: int, swid: str, espn_s2: str):
    """Fetch current roto standings from the ESPN API.

    Returns (owner_map, roto_standings) with the same shape expected by
    db.insert_standings_snapshot:
      owner_map: {team_id: owner_name}
      roto_standings: [{'name': str, 'owner': str, 'stats': {R, HR, ...}}, ...]
    """
    cookies = {'SWID': swid, 'espn_s2': espn_s2}
    resp = requests.get(
        f'{BASE_URL}/{league_id}',
        params={'view': ['mTeam', 'mSettings']},
        cookies=cookies,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json()

    # Build SWID → "First Last" lookup from members
    member_names = {
        m['id']: f"{m.get('firstName', '')} {m.get('lastName', '')}".strip()
        for m in data.get('members', [])
    }

    owner_map = {}
    roto_standings = []

    for team in data.get('teams', []):
        team_id = team['id']
        team_name = team.get('name', f'Team {team_id}')

        primary_owner_id = team.get('primaryOwner') or (team.get('owners') or [None])[0]
        owner_name = member_names.get(primary_owner_id, 'Unknown')

        owner_map[team_id] = owner_name

        vbs = team.get('valuesByStat', {})
        stats = {
            name: vbs.get(str(stat_id))
            for stat_id, name in STAT_ID_MAP.items()
        }

        overall = (team.get('record') or {}).get('overall', {})
        record = {
            'wins':       overall.get('wins'),
            'losses':     overall.get('losses'),
            'ties':       overall.get('ties'),
            'pct':        overall.get('percentage'),
            'games_back': overall.get('gamesBack'),
        }

        roto_standings.append({
            'name':   team_name,
            'owner':  owner_name,
            'stats':  stats,
            'record': record,
        })

    return owner_map, roto_standings
