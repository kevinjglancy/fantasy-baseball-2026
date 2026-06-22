"""Analysis logic for fantasy baseball league"""


class WeeklyAnalyzer:
    def __init__(self, league_data):
        self.league_data = league_data
        self.teams = league_data.get('teams', [])
        self.schedule = league_data.get('schedule', [])
        self.league = league_data.get('league', {})
        self.owner_map = league_data.get('owner_map', {})
        self.matchup_details = league_data.get('matchup_details', {})

    def analyze_current_week(self, week=None):
        """Analyze the current week's matchups"""
        week_label = f"WEEK {week}" if week else "CURRENT WEEK"
        print(f"\n{'='*70}")
        print(f"{self.league.get('name', 'LEAGUE')} - {week_label}")
        print(f"{'='*70}\n")

        if not self.schedule:
            print("No matchup data available")
            return

        # Group schedule by week
        matchups_by_week = {}
        for matchup in self.schedule:
            week = matchup.get('matchupPeriodId', 1)
            if week not in matchups_by_week:
                matchups_by_week[week] = []
            matchups_by_week[week].append(matchup)

        if not matchups_by_week:
            print("No matchups found")
            return

        # Show requested week or current week
        if week:
            display_week = week
        else:
            display_week = max(matchups_by_week.keys())

        if display_week not in matchups_by_week:
            print(f"Week {display_week} has no matchups")
            return

        print(f"Week {display_week}\n")

        for matchup in matchups_by_week[display_week]:
            self._analyze_matchup(matchup)

    def _analyze_matchup(self, matchup):
        """Analyze a single matchup"""
        home = matchup.get('home', {})
        away = matchup.get('away', {})

        home_name = home.get('name', 'Team')
        away_name = away.get('name', 'Team')
        home_id = home.get('teamId')
        away_id = away.get('teamId')

        # Get owner names (map can be by name or by ID)
        home_owner = self.owner_map.get(home_name, self.owner_map.get(home_id, 'Unknown'))
        away_owner = self.owner_map.get(away_name, self.owner_map.get(away_id, 'Unknown'))

        home_score = home.get('totalPoints', 0)
        away_score = away.get('totalPoints', 0)

        # Print matchup header with owners
        print(f"{away_name} ({away_owner}) @ {home_name} ({home_owner})")
        print(f"Score: {away_name} {away_score:.1f} - {home_name} {home_score:.1f}")

        # Print matchup details if available
        matchup_key = f"{away_id}_vs_{home_id}"
        if matchup_key in self.matchup_details:
            self._print_matchup_details(self.matchup_details[matchup_key])

        print()

    def _print_matchup_details(self, details):
        """Print detailed matchup stats including player performance"""
        # Print team totals
        print("\n  TEAM TOTALS:")
        team_totals = details.get('team_totals', {})
        if team_totals:
            stats = team_totals.get('stats', {})
            print(f"    {team_totals.get('name', 'Team')}: ", end='')
            print(f"R={stats.get('R', '0')}, HR={stats.get('HR', '0')}, RBI={stats.get('RBI', '0')}, "
                  f"AVG={stats.get('AVG', '0')}, ERA={stats.get('ERA', '0')}, WHIP={stats.get('WHIP', '0')}")

        opponent_totals = details.get('opponent_totals', {})
        if opponent_totals:
            stats = opponent_totals.get('stats', {})
            print(f"    {opponent_totals.get('name', 'Team')}: ", end='')
            print(f"R={stats.get('R', '0')}, HR={stats.get('HR', '0')}, RBI={stats.get('RBI', '0')}, "
                  f"AVG={stats.get('AVG', '0')}, ERA={stats.get('ERA', '0')}, WHIP={stats.get('WHIP', '0')}")

        # Print player stats
        team_name = team_totals.get('name', 'Team')
        opponent_name = opponent_totals.get('name', 'Opponent')

        # Show batting stats
        team_batters = details.get('team_batters', [])
        if team_batters:
            print(f"\n  {team_name} BATTERS:")
            for batter in team_batters[:8]:  # Show top 8
                stats = batter.get('stats', {})
                print(f"    {batter.get('name', 'Player')}: "
                      f"H/AB={stats.get('H/AB', '-')}, R={stats.get('R', '-')}, "
                      f"HR={stats.get('HR', '-')}, RBI={stats.get('RBI', '-')}, "
                      f"AVG={stats.get('AVG', '-')}")

        opponent_batters = details.get('opponent_batters', [])
        if opponent_batters:
            print(f"\n  {opponent_name} BATTERS:")
            for batter in opponent_batters[:8]:
                stats = batter.get('stats', {})
                print(f"    {batter.get('name', 'Player')}: "
                      f"H/AB={stats.get('H/AB', '-')}, R={stats.get('R', '-')}, "
                      f"HR={stats.get('HR', '-')}, RBI={stats.get('RBI', '-')}, "
                      f"AVG={stats.get('AVG', '-')}")

        # Show pitching stats
        team_pitchers = details.get('team_pitchers', [])
        if team_pitchers:
            print(f"\n  {team_name} PITCHERS:")
            for pitcher in team_pitchers[:5]:  # Show top 5
                stats = pitcher.get('stats', {})
                print(f"    {pitcher.get('name', 'Player')}: "
                      f"IP={stats.get('IP', '-')}, K={stats.get('K', '-')}, "
                      f"ERA={stats.get('ERA', '-')}, WHIP={stats.get('WHIP', '-')}")

        opponent_pitchers = details.get('opponent_pitchers', [])
        if opponent_pitchers:
            print(f"\n  {opponent_name} PITCHERS:")
            for pitcher in opponent_pitchers[:5]:
                stats = pitcher.get('stats', {})
                print(f"    {pitcher.get('name', 'Player')}: "
                      f"IP={stats.get('IP', '-')}, K={stats.get('K', '-')}, "
                      f"ERA={stats.get('ERA', '-')}, WHIP={stats.get('WHIP', '-')}")
