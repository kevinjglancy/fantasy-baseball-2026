import sqlite3
from datetime import date
import pandas as pd
from typing import Optional, Union, Set

DB_PATH = 'fantasy_baseball.db'

def init_db(db_path: str = DB_PATH) -> sqlite3.Connection:
    """Initialize SQLite database with schema. Returns connection."""
    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Daily roto standings snapshot
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS standings_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date   TEXT NOT NULL,
            team_name       TEXT NOT NULL,
            owner           TEXT,
            wins            INTEGER,
            losses          INTEGER,
            ties            INTEGER,
            pct             REAL,
            games_back      REAL,
            r               REAL,
            hr              REAL,
            rbi             REAL,
            sb              REAL,
            avg             REAL,
            ops             REAL,
            k               REAL,
            qs              REAL,
            sv              REAL,
            hd              REAL,
            era             REAL,
            whip            REAL,
            UNIQUE(snapshot_date, team_name)
        )
    ''')
    # Add record columns to existing DBs that predate this schema
    for col, typedef in [('wins', 'INTEGER'), ('losses', 'INTEGER'),
                         ('ties', 'INTEGER'), ('pct', 'REAL'), ('games_back', 'REAL')]:
        try:
            cursor.execute(f'ALTER TABLE standings_snapshots ADD COLUMN {col} {typedef}')
        except sqlite3.OperationalError:
            pass  # column already exists

    # Daily player stats snapshot (cumulative week-to-date)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS player_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date   TEXT NOT NULL,
            week            INTEGER NOT NULL,
            team_name       TEXT NOT NULL,
            player_name     TEXT NOT NULL,
            player_type     TEXT NOT NULL,
            slot            TEXT,
            h_ab            TEXT,
            r               REAL,
            hr              REAL,
            rbi             REAL,
            bb              REAL,
            sb              REAL,
            avg             REAL,
            ops             REAL,
            ip              REAL,
            h               REAL,
            er              REAL,
            k               REAL,
            qs              REAL,
            sv              REAL,
            hd              REAL,
            era             REAL,
            whip            REAL,
            UNIQUE(snapshot_date, week, team_name, player_name)
        )
    ''')

    # Weekly matchup team totals snapshot
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS team_week_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date   TEXT NOT NULL,
            week            INTEGER NOT NULL,
            team_name       TEXT NOT NULL,
            matchup_opponent TEXT,
            r               REAL,
            hr              REAL,
            rbi             REAL,
            sb              REAL,
            avg             REAL,
            ops             REAL,
            k               REAL,
            qs              REAL,
            sv              REAL,
            hd              REAL,
            era             REAL,
            whip            REAL,
            score           REAL,
            UNIQUE(snapshot_date, week, team_name)
        )
    ''')

    # Season-to-date daily team snapshots (for roto leaderboard)
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS team_day_snapshots (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_date   TEXT NOT NULL,
            team_name       TEXT NOT NULL,
            r               REAL,
            hr              REAL,
            rbi             REAL,
            sb              REAL,
            avg             REAL,
            ops             REAL,
            k               REAL,
            qs              REAL,
            sv              REAL,
            hd              REAL,
            era             REAL,
            whip            REAL,
            UNIQUE(snapshot_date, team_name)
        )
    ''')

    # Collection audit log
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS collection_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            collected_at    TEXT NOT NULL,
            collection_type TEXT NOT NULL,
            week            INTEGER,
            snapshot_date   TEXT NOT NULL,
            status          TEXT NOT NULL,
            note            TEXT
        )
    ''')

    conn.commit()
    return conn

def _to_float(val: Optional[str]) -> Optional[float]:
    """Convert string to float, handling None and invalid values."""
    if val is None or val == '':
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None

def insert_standings_snapshot(conn: sqlite3.Connection, date_str: str, roto_standings: list) -> int:
    """Insert daily standings snapshot. Returns row count inserted."""
    cursor = conn.cursor()
    inserted = 0

    for team_data in roto_standings:
        name = team_data.get('name')
        owner = team_data.get('owner')
        stats = team_data.get('stats', {})
        record = team_data.get('record', {})

        cursor.execute('''
            INSERT OR REPLACE INTO standings_snapshots
            (snapshot_date, team_name, owner,
             wins, losses, ties, pct, games_back,
             r, hr, rbi, sb, avg, ops, k, qs, sv, hd, era, whip)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ''', (
            date_str,
            name,
            owner,
            record.get('wins'),
            record.get('losses'),
            record.get('ties'),
            record.get('pct'),
            record.get('games_back'),
            _to_float(stats.get('R')),
            _to_float(stats.get('HR')),
            _to_float(stats.get('RBI')),
            _to_float(stats.get('SB')),
            _to_float(stats.get('AVG')),
            _to_float(stats.get('OPS')),
            _to_float(stats.get('K')),
            _to_float(stats.get('QS')),
            _to_float(stats.get('SV')),
            _to_float(stats.get('HD')),
            _to_float(stats.get('ERA')),
            _to_float(stats.get('WHIP'))
        ))
        inserted += 1

    conn.commit()
    return inserted

def insert_team_week_snapshot(conn: sqlite3.Connection, date_str: str, week: int,
                               team_name: str, opponent_name: Optional[str], stats: dict) -> None:
    """Insert weekly team totals snapshot."""
    cursor = conn.cursor()

    cursor.execute('''
        INSERT OR REPLACE INTO team_week_snapshots
        (snapshot_date, week, team_name, matchup_opponent, r, hr, rbi, sb, avg, ops, k, qs, sv, hd, era, whip, score)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        date_str,
        week,
        team_name,
        opponent_name,
        _to_float(stats.get('R')),
        _to_float(stats.get('HR')),
        _to_float(stats.get('RBI')),
        _to_float(stats.get('SB')),
        _to_float(stats.get('AVG')),
        _to_float(stats.get('OPS')),
        _to_float(stats.get('K')),
        _to_float(stats.get('QS')),
        _to_float(stats.get('SV')),
        _to_float(stats.get('HD')),
        _to_float(stats.get('ERA')),
        _to_float(stats.get('WHIP')),
        _to_float(stats.get('Score'))
    ))
    conn.commit()

