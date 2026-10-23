import copy

import pytest

from app.model import project_players
from app.transfers import MAX_PER_CLUB, MIN_XP_GAIN, sell_reason, suggest_transfers
from tests.conftest import make_player


@pytest.fixture
def market(world):
    bootstrap, fixtures = world
    projections, _ = project_players(bootstrap, fixtures)
    players = {p["id"]: p for p in bootstrap["elements"]}

    def suggest(squad_ids, bank=0, bench=(), limit=3):
        squad = [players[i] for i in squad_ids]
        return suggest_transfers(squad, bootstrap["elements"], projections, bank, set(bench), limit)

    return suggest, players, projections


def test_injured_player_is_sold_for_an_affordable_replacement(market):
    suggest, *_ = market
    swap = suggest([12, 30, 1], bank=0)[0]
    assert (swap.out["id"], swap.into["id"]) == (12, 11)  # the elite forward costs more than he can afford
    assert swap.reason == "Knee injury"
    assert swap.xp_gain > 10


def test_bank_unlocks_pricier_targets(market):
    suggest, *_ = market
    broke = suggest([12], bank=0)[0]
    flush = suggest([12], bank=100)[0]
    assert broke.into["id"] == 11
    assert flush.into["id"] == 10
    assert flush.cost_change == 90  # £9.0m more, in tenths


def test_swaps_keep_the_position(market):
    suggest, _, _ = market
    for swap in suggest([12, 30, 1, 20], bank=200, limit=10):
        assert swap.into["element_type"] == swap.out["element_type"]


def test_never_suggests_players_already_owned(market):
    suggest, *_ = market
    squad = [12, 11, 10]
    for swap in suggest(squad, bank=200, limit=10):
        assert swap.into["id"] not in squad


def test_three_per_club_limit_is_respected(market):
    suggest, players, _ = market
    squad = [1, 30, 31, 13]  # three players from club 1
    assert sum(players[i]["team"] == 1 for i in squad) == MAX_PER_CLUB
    swaps = suggest(squad, bank=200, limit=10)
    forward_swap = next(s for s in swaps if s.out["id"] == 13)
    assert forward_swap.into["team"] != 1  # the club-1 striker would be a fourth


def test_swapping_within_a_full_club_is_allowed(market):
    suggest, *_ = market
    swap = suggest([1, 30, 12], bank=200)[0]  # club 1 sells an injured forward for a club-1 forward
    assert (swap.out["id"], swap.into["id"]) == (12, 10)


def test_each_player_is_sold_and_bought_at_most_once(market):
    suggest, *_ = market
    swaps = suggest([12, 13], bank=200, limit=5)
    assert len(swaps) == 2
    assert len({s.out["id"] for s in swaps}) == 2
    assert len({s.into["id"] for s in swaps}) == 2
    assert swaps[0].xp_gain >= swaps[1].xp_gain


def test_bench_slots_rank_below_starters(market):
    suggest, *_ = market
    starters = suggest([11, 13], bank=200)
    assert starters[0].out["id"] == 13  # biggest raw upgrade when both start

    with_bench = suggest([11, 13], bank=200, bench=[13])
    assert with_bench[0].out["id"] == 11  # the same upgrade counts for less on the bench
    assert with_bench[0].xp_gain < starters[0].xp_gain


def test_rotation_risks_are_never_recommended(market):
    suggest, *_ = market
    for swap in suggest([12, 20, 30, 1], bank=500, limit=10):
        assert swap.into["id"] != 13  # starts one game in seven


def test_no_suggestion_when_the_squad_is_already_strong(market):
    suggest, *_ = market
    assert suggest([10], bank=0) == []


def test_gains_below_the_threshold_are_ignored(market):
    suggest, _, projections = market
    for swap in suggest([12, 30, 1, 21], bank=200, limit=10):
        assert swap.xp_gain >= MIN_XP_GAIN


def test_empty_or_unknown_squad_returns_nothing(market):
    suggest, *_ = market
    assert suggest([], bank=100) == []


def test_limit_is_respected(market):
    suggest, *_ = market
    assert len(suggest([12, 13, 30, 1, 20], bank=200, limit=2)) <= 2


def test_inputs_are_not_mutated(world):
    bootstrap, fixtures = world
    projections, _ = project_players(bootstrap, fixtures)
    squad = [p for p in bootstrap["elements"] if p["id"] in (12, 13)]
    before = copy.deepcopy((bootstrap, squad, projections))
    suggest_transfers(squad, bootstrap["elements"], projections, 100)
    assert (bootstrap, squad, projections) == before


# ---------- Reasons ----------

@pytest.mark.parametrize(
    "player, minutes_security, expected",
    [
        (make_player(1, 1, 3, status="i", chance_of_playing_next_round=0, news="Hamstring injury"), 0.0, "Hamstring injury"),
        (make_player(2, 1, 3, status="d", chance_of_playing_next_round=50, news=""), 0.5, "50% chance of playing"),
        (make_player(3, 1, 3, status="u", chance_of_playing_next_round=None, news=""), 0.0, "Unavailable"),
        (make_player(4, 1, 3), 0.3, "Rotation risk: not a reliable starter"),
        (make_player(5, 1, 3, goals_scored=6, expected_goals="2.0"), 1.0, "Scoring 4.0 above his xG, which rarely lasts"),
        (make_player(6, 1, 3), 1.0, "A better-projected option is available"),
    ],
)
def test_sell_reasons(player, minutes_security, expected):
    assert sell_reason(player, {"minutes_security": minutes_security}) == expected
