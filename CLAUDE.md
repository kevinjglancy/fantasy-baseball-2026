# Fantasy Baseball Analyzer — Project Context

## League
10-team H2H categories league on ESPN. League ID: `94668654`. Season 2026 (March 25 – August 16).

**Teams & Owners:**
| Team | Owner |
|---|---|
| The Big Gamblino | Ted Zhang |
| Pooh's On First | Kevin Glancy |
| Phoenix Coyotes | Josh Oremland, Zach Oremland |
| The Chicago Orphans | Patrick Booth |
| Pittsburgh Piglets | Julien Piet |
| Pittsburgh Pirates | David Glancy |
| Seattle Dumpers | Devesh Rathee |
| Lets Go Bucs | Sherri Glancy |
| Cronen-Zone | Andrew Stephens |
| All Betts Are Off | Andrew Powell |

**Categories (12):** R, HR, RBI, SB, AVG, OPS (batting) + K, QS, SV, HD, ERA, WHIP (pitching). ERA and WHIP are lower-is-better.

## Quick Start
```bash
cd /Users/kevinglancy/fantasy-baseball-analyzer
source venv/bin/activate

# Regenerate dashboard (no ESPN call needed):
python generate_dashboard.py

# Generate weekly write-up for current week (needs ANTHROPIC_API_KEY env var):
python generate_weekly_writeup.py

# Collect latest player stats (needs Selenium + .env):
python collect_player_daily.py --league-id 94668654 --start-date 2026-06-22 --end-date 2026-06-22

# Validate collection:
python validate_collection.py --retry
```

## Key Files

| File | Purpose |
|---|---|
| `generate_dashboard.py` | Rebuilds `dashboard.html` + `dashboard_data.json` from DB. Run after any DB change. |
| `generate_weekly_writeup.py` | Calls Claude API to generate weekly matchup write-ups → `weekly_writeups.json`. Requires `ANTHROPIC_API_KEY`. Uses Selenium to fetch matchup pairings if not cached. |
| `collect_player_daily.py` | Daily player stats collection via Selenium (runs 3am ET daily via GitHub Actions). |
| `collect_daily.py` | Monday collection: team totals + matchup stats. |
| `validate_collection.py` | Verifies collected data, retries errors. **Always run after collection.** |
| `espn_schedule.py` | Maps week numbers to date ranges. Season weeks 1–19. |
| `driver_utils.py` | Shared `create_driver()` + `setup_driver_with_cookies()` — all Selenium scripts use this. |
| `db.py` | All DB functions. Tables: `team_day_snapshots`, `player_snapshots`, `standings_snapshots`, `team_week_snapshots`, `collection_log`. |
| `owner_map.py` | `TEAM_NAME_TO_OWNER` dict + `get_owner_by_name()`. |
| `weekly_writeups.json` | Persisted write-ups keyed by week number. Injected into dashboard. |
| `dashboard.html` | The live dashboard (committed to repo + pushed to pages repo). |
| `.env` | `SWID` + `ESPN_S2` (URL-encoded). DO NOT commit. |

## Database Schema Summary

### `team_day_snapshots`
End-of-week matchup totals per team, keyed by `snapshot_date` (last day of the week) and `team_name`.
- Stats: R, HR, RBI, SB, AVG, OPS, K, QS, SV, HD, ERA, WHIP
- Use `get_weekly_stats(conn, week)` in `generate_dashboard.py` to query.

### `player_snapshots`
Cumulative week-to-date stats per player, per day. Keyed by `snapshot_date`, `week`, `team_name`, `player_name`.
- Batters: h_ab, r, hr, rbi, bb, sb, avg, ops
- Pitchers: ip, h, er, k, qs, sv, hd, era, whip
- To get a player's full-week stats: query `WHERE week=N` and take `MAX(snapshot_date)`.

### `standings_snapshots`
Season-to-date roto standings. Usually only one or two snapshots per season.

