import copy
import math

import pytest

from app.model import (
    HORIZON_DISCOUNT,
    Minutes,
    availability,
    expected_goals,
    fixture_points,
    minutes_profile,
    per90,
    poisson_at_least,
    position_priors,
    player_rates,
    project_players,
    scoring_rules,
    team_ratings,
)
from tests.conftest import make_player


# ---------- Building blocks ----------

def test_per90_falls_back_to_prior_without_minutes():
    assert per90(0, 0, 0.5) == pytest.approx(0.5)


def test_per90_shrinks_small_samples_toward_prior():
    raw = 9 / 900 * 90  # 0.9 per 90
    smoothed = per90(9, 900, 0.1)
    assert 0.1 < smoothed < raw
    # The more minutes played, the closer to the player's own rate.
    assert abs(per90(90, 9000, 0.1) - raw) < abs(smoothed - raw)


@pytest.mark.parametrize(
    "status, chance, expected",
    [("a", None, 1.0), ("d", 75, 0.75), ("i", 0, 0.0), ("i", None, 0.0), ("s", None, 0.0)],
)
def test_availability(status, chance, expected):
    assert availability({"status": status, "chance_of_playing_next_round": chance}) == pytest.approx(expected)


def test_minutes_profile_nailed_starter():
    mins = minutes_profile(make_player(1, 1, 4, minutes=630, starts=7), team_games=7)
    assert mins == Minutes(1.0, 1.0, 1.0, 1.0)


def test_minutes_profile_penalises_rotation_and_early_subs():
    rotation = minutes_profile(make_player(1, 1, 4, minutes=180, starts=3), team_games=7)
    assert rotation.p_play == pytest.approx(3 / 7)
    hooked = minutes_profile(make_player(2, 1, 4, minutes=7 * 55, starts=7), team_games=7)
    assert hooked.p_play == 1.0 and hooked.p_60 < 1.0 and hooked.share < 1.0


@pytest.mark.parametrize(
    "player, team_games",
    [
        (make_player(1, 1, 4, status="i", chance_of_playing_next_round=0), 7),
        (make_player(2, 1, 4, minutes=0, starts=0), 7),
        (make_player(3, 1, 4), 0),  # pre-season: no games played yet
    ],
)
def test_minutes_profile_zero_when_unavailable_or_unproven(player, team_games):
    mins = minutes_profile(player, team_games)
    assert (mins.p_play, mins.p_60, mins.share) == (0.0, 0.0, 0.0)


def test_poisson_at_least():
    assert poisson_at_least(0, 3) == 0.0
    assert poisson_at_least(5, 0) == 1.0
    assert poisson_at_least(1.0, 1) == pytest.approx(1 - math.exp(-1))
    assert poisson_at_least(12, 10) > poisson_at_least(8, 10)


def test_scoring_rules_prefer_live_values_and_fill_gaps():
    rules = scoring_rules({"game_config": {"scoring": {"assists": 4, "goals_scored": {"FWD": 5, "MID": "bad"}}}})
    assert rules["assists"] == 4
    assert rules["goals_scored"]["FWD"] == 5
    assert rules["goals_scored"]["MID"] == 5  # invalid live value -> default
    assert rules["clean_sheets"]["DEF"] == 4  # missing from live config -> default
    assert scoring_rules({}) == scoring_rules({"game_config": None})


# ---------- Teams and fixtures ----------

def test_team_ratings_follow_expected_goals(world):
    bootstrap, fixtures = world
    ratings, league = team_ratings(bootstrap["elements"], fixtures)
    assert all(r["games"] == 7 for r in ratings.values())
    assert ratings[2]["defence"] > ratings[3]["defence"] > ratings[1]["defence"]
    assert ratings[1]["attack"] > ratings[4]["attack"]
    assert league > 0


def test_team_ratings_preseason_uses_league_fallback():
    ratings, league = team_ratings([make_player(1, 1, 4, expected_goals="0")], fixtures=[])
    assert ratings[1]["attack"] == pytest.approx(league)
    assert ratings[1]["defence"] == pytest.approx(league)


def test_expected_goals_home_advantage():
    side = {"attack": 1.5, "defence": 1.5}
    assert expected_goals(side, side, 1.5, at_home=True) > expected_goals(side, side, 1.5, at_home=False)


def _context(world):
    bootstrap, fixtures = world
    ratings, league = team_ratings(bootstrap["elements"], fixtures)
    priors = position_priors(bootstrap["elements"])
    return ratings, league, priors, scoring_rules(bootstrap)


def test_attacker_scores_more_against_leaky_defence(world):
    ratings, league, priors, scoring = _context(world)
    striker = make_player(99, 3, 4, expected_goals="5.0", expected_assists="1.0")
    rates, mins = player_rates(striker, priors["FWD"]), minutes_profile(striker, 7)
    vs_leaky = fixture_points("FWD", rates, mins, ratings[3], ratings[2], True, league, scoring)
    vs_tight = fixture_points("FWD", rates, mins, ratings[3], ratings[1], True, league, scoring)
    away = fixture_points("FWD", rates, mins, ratings[3], ratings[2], False, league, scoring)
    assert vs_leaky > vs_tight
    assert vs_leaky > away


