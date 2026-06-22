#!/usr/bin/env python3
"""Generate weekly fantasy baseball write-ups using Claude API."""

import sqlite3, json, os, sys, argparse
from datetime import date
from collections import defaultdict

script_dir = os.path.dirname(os.path.abspath(__file__))
db_path = os.path.join(script_dir, 'fantasy_baseball.db')
writeups_path = os.path.join(script_dir, 'weekly_writeups.json')

CATEGORIES = ['r', 'hr', 'rbi', 'sb', 'avg', 'ops', 'k', 'qs', 'sv', 'hd', 'era', 'whip']
LOWER_IS_BETTER = {'era', 'whip'}


def get_week_team_stats(conn, week):
    from espn_schedule import get_week_date_range
    start, end = get_week_date_range(week)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT t.team_name, t.r, t.hr, t.rbi, t.sb, t.avg, t.ops,
               t.k, t.qs, t.sv, t.hd, t.era, t.whip
        FROM team_day_snapshots t
        INNER JOIN (
            SELECT team_name, MAX(snapshot_date) as max_date
            FROM team_day_snapshots WHERE snapshot_date BETWEEN ? AND ?
            GROUP BY team_name
        ) latest ON t.team_name = latest.team_name AND t.snapshot_date = latest.max_date
    """, (start, end))
    return {row[0]: dict(zip(CATEGORIES, row[1:])) for row in cursor.fetchall()}


def _fetch_pairings_selenium(week, league_id=94668654):
    """Fetch matchup pairings from ESPN via Selenium. Returns list of (team1, team2)."""
    import urllib.parse, time
    from dotenv import load_dotenv
    load_dotenv()
    swid = os.getenv('SWID')
    espn_s2 = os.getenv('ESPN_S2')
    if not swid or not espn_s2:
        return []

    from driver_utils import create_driver
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support.ui import WebDriverWait
    from selenium.webdriver.support import expected_conditions as EC
    from bs4 import BeautifulSoup

    espn_s2_dec = urllib.parse.unquote(espn_s2)
    driver = create_driver()
    try:
        driver.get('https://fantasy.espn.com')
        driver.add_cookie({'name': 'SWID', 'value': swid})
        driver.add_cookie({'name': 'espn_s2', 'value': espn_s2_dec})
        url = f"https://fantasy.espn.com/baseball/league/scoreboard?leagueId={league_id}&matchupPeriodId={week}"
        driver.get(url)
        WebDriverWait(driver, 20).until(
            EC.presence_of_all_elements_located((By.CSS_SELECTOR, 'li.ScoreboardScoreCell__Item'))
        )
        time.sleep(2)
        soup = BeautifulSoup(driver.page_source, 'html.parser')
        seen, pairings = set(), []
        for container in soup.find_all('div', class_='matchup-score'):
            items = container.find_all('li', class_='ScoreboardScoreCell__Item')
            if len(items) < 2:
                continue
            teams = [i.find('div', class_='ScoreCell__TeamName') for i in items[:2]]
            teams = [t.get_text(strip=True) for t in teams if t]
            if len(teams) == 2:
                key = tuple(sorted(teams))
                if key not in seen:
                    seen.add(key)
                    pairings.append(tuple(teams))
        return pairings
    except Exception as e:
        print(f"  Selenium pairing fetch failed: {e}")
        return []
    finally:
        driver.quit()


def _store_pairing(conn, week, snapshot_date, team, opponent):
    cursor = conn.cursor()
    cursor.execute("""
        INSERT OR IGNORE INTO team_week_snapshots (snapshot_date, week, team_name, matchup_opponent)
        VALUES (?, ?, ?, ?)
    """, (snapshot_date, week, team, opponent))
    cursor.execute("""
        UPDATE team_week_snapshots SET matchup_opponent = ?
        WHERE week = ? AND team_name = ? AND matchup_opponent IS NULL
    """, (opponent, week, team))
    conn.commit()


def get_matchup_pairings(conn, week, league_id=94668654):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT DISTINCT team_name, matchup_opponent
        FROM team_week_snapshots
        WHERE week = ? AND matchup_opponent IS NOT NULL
    """, (week,))
    seen, pairings = set(), []
    for team, opp in cursor.fetchall():
        key = tuple(sorted([team, opp]))
        if key not in seen:
            seen.add(key)
            pairings.append((team, opp))
    if pairings:
        return pairings

    print(f"  No pairings in DB for week {week}, fetching via Selenium...")
    pairings = _fetch_pairings_selenium(week, league_id)
    if pairings:
        from espn_schedule import get_week_date_range
        _, end_date = get_week_date_range(week)
        for t1, t2 in pairings:
            _store_pairing(conn, week, end_date, t1, t2)
            _store_pairing(conn, week, end_date, t2, t1)
    return pairings