### `team_week_snapshots`
Per-week data with `matchup_opponent` field. Only populated through week 6 by current collection. `generate_weekly_writeup.py` uses Selenium to backfill pairings for newer weeks and stores them here.

## Dashboard Tabs
1. **Standings** — Current W-L-T records
2. **Season Stats** — Season batting/pitching totals per team
3. **Expected Record** — Round-robin expected W-L vs actual. Chart shows week-by-week progression.
4. **Top Players** — Season leaders by composite z-score. **Week N Leaders** section at top shows most recent week's top performers.
5. **Team Drill-Down** — Per-team roster with player z-scores
6. **Weekly Recap** — Claude-generated matchup write-ups, newest first. Run `generate_weekly_writeup.py` to add a new week.
7. **Season Write-Up** — Hardcoded season narrative per team (edit in `dashboard.html` JS directly).
8. **Trade Targets** — Z-score-based trade suggestions
9. **Trade Evaluator** — Interactive trade fairness checker

## Z-Score Computation
- **Batters**: R, HR, RBI, SB, AVG, OPS. Minimum 50 AB.
- **Pitchers**: K, QS, SV, HD, ERA, WHIP. Minimum 10 IP (season) or 1 IP (weekly). **ERA/WHIP are IP-weighted**: a pitcher's ERA/WHIP contribution is computed as `(pool_avg - era) * ip / 9`, so a 12-IP pitcher barely moves the needle vs a 90-IP pitcher. `z_total` = sum of all 6 z-scores.

## GitHub Actions Automation
Workflow: `.github/workflows/update.yml`

| Schedule | What runs |
|---|---|
| Daily 3am ET | `collect_player_daily.py` |
| Monday 10am ET | `collect_daily.py` → `generate_weekly_writeup.py` → `generate_dashboard.py` |
| Any push/dispatch | Full pipeline |

**Secrets needed in GitHub**: `SWID`, `ESPN_S2`, `GH_PAT`, `ANTHROPIC_API_KEY`

The dashboard is committed to this repo AND pushed to `kevinjglancy/fantasy-baseball-2026` (GitHub Pages).

## Weekly Write-Up Details
- Script: `generate_weekly_writeup.py`
- Model: `claude-opus-4-8`
- Output: `weekly_writeups.json` (dict keyed by week number)
- Data sources: team stats from `team_day_snapshots`, players from `player_snapshots`, pairings from `team_week_snapshots` (Selenium fallback)
- **Bias**: Subtly favorable towards Kevin Glancy (Pooh's On First), subtly skeptical of Ted Zhang (The Big Gamblino). Kept deniable — word choices and framing, not explicit statements.
- To generate for a specific past week: `python generate_weekly_writeup.py --week 11`

## ESPN Authentication
- `SWID` and `ESPN_S2` cookies from browser DevTools → Application → Cookies → espn.com
- `ESPN_S2` in `.env` is URL-encoded (`%2F`, `%2B`, `%3D`) — `urllib.parse.unquote()` before passing to Selenium
- Credentials expire ~30 days after last use. If 403 errors, re-copy from browser.

## Common Gotchas
- `team_day_snapshots` stores matchup-period cumulative stats (not season totals). The last snapshot within a week's date range = that week's full totals.
- `player_snapshots` are cumulative week-to-date. To get daily production: subtract day N-1 from day N.
- `team_week_snapshots` stats are unreliable (bug in early collection) — use only for `matchup_opponent` field.
- ESPN_S2 must be URL-decoded before use in Selenium cookies.
- Headless Chrome needs `--no-sandbox --disable-dev-shm-usage` (already in `driver_utils.py`).
- After any DB changes, always run `python generate_dashboard.py` to rebuild the HTML.

## Previous Failed Approaches
- ❌ espn-api library: Only supports football/basketball
- ❌ Direct API calls: ESPN rejects without browser context
- ❌ Pure HTML scraping: Data loads via JavaScript (Next.js)
