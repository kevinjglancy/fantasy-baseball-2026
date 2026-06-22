#!/usr/bin/env python3
"""Weekly fantasy baseball recap with trend analysis."""

import sys
import argparse
from datetime import datetime
from typing import Optional, List, Dict
import pandas as pd

import db

INFLECTION_THRESHOLDS = {
    'ERA': 0.50,
    'WHIP': 0.10,
    'AVG': 0.015,
    'OPS': 0.030,
    'HR': 2,
    'R': 3,
    'RBI': 3,
    'K': 4,
    'SB': 2,
    'QS': 1,
    'SV': 2,
    'HD': 2,
}

COUNTING_STATS = ['r', 'hr', 'rbi', 'sb', 'k', 'qs', 'sv', 'hd']
RATE_STATS = ['avg', 'ops', 'era', 'whip']
DISPLAY_STATS = ['r', 'hr', 'rbi', 'sb', 'avg', 'ops', 'k', 'qs', 'sv', 'era', 'whip']
DISPLAY_NAMES = {'r': 'R', 'hr': 'HR', 'rbi': 'RBI', 'sb': 'SB', 'avg': 'AVG', 'ops': 'OPS',
                 'k': 'K', 'qs': 'QS', 'sv': 'SV', 'era': 'ERA', 'whip': 'WHIP'}

def load_week_trend(conn, week: int) -> pd.DataFrame:
    """Load team week snapshots for a given week."""
    df = db.load_team_week_snapshots(conn, week=week)
    if df.empty:
        return df
    # Ensure snapshot_date is datetime
    df['snapshot_date'] = pd.to_datetime(df['snapshot_date'])
    df = df.sort_values(['snapshot_date', 'team_name']).reset_index(drop=True)
    return df

def compute_daily_deltas(trend_df: pd.DataFrame, team_name: str) -> pd.DataFrame:
    """Compute day-over-day stat changes for a team."""
    if trend_df.empty:
        return pd.DataFrame()

    team_df = trend_df[trend_df['team_name'] == team_name].copy()
    if team_df.empty:
        return pd.DataFrame()

    team_df = team_df.sort_values('snapshot_date').reset_index(drop=True)

    # Build result with deltas
    deltas = []
    for stat in DISPLAY_STATS:
        if stat not in team_df.columns:
            continue

        stat_col = team_df[stat].astype(float, errors='ignore')
        stat_deltas = stat_col.diff()

        for idx in range(1, len(team_df)):
            date_val = team_df.iloc[idx]['snapshot_date']
            prev_val = stat_col.iloc[idx - 1]
            new_val = stat_col.iloc[idx]
            delta = stat_deltas.iloc[idx]

            if pd.notna(delta) and delta != 0:
                deltas.append({
                    'date': date_val,
                    'stat': stat,
                    'prev_value': prev_val,
                    'new_value': new_val,
                    'delta': delta
                })

    return pd.DataFrame(deltas) if deltas else pd.DataFrame()

def detect_inflection_points(delta_df: pd.DataFrame) -> List[Dict]:
    """Find stat changes that exceed thresholds."""
    if delta_df.empty:
        return []

    inflections = []
    for _, row in delta_df.iterrows():
        stat = row['stat']
        delta = abs(row['delta'])
        # Look up threshold using uppercase stat name
        threshold = INFLECTION_THRESHOLDS.get(stat.upper(), 0)

        if delta >= threshold:
            inflections.append({
                'date': row['date'],
                'stat': row['stat'],
                'team': None,  # Will be filled by caller
                'prev': row['prev_value'],
                'new': row['new_value'],
                'delta': row['delta'],
                'direction': 'up' if row['delta'] > 0 else 'down'
            })

    return sorted(inflections, key=lambda x: x['date'])

def get_player_contribution(conn, week: int, team_name: str, stat: str,
                           date_str: str, prev_date_str: Optional[str] = None) -> str:
    """Attribute a stat change to a specific player."""
    player_df = db.load_player_snapshots(conn, week=week, team_name=team_name)
    if player_df.empty:
        return ""

    player_df['snapshot_date'] = pd.to_datetime(player_df['snapshot_date'])

    # Map stat column names (they may have underscores in DB)
    stat_col = stat.lower().replace('-', '_')
    if stat == 'H/AB':
        stat_col = 'h_ab'

    # Find players who contributed most to the change
    current_day = player_df[player_df['snapshot_date'] == pd.to_datetime(date_str)]
    if current_day.empty:
        return ""

    if prev_date_str:
        prev_day = player_df[player_df['snapshot_date'] == pd.to_datetime(prev_date_str)]
    else:
        prev_day = pd.DataFrame()

    # Simple heuristic: top performer on current day for that stat
    if stat in ['ERA', 'WHIP']:
        # For pitching stats, look for pitchers
        pitchers = current_day[current_day['player_type'] == 'pitcher'].copy()
        if not pitchers.empty and stat_col in pitchers.columns:
            top = pitchers.nlargest(1, stat_col)
            if not top.empty:
                player = top.iloc[0]
                return f"{player['player_name']} ({stat}: {player.get(stat_col, 'N/A')})"
    elif stat in ['HR', 'RBI', 'AVG']:
        # For batting stats, look for batters
        batters = current_day[current_day['player_type'] == 'batter'].copy()
        if not batters.empty and stat_col in batters.columns:
            top = batters.nlargest(1, stat_col)
            if not top.empty:
                player = top.iloc[0]
                return f"{player['player_name']} ({stat}: {player.get(stat_col, 'N/A')})"

    return ""

