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


# ---------- A full synthetic league: enough players to field real 15-man squads ----------

SCORING = {
    "long_play": 2, "short_play": 1,
    "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4}, "assists": 3,
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0}, "saves": 1,
    "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
}
LEAGUE_SHAPE = {1: 2, 2: 5, 3: 5, 4: 3}


def round_robin(team_ids):
    """Fixtures by the circle method: every team plays every other once per cycle."""
    teams = list(team_ids)
    half = len(teams) // 2
    for index in range(len(teams) - 1):
        yield [(teams[i], teams[-1 - i]) if (index + i) % 2 == 0 else (teams[-1 - i], teams[i]) for i in range(half)]
        teams = [teams[0], teams[-1], *teams[1:-1]]


def build_league(clubs=8, played=7, upcoming=5):
    """`clubs` teams of 15 players each. Quality varies deterministically so projections are distinct."""
    elements = []
    for team in range(1, clubs + 1):
        next_id = team * 100
        for position, count in LEAGUE_SHAPE.items():
            for i in range(count):
                next_id += 1
                quality = ((team * 7 + position * 3 + i * 5) % 9) / 8  # 0 (weak) to 1 (elite)
                scale = 0.3 + 0.7 * quality
                stats = {
                    "expected_goals": f"{ {1: 0, 2: 0.6, 3: 2.5, 4: 5.0}[position] * scale:.2f}",
                    "expected_assists": f"{ {1: 0, 2: 0.5, 3: 2.0, 4: 1.2}[position] * scale:.2f}",
                    "now_cost": {1: 40, 2: 40, 3: 45, 4: 45}[position] + round(quality * {1: 20, 2: 35, 3: 60, 4: 70}[position]),
                    "defensive_contribution": round({2: 70 + 20 * quality, 3: 50 + 30 * quality}.get(position, 0)),
                    "selected_by_percent": f"{quality * 40:.1f}",
                    "goals_scored": round(quality * 3),
                    "bonus": round(quality * 6),
                }
                if position == 1:
                    first_choice = i == 0
                    stats.update(
                        expected_goals_conceded=f"{played * (0.9 + 0.1 * team):.2f}" if first_choice else "0.00",
                        minutes=630 if first_choice else 0,
                        starts=7 if first_choice else 0,
                        saves=20 if first_choice else 0,
                    )
                elif position in (2, 3) and i == count - 1:
                    stats.update(minutes=140, starts=2)  # bench fodder who rarely starts
                elements.append(make_player(next_id, team, position, **stats))

    # One injured forward, so there is somebody the model must never buy.
    injured = next(p for p in elements if p["team"] == 3 and p["element_type"] == 4)
    injured.update(status="i", chance_of_playing_next_round=0, news="Calf injury")

    fixtures = []
    cycle = list(round_robin(range(1, clubs + 1)))
    for gameweek in range(1, played + upcoming + 1):
        for home, away in cycle[(gameweek - 1) % len(cycle)]:
            done = gameweek <= played
            fixtures.append({
                "id": len(fixtures) + 1, "event": gameweek, "team_h": home, "team_a": away,
                "finished": done, "finished_provisional": done,
                "kickoff_time": f"2026-{8 + gameweek // 5:02d}-{(gameweek * 3) % 28 + 1:02d}T15:00:00Z",
                "team_h_difficulty": 3, "team_a_difficulty": 3,
            })

    windows = [
        ("wildcard", 2, 19), ("wildcard", 20, 38), ("freehit", 2, 19), ("freehit", 20, 38),
        ("bboost", 1, 19), ("bboost", 20, 38), ("3xc", 1, 19), ("3xc", 20, 38),
    ]
    bootstrap = {
        "elements": elements,
        "teams": [{"id": t, "short_name": f"T{t}", "name": f"Team {t}"} for t in range(1, clubs + 1)],
        "events": [{"id": gw, "is_current": gw == played, "is_next": gw == played + 1} for gw in range(1, played + upcoming + 1)],
        "chips": [{"name": n, "number": 1, "start_event": a, "stop_event": b} for n, a, b in windows],
        "element_types": [
            {"id": 1, "squad_select": 2, "squad_min_play": 1, "squad_max_play": 1},
            {"id": 2, "squad_select": 5, "squad_min_play": 3, "squad_max_play": 5},
            {"id": 3, "squad_select": 5, "squad_min_play": 2, "squad_max_play": 5},
            {"id": 4, "squad_select": 3, "squad_min_play": 1, "squad_max_play": 3},
        ],
        "game_config": {
            "scoring": SCORING,
            "rules": {"squad_squadsize": 15, "squad_squadplay": 11, "squad_team_limit": 3, "max_extra_free_transfers": 4},
        },
    }
    return bootstrap, fixtures


def weakest_squad(bootstrap, projections):
    """A legal, deliberately poor squad (the lowest projections per position, at most 3 per club)."""
    from collections import Counter

    clubs, chosen = Counter(), []
    for position, count in LEAGUE_SHAPE.items():
        pool = sorted(
            (p for p in bootstrap["elements"] if p["element_type"] == position and p["status"] == "a"),
            key=lambda p: (projections[p["id"]]["xp_horizon"], p["id"]),
        )
        picked = 0
        for player in pool:
            if picked < count and clubs[player["team"]] < 3:
                chosen.append(player)
                clubs[player["team"]] += 1
                picked += 1
    return chosen


@pytest.fixture
def league():
    return build_league()