def insert_player_snapshot(conn: sqlite3.Connection, date_str: str, week: int,
                           team_name: str, player: dict, player_type: str) -> None:
    """Insert player stats snapshot. player_type is 'batter' or 'pitcher'."""
    cursor = conn.cursor()

    player_name = player.get('name', '')
    slot = player.get('slot', '')
    stats = player.get('stats', {})

    # Map parsed stats to schema columns
    h_ab = stats.get('H/AB', stats.get('H_AB'))  # handle both formats
    r = _to_float(stats.get('R'))
    hr = _to_float(stats.get('HR'))
    rbi = _to_float(stats.get('RBI'))
    bb = _to_float(stats.get('BB'))
    sb = _to_float(stats.get('SB'))
    avg = _to_float(stats.get('AVG'))
    ops = _to_float(stats.get('OPS'))
    ip = _to_float(stats.get('IP'))
    h = _to_float(stats.get('H'))
    er = _to_float(stats.get('ER'))
    k = _to_float(stats.get('K'))
    qs = _to_float(stats.get('QS'))
    sv = _to_float(stats.get('SV'))
    hd = _to_float(stats.get('HD'))
    era = _to_float(stats.get('ERA'))
    whip = _to_float(stats.get('WHIP'))

    cursor.execute('''
        INSERT OR REPLACE INTO player_snapshots
        (snapshot_date, week, team_name, player_name, player_type, slot,
         h_ab, r, hr, rbi, bb, sb, avg, ops, ip, h, er, k, qs, sv, hd, era, whip)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        date_str, week, team_name, player_name, player_type, slot,
        h_ab, r, hr, rbi, bb, sb, avg, ops, ip, h, er, k, qs, sv, hd, era, whip
    ))
    conn.commit()

def log_collection(conn: sqlite3.Connection, collection_type: str, week: Optional[int],
                   snapshot_date: str, status: str, note: str = '') -> None:
    """Log a collection event to the audit trail."""
    from datetime import datetime
    cursor = conn.cursor()

    cursor.execute('''
        INSERT INTO collection_log
        (collected_at, collection_type, week, snapshot_date, status, note)
        VALUES (?, ?, ?, ?, ?, ?)
    ''', (
        datetime.utcnow().isoformat(),
        collection_type,
        week,
        snapshot_date,
        status,
        note
    ))
    conn.commit()

def get_last_collected_date(conn: sqlite3.Connection, collection_type: str) -> Union[str, None]:
    """Return the most recent snapshot_date where status='success' for the given collection_type."""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT MAX(snapshot_date) FROM collection_log
        WHERE collection_type = ? AND status = 'success'
    ''', (collection_type,))
    result = cursor.fetchone()
    return result[0] if result and result[0] else None

def get_collected_weeks(conn: sqlite3.Connection) -> Set[int]:
    """Return the set of week numbers that have been successfully collected."""
    cursor = conn.cursor()
    cursor.execute('''
        SELECT DISTINCT week FROM collection_log
        WHERE collection_type = 'matchup_week' AND status = 'success' AND week IS NOT NULL
    ''')
    return {row[0] for row in cursor.fetchall()}

