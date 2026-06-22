"""ESPN Fantasy Baseball 2026 matchup week schedule."""

from datetime import date

# Maps matchupPeriodId -> (start_date, end_date) strings
ESPN_WEEKS = {
    1:  ('2026-03-25', '2026-04-05'),  # Opening period, 12 days (no real matchup)
    2:  ('2026-04-06', '2026-04-12'),
    3:  ('2026-04-13', '2026-04-19'),
    4:  ('2026-04-20', '2026-04-26'),
    5:  ('2026-04-27', '2026-05-03'),
    6:  ('2026-05-04', '2026-05-10'),  # Validated ✓
    7:  ('2026-05-11', '2026-05-17'),  # Validated ✓
    8:  ('2026-05-18', '2026-05-24'),
    9:  ('2026-05-25', '2026-05-31'),
    10: ('2026-06-01', '2026-06-07'),
    11: ('2026-06-08', '2026-06-14'),
    12: ('2026-06-15', '2026-06-21'),
    13: ('2026-06-22', '2026-06-28'),
    14: ('2026-06-29', '2026-07-05'),
    15: ('2026-07-06', '2026-07-19'),  # Extended 14 days — All-Star break
    16: ('2026-07-20', '2026-07-26'),
    17: ('2026-07-27', '2026-08-02'),
    18: ('2026-08-03', '2026-08-09'),
    19: ('2026-08-10', '2026-08-16'),
}

def date_to_matchup_period(target_date) -> int:
    """Convert a date to ESPN's matchupPeriodId."""
    date_str = str(target_date)
    for period, (start, end) in ESPN_WEEKS.items():
        if start <= date_str <= end:
            return period
    raise ValueError(f"Date {target_date} not in any known ESPN week")

def get_week_date_range(matchup_period: int) -> tuple:
    """Get the (start_date, end_date) for a matchup period."""
    if matchup_period not in ESPN_WEEKS:
        raise ValueError(f"Unknown matchup period: {matchup_period}")
    return ESPN_WEEKS[matchup_period]

def get_last_day_of_week(matchup_period: int) -> str:
    """Get the last day of a matchup period (YYYY-MM-DD)."""
    return ESPN_WEEKS[matchup_period][1]