def get_week_players(conn, week):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT p.player_name, p.team_name, p.h_ab, p.r, p.hr, p.rbi, p.sb, p.avg
        FROM player_snapshots p
        INNER JOIN (
            SELECT player_name, MAX(snapshot_date) as md
            FROM player_snapshots
            WHERE week = ? AND player_type = 'batter'
              AND player_name NOT IN ('Empty', '__Empty__')
            GROUP BY player_name
        ) x ON p.player_name = x.player_name AND p.snapshot_date = x.md
        WHERE p.week = ?
        ORDER BY COALESCE(p.hr,0)*3 + COALESCE(p.rbi,0) DESC
    """, (week, week))
    batters = [{'name': r[0], 'team': r[1], 'h_ab': r[2], 'r': r[3] or 0,
                'hr': r[4] or 0, 'rbi': r[5] or 0, 'sb': r[6] or 0, 'avg': r[7] or 0}
               for r in cursor.fetchall()]

    cursor.execute("""
        SELECT p.player_name, p.team_name, p.ip, p.k, p.qs, p.sv, p.era, p.whip
        FROM player_snapshots p
        INNER JOIN (
            SELECT player_name, MAX(snapshot_date) as md
            FROM player_snapshots
            WHERE week = ? AND player_type = 'pitcher'
              AND ip > 0 AND player_name NOT IN ('Empty', '__Empty__')
            GROUP BY player_name
        ) x ON p.player_name = x.player_name AND p.snapshot_date = x.md
        WHERE p.week = ?
        ORDER BY COALESCE(p.k,0) + COALESCE(p.qs,0)*5 DESC
    """, (week, week))
    pitchers = [{'name': r[0], 'team': r[1], 'ip': r[2] or 0, 'k': r[3] or 0,
                 'qs': r[4] or 0, 'sv': r[5] or 0, 'era': r[6] or 0, 'whip': r[7] or 0}
                for r in cursor.fetchall()]
    return batters, pitchers


def get_daily_progression(conn, week, team1, team2):
    from espn_schedule import get_week_date_range
    start, end = get_week_date_range(week)
    cursor = conn.cursor()
    cursor.execute("""
        SELECT snapshot_date, team_name,
               SUM(COALESCE(r,0)), SUM(COALESCE(hr,0)),
               SUM(COALESCE(rbi,0)), SUM(COALESCE(k,0))
        FROM player_snapshots
        WHERE week = ? AND team_name IN (?, ?)
          AND snapshot_date BETWEEN ? AND ?
          AND player_name NOT IN ('Empty', '__Empty__')
        GROUP BY snapshot_date, team_name
        ORDER BY snapshot_date
    """, (week, team1, team2, start, end))

    by_date = defaultdict(dict)
    for d, team, r, hr, rbi, k in cursor.fetchall():
        by_date[d][team] = {'r': r, 'hr': hr, 'rbi': rbi, 'k': k}

    dates = sorted(by_date.keys())
    daily = []
    for i, d in enumerate(dates):
        if i == 0:
            t1 = by_date[d].get(team1, {'r': 0, 'hr': 0, 'rbi': 0, 'k': 0})
            t2 = by_date[d].get(team2, {'r': 0, 'hr': 0, 'rbi': 0, 'k': 0})
        else:
            prev = dates[i - 1]
            def delta(cur, prv):
                return {k: (cur.get(k, 0) or 0) - (prv.get(k, 0) or 0)
                        for k in ['r', 'hr', 'rbi', 'k']}
            t1 = delta(by_date[d].get(team1, {}), by_date[prev].get(team1, {}))
            t2 = delta(by_date[d].get(team2, {}), by_date[prev].get(team2, {}))
        daily.append({'date': d[-5:], 't1': t1, 't2': t2})
    return daily


def compare_teams(s1, s2):
    w1 = w2 = 0
    details = {}
    for cat in CATEGORIES:
        v1, v2 = s1.get(cat) or 0, s2.get(cat) or 0
        if v1 == v2:
            details[cat] = 'tie'
        elif (cat in LOWER_IS_BETTER and v1 < v2) or (cat not in LOWER_IS_BETTER and v1 > v2):
            w1 += 1; details[cat] = 'team1'
        else:
            w2 += 1; details[cat] = 'team2'
    return w1, w2, details


def fmt_val(cat, val):
    return round(val, 3) if cat in ('avg', 'ops', 'era', 'whip') else int(val or 0)


def compute_roto_points(stats_dict):
    """1st=12pts, 2nd=11pts, ..., 10th=3pts. Ties share points."""
    if not stats_dict: return {}
    n = len(stats_dict); teams = list(stats_dict.keys())
    pts = {t: {} for t in teams}
    for cat in CATEGORIES:
        vals = sorted([(t, stats_dict[t].get(cat) or 0) for t in teams],
                      key=lambda x: x[1], reverse=(cat not in LOWER_IS_BETTER))
        i = 0
        while i < n:
            j = i
            while j < n and vals[j][1] == vals[i][1]: j += 1
            shared = sum(12 - k for k in range(i, j)) / (j - i)
            for k in range(i, j): pts[vals[k][0]][cat] = round(shared, 1)
            i = j
    for t in teams:
        pts[t]['total'] = round(sum(pts[t].get(c, 0) for c in CATEGORIES), 1)
    return pts


def get_season_standings(conn):
    cursor = conn.cursor()
    cursor.execute("""
        SELECT TRIM(team_name), owner, wins, losses, ties, pct
        FROM standings_snapshots
        WHERE snapshot_date = (SELECT MAX(snapshot_date) FROM standings_snapshots)
        ORDER BY pct DESC
    """)
    return [{'team': r[0], 'owner': r[1], 'w': r[2], 'l': r[3], 't': r[4],
             'pct': round(r[5] or 0, 3)} for r in cursor.fetchall()]


def build_prompt(week, conn, league_id=94668654):
    from espn_schedule import get_week_date_range
    start, end = get_week_date_range(week)

    week_stats = get_week_team_stats(conn, week)
    pairings = get_matchup_pairings(conn, week, league_id)
    batters, pitchers = get_week_players(conn, week)
    standings = get_season_standings(conn)

    if not week_stats or not pairings:
        return None

    matchup_blocks = []
    for team1, team2 in pairings:
        s1 = week_stats.get(team1, {})
        s2 = week_stats.get(team2, {})
        w1, w2, cat_results = compare_teams(s1, s2)
        winner = team1 if w1 > w2 else (team2 if w2 > w1 else None)

        t1_bat = [f"{p['name']}: {p['h_ab'] or '--'} {p['hr']}HR {p['rbi']}RBI {p['r']}R {p['sb']}SB"
                  for p in batters if p['team'] == team1][:3]
        t1_pit = [f"{p['name']}: {p['ip']}IP {p['k']}K {p['qs']}QS {p['sv']}SV {p['era']}ERA"
                  for p in pitchers if p['team'] == team1][:3]
        t2_bat = [f"{p['name']}: {p['h_ab'] or '--'} {p['hr']}HR {p['rbi']}RBI {p['r']}R {p['sb']}SB"
                  for p in batters if p['team'] == team2][:3]
        t2_pit = [f"{p['name']}: {p['ip']}IP {p['k']}K {p['qs']}QS {p['sv']}SV {p['era']}ERA"
                  for p in pitchers if p['team'] == team2][:3]

        daily = get_daily_progression(conn, week, team1, team2)
        daily_lines = [
            f"{d['date']}: {team1} {d['t1'].get('r',0)}R/{d['t1'].get('hr',0)}HR/{d['t1'].get('k',0)}K | "
            f"{team2} {d['t2'].get('r',0)}R/{d['t2'].get('hr',0)}HR/{d['t2'].get('k',0)}K"
            for d in daily
        ]

        cats_t1 = [c.upper() for c, w in cat_results.items() if w == 'team1']
        cats_t2 = [c.upper() for c, w in cat_results.items() if w == 'team2']
        cats_tie = [c.upper() for c, w in cat_results.items() if w == 'tie']

        s1_str = ', '.join(f"{c.upper()}={fmt_val(c, s1.get(c))}" for c in CATEGORIES)
        s2_str = ', '.join(f"{c.upper()}={fmt_val(c, s2.get(c))}" for c in CATEGORIES)

        matchup_blocks.append(
            f"MATCHUP: {team1} vs {team2}\n"
            f"Result: {winner or 'TIE'} wins {w1}-{w2}\n"
            f"{team1} weekly stats: {s1_str}\n"
            f"{team2} weekly stats: {s2_str}\n"
            f"{team1} won categories: {cats_t1}\n"
            f"{team2} won categories: {cats_t2}\n"
            f"Tied categories: {cats_tie}\n"
            f"{team1} top batters: {t1_bat}\n"
            f"{team1} top pitchers: {t1_pit}\n"
            f"{team2} top batters: {t2_bat}\n"
            f"{team2} top pitchers: {t2_pit}\n"
            f"Day-by-day (R/HR/K):\n" + '\n'.join(daily_lines)
        )

    # Weekly roto leaders
    # Compute weekly roto standings (1st=12pts ... 10th=3pts)
    weekly_roto = compute_roto_points(week_stats)
    roto_sorted = sorted(weekly_roto.items(), key=lambda x: x[1]['total'], reverse=True)
    roto_lines = [
        f"{i+1}. {team} — {pts['total']}pts "
        f"(top cats: {', '.join(c.upper() for c in CATEGORIES if pts.get(c, 0) >= 10)})"
        for i, (team, pts) in enumerate(roto_sorted)
    ]
    cat_leaders = []
    for cat in CATEGORIES:
        leader = max(weekly_roto.items(), key=lambda x: x[1].get(cat, 0))
        cat_leaders.append(f"{cat.upper()}: {leader[0]} ({fmt_val(cat, week_stats.get(leader[0], {}).get(cat))})")

    standings_lines = [
        f"{i+1}. {s['team']} ({s['owner']}): {s['w']}-{s['l']}-{s['t']} ({s['pct']})"
        for i, s in enumerate(standings)
    ]

    return (
        f"Generate the Week {week} fantasy baseball recap ({start} to {end}) "
        f"for this 10-team H2H categories league.\n\n"
        f"{'='*60}\nMATCHUP DATA\n{'='*60}\n\n"
        + '\n\n'.join(matchup_blocks)
        + f"\n\n{'='*60}\nWEEKLY ROTO STANDINGS (1st=12pts, 10th=3pts)\n{'='*60}\n"
        + '\n'.join(roto_lines)
        + f"\n\nCategory leaders this week:\n" + '\n'.join(cat_leaders)
        + f"\n\n{'='*60}\nSEASON STANDINGS\n{'='*60}\n"
        + '\n'.join(standings_lines)
        + f"""

