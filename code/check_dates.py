#!/usr/bin/env python3
"""Check date to scoringPeriodId calculations."""

from datetime import date
from collect_daily import date_to_scoring_period, scoring_period_to_date

print("\n" + "="*80)
print("DATE CALCULATION CHECK")
print("="*80 + "\n")

# Test dates
test_dates = [
    date(2026, 3, 25),  # Season start reference
    date(2026, 3, 26),  # First game day
    date(2026, 4, 23),  # April 23 example
    date(2026, 5, 3),   # May 3
    date(2026, 5, 4),   # May 4
    date(2026, 5, 5),   # May 5
]

print("Date → scoringPeriodId:\n")
for d in test_dates:
    period = date_to_scoring_period(d)
    print(f"  {d} = Period {period}")

print("\n" + "-"*80)
print("scoringPeriodId → Date:\n")

test_periods = [1, 30, 40, 41, 42]
for period in test_periods:
    d = scoring_period_to_date(period)
    print(f"  Period {period} = {d}")

print("\n" + "-"*80)
print("Verification:\n")

# Round-trip test
orig_date = date(2026, 5, 4)
period = date_to_scoring_period(orig_date)
back_to_date = scoring_period_to_date(period)

if orig_date == back_to_date:
    print(f"✓ Round-trip works: {orig_date} → {period} → {back_to_date}")
else:
    print(f"✗ Round-trip failed: {orig_date} → {period} → {back_to_date}")

print()