def load_standings_snapshots(conn: sqlite3.Connection, start_date: Optional[str] = None,
                             end_date: Optional[str] = None):
    """Load standings snapshots as a DataFrame. Dates are 'YYYY-MM-DD' format."""
    query = 'SELECT * FROM standings_snapshots WHERE 1=1'
    params = []

    if start_date:
        query += ' AND snapshot_date >= ?'
        params.append(start_date)
    if end_date:
        query += ' AND snapshot_date <= ?'
        params.append(end_date)

    query += ' ORDER BY snapshot_date, team_name'
    return pd.read_sql_query(query, conn, params=params)

def load_team_week_snapshots(conn: sqlite3.Connection, week: Optional[int] = None):
    """Load team week snapshots as a DataFrame."""
    if week is not None:
        query = 'SELECT * FROM team_week_snapshots WHERE week = ? ORDER BY snapshot_date, team_name'
        return pd.read_sql_query(query, conn, params=[week])
    else:
        query = 'SELECT * FROM team_week_snapshots ORDER BY snapshot_date, week, team_name'
        return pd.read_sql_query(query, conn)

def load_player_snapshots(conn: sqlite3.Connection, week: int,
                          team_name: Optional[str] = None):
    """Load player snapshots as a DataFrame."""
    if team_name:
        query = 'SELECT * FROM player_snapshots WHERE week = ? AND team_name = ? ORDER BY snapshot_date, player_name'
        return pd.read_sql_query(query, conn, params=[week, team_name])
    else:
        query = 'SELECT * FROM player_snapshots WHERE week = ? ORDER BY snapshot_date, team_name, player_name'
        return pd.read_sql_query(query, conn, params=[week])