Return ONLY a JSON object with this exact structure (no markdown fences, no extra text):
{{
  "headline": "Week {week} Recap: [catchy subtitle]",
  "intro": "1-2 sentence hook about the week overall",
  "matchups": [
    {{
      "team1": "exact team name",
      "team2": "exact team name",
      "winner": "exact winning team name or null for tie",
      "score": "X-Y",
      "narrative": "3-5 sentences about the matchup storyline, who won and why",
      "day_by_day": "2-3 sentences about how the matchup evolved day by day",
      "standout_players": "2-3 sentences with specific player names and real stat lines"
    }}
  ],
  "roto_section": "2-3 sentences about the weekly roto standings — mention specific point totals, who led the week overall, which teams dominated or struggled in categories",
  "standings_note": "1-2 sentences about standings implications or expected record gaps"
}}

Include one matchup entry per matchup, in the same order as provided above. Be specific with actual player names and numbers."""
    )


def generate_writeup(week, conn, league_id=94668654):
    import anthropic

    prompt = build_prompt(week, conn, league_id)
    if not prompt:
        print(f"Insufficient data for week {week}")
        return None

    client = anthropic.Anthropic()
    response = client.messages.create(
        model="claude-opus-4-8",
        max_tokens=4000,
        system="""You are the weekly recap writer for a private 10-team fantasy baseball league. Write engaging, stats-grounded summaries that members will enjoy reading.