def test_defender_scores_more_against_weak_attack(world):
    ratings, league, priors, scoring = _context(world)
    defender = make_player(99, 3, 2)
    rates, mins = player_rates(defender, priors["DEF"]), minutes_profile(defender, 7)
    vs_weak = fixture_points("DEF", rates, mins, ratings[3], ratings[4], True, league, scoring)
    vs_strong = fixture_points("DEF", rates, mins, ratings[3], ratings[1], True, league, scoring)
    assert vs_weak > vs_strong


def test_defensive_contribution_adds_points(world):
    ratings, league, priors, scoring = _context(world)
    busy = make_player(98, 1, 2, defensive_contribution=84)  # 12 per 90, above the threshold of 10
    idle = make_player(99, 1, 2, defensive_contribution=0)
    args = (ratings[1], ratings[2], True, league, scoring)
    busy_pts = fixture_points("DEF", player_rates(busy, priors["DEF"]), minutes_profile(busy, 7), *args)
    idle_pts = fixture_points("DEF", player_rates(idle, priors["DEF"]), minutes_profile(idle, 7), *args)
    assert busy_pts - idle_pts > 0.5


# ---------- Full projections ----------

def test_projection_does_not_mutate_inputs(world):
    bootstrap, fixtures = world
    before = copy.deepcopy((bootstrap, fixtures))
    project_players(bootstrap, fixtures)
    assert (bootstrap, fixtures) == before


def test_projection_starts_at_the_next_deadline(world):
    bootstrap, fixtures = world
    _, first_gw = project_players(bootstrap, fixtures)
    assert first_gw == 8


def test_injured_and_unused_players_score_zero(world):
    projections, _ = project_players(*world)
    assert projections[12]["xp_horizon"] == 0.0
    assert projections[40]["xp_horizon"] == 0.0


def test_doubtful_player_is_discounted(world):
    bootstrap, fixtures = world
    healthy = copy.deepcopy(bootstrap)
    next(p for p in healthy["elements"] if p["id"] == 20).update(status="a", chance_of_playing_next_round=None)
    doubtful_xp = project_players(bootstrap, fixtures)[0][20]["xp_horizon"]
    healthy_xp = project_players(healthy, fixtures)[0][20]["xp_horizon"]
    assert doubtful_xp == pytest.approx(0.75 * healthy_xp, rel=0.02)


def test_underlying_numbers_beat_lucky_finishing(world):
    projections, _ = project_players(*world)
    # Player 11 has more goals (7 vs 5) but far less xG; the model prefers the elite xG profile.
    assert projections[10]["xp_horizon"] > projections[11]["xp_horizon"]
    assert projections[11]["goals_minus_xg"] == pytest.approx(5.5)


def test_rotation_risk_lowers_projection(world):
    projections, _ = project_players(*world)
    assert projections[13]["minutes_security"] == pytest.approx(1 / 7, abs=0.01)
    assert projections[13]["xp_horizon"] < projections[11]["xp_horizon"]


def test_blank_gameweek_scores_zero_next_but_counts_later(world):
    projections, _ = project_players(*world)
    assert projections[14]["xp_next"] == 0.0
    assert projections[14]["xp_horizon"] > 0.0


def test_double_gameweek_counts_both_fixtures(world):
    bootstrap, fixtures = world
    projections, _ = project_players(bootstrap, fixtures)
    single_gw = [f for f in fixtures if not (f["event"] == 8 and f["team_h"] == 3)]
    single, _ = project_players(bootstrap, single_gw)
    assert projections[2]["xp_next"] > single[2]["xp_next"] * 1.5


def test_later_gameweeks_are_discounted(world):
    bootstrap, fixtures = world
    one_gw, _ = project_players(bootstrap, fixtures, horizon=1)
    full, _ = project_players(bootstrap, fixtures, horizon=3)
    pid = 10
    assert one_gw[pid]["xp_horizon"] == pytest.approx(full[pid]["xp_next"], abs=0.01)
    assert full[pid]["xp_horizon"] < full[pid]["xp_next"] * (1 + HORIZON_DISCOUNT + HORIZON_DISCOUNT**2) + 0.01


def test_value_is_points_per_million(world):
    bootstrap, fixtures = world
    projections, _ = project_players(bootstrap, fixtures)
    assert projections[10]["value"] == pytest.approx(projections[10]["xp_horizon"] / 15.0, abs=0.01)


def test_no_upcoming_fixtures_returns_zeros():
    bootstrap = {"elements": [make_player(1, 1, 4)], "events": [], "teams": []}
    projections, first_gw = project_players(bootstrap, fixtures=[])
    assert first_gw is None
    assert projections[1]["xp_horizon"] == 0.0
