import pytest


def make_player(pid, team, position, **stats):
    player = {
        "id": pid,
        "first_name": f"First{pid}",
        "second_name": f"Player{pid}",
        "web_name": f"Player{pid}",
        "team": team,
        "element_type": position,
        "now_cost": 60,
        "status": "a",
        "chance_of_playing_next_round": None,
        "news": "",
        "minutes": 630,
        "starts": 7,
        "expected_goals": "0.00",
        "expected_assists": "0.00",
        "expected_goals_conceded": "0.00",
        "saves": 0,
        "defensive_contribution": 0,
        "bonus": 0,
        "goals_scored": 0,
        "selected_by_percent": "5.0",
        "ep_next": "4.0",
        "form": "4.0",
        "photo": f"{pid}.jpg",
        "code": pid,
    }
    player.update(stats)
    return player


def build_world():
    """Four teams, seven games played each. In gameweek 8 team 2 has a double and team 4 blanks."""
    teams = [{"id": t, "short_name": f"T{t}", "name": f"Team {t}"} for t in (1, 2, 3, 4)]

    rounds = [((1, 2), (3, 4)), ((1, 3), (2, 4)), ((1, 4), (2, 3))]
    fixtures = []
    for gw in range(1, 8):
        for home, away in rounds[gw % 3]:
            fixtures.append({"id": len(fixtures) + 1, "event": gw, "team_h": home, "team_a": away,
                             "finished": True, "finished_provisional": True, "kickoff_time": f"2026-08-{gw:02d}T15:00:00Z",
                             "team_h_difficulty": 3, "team_a_difficulty": 3})
    upcoming = [
        (8, 1, 2, "2026-10-24T14:00:00Z"), (8, 3, 2, "2026-10-27T19:00:00Z"),
        (9, 4, 1, "2026-10-31T15:00:00Z"), (9, 3, 2, "2026-10-31T15:00:00Z"),
        (10, 2, 4, "2026-11-07T15:00:00Z"), (10, 1, 3, "2026-11-07T15:00:00Z"),
    ]
    for gw, home, away, kickoff in upcoming:
        fixtures.append({"id": len(fixtures) + 1, "event": gw, "team_h": home, "team_a": away,
                         "finished": False, "finished_provisional": False, "kickoff_time": kickoff,
                         "team_h_difficulty": 2, "team_a_difficulty": 4})

    players = [
        # Goalkeepers carry each team's xG conceded: team 1 is tight, team 2 leaks. As in a real
        # league, total xG conceded roughly equals total xG created by the outfield players below.
        make_player(1, 1, 1, expected_goals_conceded="2.80", saves=14),
        make_player(2, 2, 1, expected_goals_conceded="7.00", saves=30),
        make_player(3, 3, 1, expected_goals_conceded="4.90", saves=20),
        make_player(4, 4, 1, expected_goals_conceded="4.20", saves=20),
        # Elite, nailed forward with strong underlying numbers.
        make_player(10, 1, 4, expected_goals="6.00", expected_assists="1.00", goals_scored=5, now_cost=150, bonus=8,
                    selected_by_percent="60.0"),
        # Overperformer: lots of goals from little xG.
        make_player(11, 3, 4, expected_goals="1.50", expected_assists="0.30", goals_scored=7, bonus=10),
        # Injured star: great numbers, ruled out.
        make_player(12, 1, 4, expected_goals="4.00", expected_assists="1.00", goals_scored=4, status="i",
                    chance_of_playing_next_round=0, news="Knee injury", selected_by_percent="30.0"),
        # Rotation player: one start in seven.
        make_player(13, 2, 4, expected_goals="0.80", minutes=150, starts=1),
        # Forward whose team blanks in gameweek 8. Single-name player (empty first_name).
        make_player(14, 4, 4, first_name="", second_name="Mononym", expected_goals="3.00", expected_assists="0.50"),
        # Midfielders and defenders.
        make_player(20, 2, 3, expected_goals="2.00", expected_assists="2.00", status="d", chance_of_playing_next_round=75,
                    news="Knock - 75% chance of playing", selected_by_percent="12.0"),
        make_player(21, 3, 3, expected_goals="1.00", expected_assists="1.20"),
        make_player(30, 1, 2, expected_goals="0.40", expected_assists="0.30", defensive_contribution=84),
        make_player(31, 1, 2, expected_goals="0.40", expected_assists="0.30", defensive_contribution=0),
        # Never played.
        make_player(40, 3, 3, minutes=0, starts=0),
    ]

    scoring = {
        "long_play": 2, "short_play": 1,
        "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}, "assists": 3,
        "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
        "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0}, "saves": 1,
        "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
    }
    bootstrap = {
        "elements": players,
        "teams": teams,
        "events": [{"id": gw, "is_current": gw == 7, "is_next": gw == 8} for gw in range(1, 11)],
        "game_config": {"scoring": scoring},
    }
    return bootstrap, fixtures


@pytest.fixture
def world():
    return build_world()
