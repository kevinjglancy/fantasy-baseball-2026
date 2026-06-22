#!/usr/bin/env python3
"""Check if standings data is collected."""

import db
import pandas as pd

conn = db.init_db()

# Check standings
df = pd.read_sql_query('''
    SELECT snapshot_date, team_name, owner, r, hr, rbi, era, whip
    FROM standings_snapshots
    ORDER BY snapshot_date DESC, team_name
''', conn)

print("\n" + "="*80)
print("STANDINGS DATA CHECK")
print("="*80 + "\n")

if len(df) == 0:
    print("✗ No standings data found\n")
else:
    # Show latest date
    latest_date = df['snapshot_date'].max()
    print(f"Latest standings date: {latest_date}\n")

    # Show latest standings
    latest_df = df[df['snapshot_date'] == latest_date]
    print(f"Teams in latest snapshot: {len(latest_df)}\n")
    print(latest_df[['team_name', 'owner', 'r', 'hr', 'rbi', 'era', 'whip']].to_string(index=False))

    if len(latest_df) == 10:
        print("\n✓ All 10 teams found")
    else:
        print(f"\n⚠ Only {len(latest_df)} teams (expected 10)")

    # Check for actual stats (not 0)
    non_zero = latest_df[(latest_df['r'].notna()) & (latest_df['r'] > 0)]
    if len(non_zero) > 0:
        print(f"✓ {len(non_zero)} teams have R > 0")
    else:
        print("✗ No teams with R > 0 (data might be missing)")

conn.close()
print()