def format_day_by_day_table(trend_df: pd.DataFrame, team_name: str) -> str:
    """Format day-by-day stats as a table."""
    if trend_df.empty:
        return "  [No data available]"

    team_df = trend_df[trend_df['team_name'] == team_name].copy()
    if team_df.empty:
        return "  [No data available]"

    team_df = team_df.sort_values('snapshot_date').reset_index(drop=True)

    # Build header
    header = "  Date       |"
    for stat in DISPLAY_STATS:
        if stat in team_df.columns:
            header += f" {DISPLAY_NAMES[stat]:>5}"
    header += "\n  " + "-" * 70

    # Build rows
    rows = [header]
    for idx, row in team_df.iterrows():
        date_obj = pd.to_datetime(row['snapshot_date'])
        date_str = date_obj.strftime('%b %d (%a)')
        line = f"  {date_str:11} |"

        for stat in DISPLAY_STATS:
            if stat in team_df.columns:
                val = row[stat]
                if pd.isna(val):
                    line += f" {'—':>5}"
                elif isinstance(val, float):
                    # Format appropriately based on stat type
                    if stat in ['AVG', 'OPS', 'ERA', 'WHIP']:
                        line += f" {val:>5.2f}"
                    else:
                        line += f" {int(val):>5}"
                else:
                    line += f" {str(val):>5}"

        rows.append(line)

    return "\n".join(rows)

def format_matchup_recap(conn, week: int, matchup: dict) -> str:
    """Format a complete matchup recap with trends."""
    away_team = matchup.get('away', {}).get('name', 'Unknown')
    home_team = matchup.get('home', {}).get('name', 'Unknown')

    # Load trends for both teams
    trend_df = load_week_trend(conn, week)
    if trend_df.empty:
        return f"No data available for {away_team} vs {home_team}"

    # Compute deltas
    away_deltas = compute_daily_deltas(trend_df, away_team)
    home_deltas = compute_daily_deltas(trend_df, home_team)

    # Detect inflections
    away_inflections = detect_inflection_points(away_deltas)
    home_inflections = detect_inflection_points(home_deltas)

    # Format output
    lines = []
    lines.append(f"\n{'='*70}")
    lines.append(f"WEEK {week} RECAP")
    lines.append(f"{away_team} vs {home_team}")
    lines.append(f"{'='*70}")

    # Day-by-day table
    lines.append("\nDay-by-Day Totals:")
    lines.append(format_day_by_day_table(trend_df, away_team))

    # Inflection points
    all_inflections = away_inflections + home_inflections
    if all_inflections:
        lines.append("\nInflection Points:")
        for inf in sorted(all_inflections, key=lambda x: x['date']):
            date_obj = pd.to_datetime(inf['date'])
            date_str = date_obj.strftime('%b %d (%a)')
            sign = '+' if inf['delta'] > 0 else ''
            stat_name = DISPLAY_NAMES.get(inf['stat'], inf['stat'])
            player_note = get_player_contribution(conn, week, away_team if inf['team'] == away_team else home_team,
                                                 inf['stat'], str(inf['date']))
            if player_note:
                lines.append(f"  * {date_str}: {stat_name} {sign}{inf['delta']:.2f} ({inf['prev']:.2f} → {inf['new']:.2f}) — {player_note}")
            else:
                lines.append(f"  * {date_str}: {stat_name} {sign}{inf['delta']:.2f} ({inf['prev']:.2f} → {inf['new']:.2f})")

    # Final score (if available)
    latest = trend_df[trend_df['team_name'].isin([away_team, home_team])].sort_values('snapshot_date').iloc[-2:] \
        if len(trend_df) >= 2 else trend_df
    if len(latest) >= 2:
        away_latest = latest[latest['team_name'] == away_team]
        home_latest = latest[latest['team_name'] == home_team]
        if not away_latest.empty and not home_latest.empty:
            lines.append(f"\nFinal: {away_team} {away_latest.iloc[-1].get('score', '?')} - {home_team} {home_latest.iloc[-1].get('score', '?')}")

    return "\n".join(lines)

def get_matchup_pairs(conn, week: int) -> List[Dict]:
    """Extract unique matchup pairs from team_week_snapshots."""
    trend_df = load_week_trend(conn, week)
    if trend_df.empty:
        return []

    pairs = []
    seen = set()

    for _, row in trend_df.iterrows():
        team_name = row['team_name']
        opponent = row.get('matchup_opponent')

        if not opponent:
            continue

        # Create a canonical pair key (smaller name first) to avoid duplicates
        pair_key = tuple(sorted([team_name, opponent]))
        if pair_key not in seen:
            seen.add(pair_key)
            pairs.append({
                'away': {'name': pair_key[0]},
                'home': {'name': pair_key[1]}
            })

    return pairs

def main():
    parser = argparse.ArgumentParser(description="Generate weekly fantasy baseball recap")
    parser.add_argument("--league-id", type=int, required=True, help="ESPN league ID (for reference)")
    parser.add_argument("--week", type=int, required=True, help="Week to recap")
    args = parser.parse_args()

    conn = db.init_db()

    try:
        print(f"Generating recap for week {args.week}...\n")

        # Get matchup pairs
        matchup_pairs = get_matchup_pairs(conn, args.week)

        if not matchup_pairs:
            print(f"No data found for week {args.week}")
            sys.exit(1)

        # Format each matchup
        for matchup in matchup_pairs:
            print(format_matchup_recap(conn, args.week, matchup))

    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
    finally:
        conn.close()

if __name__ == "__main__":
    main()