def insert_team_day_snapshot(conn: sqlite3.Connection, snapshot_date: str, team_name: str, stats: dict) -> None:
    """Insert season-to-date team stats for a single day."""
    cursor = conn.cursor()

    cursor.execute('''
        INSERT OR REPLACE INTO team_day_snapshots
        (snapshot_date, team_name, r, hr, rbi, sb, avg, ops, k, qs, sv, hd, era, whip)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        snapshot_date,
        team_name,
        _to_float(stats.get('R')),
        _to_float(stats.get('HR')),
        _to_float(stats.get('RBI')),
        _to_float(stats.get('SB')),
        _to_float(stats.get('AVG')),
        _to_float(stats.get('OPS')),
        _to_float(stats.get('K')),
        _to_float(stats.get('QS')),
        _to_float(stats.get('SV')),
        _to_float(stats.get('HD')),
        _to_float(stats.get('ERA')),
        _to_float(stats.get('WHIP'))
    ))
    conn.commit()

def insert_team_day_snapshot_from_dict(conn: sqlite3.Connection, snapshot_date: str, team_name: str, stats: dict) -> None:
    """Insert team stats from matchup parser output (handles string format from ESPN).

    This is used for official team totals from matchup detail pages.
    Stats dict contains string values like '.2632' for AVG, '31' for R, etc.
    """
    cursor = conn.cursor()

    cursor.execute('''
        INSERT OR REPLACE INTO team_day_snapshots
        (snapshot_date, team_name, r, hr, rbi, sb, avg, ops, k, qs, sv, hd, era, whip)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    ''', (
        snapshot_date,
        team_name,
        _to_float(stats.get('R')),
        _to_float(stats.get('HR')),
        _to_float(stats.get('RBI')),
        _to_float(stats.get('SB')),
        _to_float(stats.get('AVG')),
        _to_float(stats.get('OPS')),
        _to_float(stats.get('K')),
        _to_float(stats.get('QS')),
        _to_float(stats.get('SV')),
        _to_float(stats.get('HD')),
        _to_float(stats.get('ERA')),
        _to_float(stats.get('WHIP'))
    ))
    conn.commit()

def compute_season_to_date(conn: sqlite3.Connection, team_name: str, as_of_date: str,
                           espn_weeks: dict) -> dict:
    """Compute season-to-date stats for a team as of a given date.

    Args:
        conn: Database connection
        team_name: Team name
        as_of_date: Target date (YYYY-MM-DD)
        espn_weeks: Dict mapping matchupPeriodId -> (start_date, end_date)

    Returns dict with season totals for R, HR, RBI, SB, AVG, OPS, K, QS, SV, HD, ERA, WHIP
    """
    from espn_schedule import date_to_matchup_period, get_week_date_range

    # Determine current week
    current_period = date_to_matchup_period(as_of_date)

    # Sum completed weeks
    completed_weeks_stats = {'R': 0, 'HR': 0, 'RBI': 0, 'SB': 0, 'K': 0, 'QS': 0, 'SV': 0, 'HD': 0,
                             'total_h': 0, 'total_ab': 0, 'total_bb': 0, 'total_k_pitcher': 0,
                             'total_ip': 0, 'total_er': 0, 'pitcher_h': 0, 'pitcher_bb': 0}

    # For each completed week before current, get last day stats
    for week_num in range(1, current_period):
        last_day = get_week_date_range(week_num)[1]
        week_stats = aggregate_team_stats(conn, team_name, last_day, last_day)

        for stat in ['R', 'HR', 'RBI', 'SB', 'K', 'QS', 'SV', 'HD']:
            completed_weeks_stats[stat] += week_stats.get(stat, 0)

    # Get this week's stats (from start of week to as_of_date)
    week_start, _ = get_week_date_range(current_period)
    this_week_stats = aggregate_team_stats(conn, team_name, week_start, as_of_date)

    # Combine: counting stats just sum, rate stats need recomputation from components
    season_stats = {
        'R': completed_weeks_stats['R'] + this_week_stats.get('R', 0),
        'HR': completed_weeks_stats['HR'] + this_week_stats.get('HR', 0),
        'RBI': completed_weeks_stats['RBI'] + this_week_stats.get('RBI', 0),
        'SB': completed_weeks_stats['SB'] + this_week_stats.get('SB', 0),
        'K': completed_weeks_stats['K'] + this_week_stats.get('K', 0),
        'QS': completed_weeks_stats['QS'] + this_week_stats.get('QS', 0),
        'SV': completed_weeks_stats['SV'] + this_week_stats.get('SV', 0),
        'HD': completed_weeks_stats['HD'] + this_week_stats.get('HD', 0),
        'AVG': this_week_stats.get('AVG'),  # From current week aggregate
        'OPS': this_week_stats.get('OPS'),  # From current week aggregate
        'ERA': this_week_stats.get('ERA'),  # From current week aggregate
        'WHIP': this_week_stats.get('WHIP'),  # From current week aggregate
    }

    return season_stats

def load_team_day_snapshots(conn: sqlite3.Connection, team_name: Optional[str] = None,
                           start_date: Optional[str] = None, end_date: Optional[str] = None):
    """Load team daily snapshots as a DataFrame."""
    query = 'SELECT * FROM team_day_snapshots WHERE 1=1'
    params = []

    if team_name:
        query += ' AND team_name = ?'
        params.append(team_name)
    if start_date:
        query += ' AND snapshot_date >= ?'
        params.append(start_date)
    if end_date:
        query += ' AND snapshot_date <= ?'
        params.append(end_date)

    query += ' ORDER BY snapshot_date, team_name'
    return pd.read_sql_query(query, conn, params=params)

def _convert_baseball_ip(ip_value: float) -> float:
    """Convert baseball innings notation to decimal IP.

    In baseball, IP is notated as X.Y where:
    - X = full innings
    - Y = outs in the partial inning (0, 1, or 2)

    So: 1.0 = 1.0 IP, 1.1 = 1.333... IP, 1.2 = 1.666... IP, 2.1 = 2.333... IP
    """
    if not ip_value:
        return 0.0

    full_innings = int(ip_value)
    outs = round((ip_value - full_innings) * 10)  # Get 0, 1, or 2

    return full_innings + (outs / 3.0)


def aggregate_team_stats(conn: sqlite3.Connection, team_name: str,
                         start_date: Optional[str] = None, end_date: Optional[str] = None) -> dict:
    """Aggregate team stats from player snapshots (both batters and pitchers).

    Args:
        conn: Database connection
        team_name: Team name (e.g., "All Betts Are Off")
        start_date: Start date (YYYY-MM-DD), optional - if not provided, aggregates all
        end_date: End date (YYYY-MM-DD), optional

    Returns dict with counting stats and calculated rate stats (AVG, ERA, WHIP).
    """
    cursor = conn.cursor()

    query = '''
        SELECT
            SUM(CASE WHEN player_type = 'batter' AND r IS NOT NULL THEN r ELSE 0 END) as r,
            SUM(CASE WHEN player_type = 'batter' AND hr IS NOT NULL THEN hr ELSE 0 END) as hr,
            SUM(CASE WHEN player_type = 'batter' AND rbi IS NOT NULL THEN rbi ELSE 0 END) as rbi,
            SUM(CASE WHEN player_type = 'batter' AND sb IS NOT NULL THEN sb ELSE 0 END) as sb,
            SUM(CASE WHEN player_type = 'pitcher' AND k IS NOT NULL THEN k ELSE 0 END) as k,
            SUM(CASE WHEN player_type = 'pitcher' AND qs IS NOT NULL THEN qs ELSE 0 END) as qs,
            SUM(CASE WHEN player_type = 'pitcher' AND sv IS NOT NULL THEN sv ELSE 0 END) as sv,
            SUM(CASE WHEN player_type = 'pitcher' AND hd IS NOT NULL THEN hd ELSE 0 END) as hd
        FROM player_snapshots
        WHERE team_name = ?
    '''

    params = [team_name]

    if start_date:
        query += ' AND snapshot_date >= ?'
        params.append(start_date)

    if end_date:
        query += ' AND snapshot_date <= ?'
        params.append(end_date)

    cursor.execute(query, params)
    result = cursor.fetchone()

    stats = {'R': 0, 'HR': 0, 'RBI': 0, 'SB': 0, 'K': 0, 'QS': 0, 'SV': 0, 'HD': 0, 'AVG': None, 'OPS': None, 'ERA': None, 'WHIP': None}

    if result:
        stats['R'] = int(result[0]) if result[0] else 0
        stats['HR'] = int(result[1]) if result[1] else 0
        stats['RBI'] = int(result[2]) if result[2] else 0
        stats['SB'] = int(result[3]) if result[3] else 0
        stats['K'] = int(result[4]) if result[4] else 0
        stats['QS'] = int(result[5]) if result[5] else 0
        stats['SV'] = int(result[6]) if result[6] else 0
        stats['HD'] = int(result[7]) if result[7] else 0

    # Now calculate ERA and WHIP from raw pitcher data
    params_pitcher = [team_name]
    query_pitcher = 'SELECT ip, er, h, bb FROM player_snapshots WHERE team_name = ? AND player_type = "pitcher" AND ip IS NOT NULL'

    if start_date:
        query_pitcher += ' AND snapshot_date >= ?'
        params_pitcher.append(start_date)
    if end_date:
        query_pitcher += ' AND snapshot_date <= ?'
        params_pitcher.append(end_date)

    cursor.execute(query_pitcher, params_pitcher)

    total_ip_decimal = 0.0
    total_er = 0.0
    total_h = 0.0
    total_bb = 0.0

    for row in cursor.fetchall():
        ip_val = row[0] if row[0] else 0
        er_val = row[1] if row[1] else 0
        h_val = row[2] if row[2] else 0
        bb_val = row[3] if row[3] else 0

        total_ip_decimal += _convert_baseball_ip(ip_val)
        total_er += er_val
        total_h += h_val
        total_bb += bb_val

    if total_ip_decimal > 0:
        stats['ERA'] = round((total_er / total_ip_decimal) * 9, 3)
        stats['WHIP'] = round((total_h + total_bb) / total_ip_decimal, 3)

    # Now get batter stats for AVG and OPS (need to parse H/AB and calculate from individual player stats)
    params_batter = [team_name]
    query_batter = 'SELECT h_ab, bb, ops FROM player_snapshots WHERE team_name = ? AND player_type = "batter" AND h_ab IS NOT NULL AND h_ab != "--/--"'

    if start_date:
        query_batter += ' AND snapshot_date >= ?'
        params_batter.append(start_date)
    if end_date:
        query_batter += ' AND snapshot_date <= ?'
        params_batter.append(end_date)

    cursor.execute(query_batter, params_batter)

    total_h = 0
    total_ab = 0
    total_bb = 0
    total_bases = 0.0

    for row in cursor.fetchall():
        h_ab_str = row[0]
        bb = row[1] if row[1] else 0
        ops = row[2] if row[2] else 0

        if '/' in h_ab_str:
            try:
                h, ab = h_ab_str.split('/')
                h = int(h)
                ab = int(ab)
                total_h += h
                total_ab += ab
                total_bb += bb

                # Calculate SLG from OPS: OPS = OBP + SLG, so SLG = OPS - OBP
                # OBP ≈ (H + BB) / (AB + BB)
                if (ab + bb) > 0:
                    obp = (h + bb) / (ab + bb)
                    slg = ops - obp
                    total_bases += slg * ab
            except (ValueError, IndexError):
                pass

    if total_ab > 0:
        stats['AVG'] = round(total_h / total_ab, 4)

        # Calculate team OBP and SLG from totals (not from individual player OPS averages)
        if (total_ab + total_bb) > 0:
            team_obp = (total_h + total_bb) / (total_ab + total_bb)
            team_slg = total_bases / total_ab if total_ab > 0 else 0
            stats['OPS'] = round(team_obp + team_slg, 4)

    return stats