Subtle tone guidance — keep it deniable, never heavy-handed:
- Kevin Glancy (Pooh's On First): You quietly root for this team. When they win, your prose brightens. When they lose, find the silver lining or note the tough draw. Their strong stats get a touch more recognition.
- Ted Zhang (The Big Gamblino): Mild skepticism, always. Acknowledge dominant stats with faint "well, obviously" energy. When they struggle, allow barely-concealed satisfaction. Backhanded compliments work perfectly here.

Return only valid JSON matching the exact structure in the user's request. No markdown fences. Be specific with real player names and actual stat lines from the data provided.""",
        messages=[{"role": "user", "content": prompt}]
    )

    text = next(b.text for b in response.content if b.type == "text").strip()
    # Strip markdown code fences if present
    for fence in ('```json\n', '```json', '```\n', '```'):
        if text.startswith(fence):
            text = text[len(fence):]
            break
    if text.endswith('```'):
        text = text[:-3].strip()

    return json.loads(text)


def main():
    parser = argparse.ArgumentParser(description='Generate weekly fantasy baseball write-up')
    parser.add_argument('--week', type=int, help='Week number (default: most recently completed)')
    parser.add_argument('--league-id', type=int, default=94668654)
    args = parser.parse_args()

    from espn_schedule import ESPN_WEEKS

    if not os.path.exists(db_path):
        print(f"ERROR: Database not found at {db_path}"); sys.exit(1)

    conn = sqlite3.connect(db_path)

    if args.week:
        week = args.week
    else:
        today = date.today().strftime('%Y-%m-%d')
        week = None
        for w, (start, end) in sorted(ESPN_WEEKS.items(), reverse=True):
            if end < today and w >= 2:
                week = w; break
        if week is None:
            print("No completed week found"); conn.close(); return

    print(f"Generating write-up for week {week}...")
    writeup = generate_writeup(week, conn, args.league_id)
    conn.close()

    if not writeup:
        print("Failed to generate write-up"); sys.exit(1)

    writeup['week'] = week
    writeup['generated_at'] = date.today().strftime('%Y-%m-%d')

    all_writeups = {}
    if os.path.exists(writeups_path):
        with open(writeups_path) as f:
            try:
                all_writeups = json.load(f)
            except json.JSONDecodeError:
                pass

    all_writeups[str(week)] = writeup

    with open(writeups_path, 'w') as f:
        json.dump(all_writeups, f, indent=2)

    print(f"✓ Week {week} write-up saved to {writeups_path}")


if __name__ == '__main__':
    main()
