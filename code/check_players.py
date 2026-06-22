#!/usr/bin/env python3
"""Check if player data is collected."""

import db
import pandas as pd

conn = db.init_db()

# Check player data
df = pd.read_sql_query('''
    SELECT week, snapshot_date, COUNT(DISTINCT player_name) as unique_players,
           COUNT(*) as total_rows,
           SUM(CASE WHEN hr != '--' AND hr IS NOT NULL THEN 1 ELSE 0 END) as hr_stats
    FROM player_snapshots
    GROUP BY week, snapshot_date
    ORDER BY week DESC, snapshot_date DESC
''', conn)

print("\n" + "="*80)
print("PLAYER DATA CHECK")
print("="*80 + "\n")

if len(df) == 0:
    print("✗ No player data found\n")
else:
    print(f"Data collected for {len(df)} (week, date) combinations\n")
    print(df.to_string(index=False))

    # Check a sample of actual player data
    print("\n" + "-"*80)
    print("Sample player data:\n")
    sample = pd.read_sql_query('''
        SELECT week, snapshot_date, player_name, player_type, hr, r, rbi
        FROM player_snapshots
        WHERE hr != '--' AND hr IS NOT NULL AND hr != '0'
        LIMIT 5
    ''', conn)

    if len(sample) > 0:
        print(sample.to_string(index=False))
        print(f"\n✓ Found {len(sample)} players with HR stats")
    else:
        print("✗ No players with HR > 0")

conn.close()
print()
