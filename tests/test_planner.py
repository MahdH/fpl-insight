import copy
from collections import Counter

import pytest

from app.model import project_players
from app.planner import (
    CHIPS,
    OBJECTIVES,
    build_plan,
    estimate_sell_prices,
    pair_swaps,
    pick_captains,
    sell_reason,
)
from app.squad import HIT_COST, CHANGE_PENALTY, squad_rules
from tests.conftest import make_player, weakest_squad


@pytest.fixture
def setup(league):
    bootstrap, fixtures = league
    projections, _ = project_players(bootstrap, fixtures)
    squad = weakest_squad(bootstrap, projections)
    by_id = {p["id"]: p for p in bootstrap["elements"]}

    def plan(chip="none", transfers=2, free=1, bank=10, value=None):
        value = value if value is not None else sum(p["now_cost"] for p in squad)
        return build_plan(bootstrap, projections, squad, bank, value, chip, transfers, free)

    return bootstrap, projections, squad, by_id, plan


def assert_legal(players, rules):
    assert len(players) == rules.size == len({p["id"] for p in players})
    assert Counter(p["element_type"] for p in players) == Counter(rules.shape)
    assert max(Counter(p["team"] for p in players).values()) <= rules.club_limit


def test_every_chip_has_an_objective():
    assert set(OBJECTIVES) == set(CHIPS)


# ---------- Normal transfers ----------


def test_a_normal_plan_is_a_legal_improvement_within_budget(setup):
    bootstrap, projections, squad, by_id, plan = setup
    result = plan(transfers=2, free=2, bank=10)
    rules = squad_rules(bootstrap)

    new_squad = result.starters + result.bench
    assert_legal(new_squad, rules)
    assert 1 <= len(result.swaps) <= 2
    assert result.new_xp > result.current_xp
    assert result.bank_after >= -1e-6  # never overspends the bank
    assert result.hit_cost == 0  # two free transfers, at most two made


def test_each_swap_keeps_the_position_and_buys_somebody_new(setup):
    _, projections, squad, _, plan = setup
    owned = {p["id"] for p in squad}
    for swap in plan(transfers=4, free=4).swaps:
        assert swap.out["id"] in owned and swap.into["id"] not in owned
        assert swap.out["element_type"] == swap.into["element_type"]
        assert swap.reason


def test_the_plan_only_buys_available_players(setup):
    bootstrap, _, _, _, plan = setup
    injured = {p["id"] for p in bootstrap["elements"] if p["status"] != "a"}
    for chip in ("none", "wildcard", "freehit", "bboost"):
        result = plan(chip=chip, transfers=5, free=5)
        assert injured.isdisjoint({s.into["id"] for s in result.swaps})
        assert injured.isdisjoint({p["id"] for p in result.starters + result.bench})


def test_the_transfer_cap_is_respected(setup):
    _, _, _, _, plan = setup
    for cap in (1, 2, 3, 5):
        assert len(plan(transfers=cap, free=cap).swaps) <= cap


def test_hits_are_charged_beyond_the_free_transfers_and_must_pay_for_themselves(setup):
    _, _, _, _, plan = setup
    result = plan(transfers=5, free=1)
    used = len(result.swaps)
    assert used > 1  # this poor squad is worth several transfers, so hits are in play
    assert result.hit_cost == int(HIT_COST) * (used - 1)

    free_only = plan(transfers=1, free=1)

    def objective(p):
        return (p.new_xp - p.current_xp) - CHANGE_PENALTY * len(p.swaps) - p.hit_cost

    # Net of hits and the per-transfer minimum, taking them must beat making just the free transfer.
    assert objective(result) >= objective(free_only) - 1e-6


def squad_with_an_injured_star(league):
    """An optimal squad whose best forward then gets injured: one clear, legal flaw.

    Returns the updated bootstrap, its projections, the squad and the injured player.
    """
    bootstrap, fixtures = league
    projections, _ = project_players(bootstrap, fixtures)
    best = build_plan(bootstrap, projections, weakest_squad(bootstrap, projections), 10, 900, "wildcard", 1, 1)
    star = max((p for p in best.starters if p["element_type"] == 4), key=lambda p: projections[p["id"]]["xp_horizon"])

    hurt = copy.deepcopy(bootstrap)
    victim = next(p for p in hurt["elements"] if p["id"] == star["id"])
    victim.update(status="i", chance_of_playing_next_round=0, news="Calf injury")
    hurt_projections, _ = project_players(hurt, fixtures)

    by_id = {p["id"]: p for p in hurt["elements"]}
    return hurt, hurt_projections, [by_id[p["id"]] for p in best.starters + best.bench], victim


def test_more_free_transfers_never_lower_the_plan_quality(setup):
    _, _, _, _, plan = setup
    gains = [plan(transfers=n, free=n).new_xp for n in (1, 2, 3, 4, 5)]
    assert gains == sorted(gains)


def test_an_already_strong_squad_needs_no_transfers(setup):
    bootstrap, projections, squad, _, plan = setup
    first = plan(chip="wildcard")  # the best possible squad...
    strong = first.starters + first.bench
    again = build_plan(bootstrap, projections, strong, 0, sum(p["now_cost"] for p in strong), "none", 3, 3)
    assert again.swaps == []
    assert "well set" in again.notes[0]


def test_the_injured_player_is_the_one_sold_and_the_hit_is_explained(league):
    hurt, projections, squad, injured = squad_with_an_injured_star(league)
    value = sum(p["now_cost"] for p in squad)

    result = build_plan(hurt, projections, squad, 50, value, "none", 3, 1)
    assert len(result.swaps) == 1 and result.hit_cost == 0
    assert result.swaps[0].out["id"] == injured["id"]
    assert result.swaps[0].reason == "Calf injury"
    assert result.notes == [
        "Only 1 of 3 transfers are worth making: transfers beyond your 1 free one cost a 4-point hit each "
        "and wouldn't pay for themselves."
    ]


def test_the_note_drops_the_hit_talk_when_the_transfers_were_all_free(league):
    hurt, projections, squad, _ = squad_with_an_injured_star(league)
    result = build_plan(hurt, projections, squad, 50, sum(p["now_cost"] for p in squad), "none", 3, 3)
    used = len(result.swaps)
    assert 1 <= used < 3 and result.hit_cost == 0
    assert result.notes == [f"Only {used} of 3 transfers are worth making: the rest wouldn't add enough."]
    assert "hit" not in result.notes[0]


def test_a_squad_over_budget_is_fixed_not_ignored(setup):
    # If the bank somehow can't cover the current squad, the plan must still be affordable.
    bootstrap, projections, squad, _, _ = setup
    value = sum(p["now_cost"] for p in squad)
    result = build_plan(bootstrap, projections, squad, -10, value, "none", 5, 5)
    assert result.bank_after >= -1e-6


def test_swaps_are_listed_biggest_gain_first(setup):
    _, _, _, _, plan = setup
    gains = [s.xp_gain for s in plan(transfers=5, free=5).swaps]
    assert gains == sorted(gains, reverse=True)


# ---------- Wildcard and Free Hit ----------


def test_a_wildcard_rebuilds_the_squad_with_no_hit(setup):
    bootstrap, _, squad, _, plan = setup
    result = plan(chip="wildcard", transfers=1, free=1)
    assert_legal(result.starters + result.bench, squad_rules(bootstrap))
    assert len(result.swaps) > 5  # a poor squad is mostly replaced
    assert result.hit_cost == 0
    assert result.horizon == "xp_horizon"
    assert any("Wildcard" in note for note in result.notes)


def test_a_wildcard_beats_any_number_of_ordinary_transfers(setup):
    _, _, _, _, plan = setup
    assert plan(chip="wildcard").new_xp >= plan(chip="none", transfers=5, free=5).new_xp - 1e-6


def test_a_wildcard_keeps_players_it_cannot_improve(setup):
    bootstrap, projections, squad, _, _ = setup
    best = build_plan(bootstrap, projections, squad, 0, 900, "wildcard", 1, 1)
    again_squad = best.starters + best.bench
    rebuilt = build_plan(bootstrap, projections, again_squad, 0, sum(p["now_cost"] for p in again_squad), "wildcard", 1, 1)
    assert rebuilt.swaps == []  # nothing to change on a squad that is already optimal


def test_a_free_hit_optimises_one_gameweek_only(setup):
    _, projections, _, _, plan = setup
    result = plan(chip="freehit")
    assert result.horizon == "xp_next"
    assert result.hit_cost == 0
    assert result.new_xp > result.current_xp
    assert any("Free Hit" in note and "reverts" in note for note in result.notes)


def test_a_rebuild_respects_the_squad_value_and_bank(setup):
    bootstrap, _, squad, _, plan = setup
    value = sum(p["now_cost"] for p in squad)
    result = plan(chip="wildcard", bank=25, value=value)
    new_cost = sum(p["now_cost"] for p in result.starters + result.bench)
    assert new_cost <= value + 25 + 1e-6


# ---------- Bench Boost and Triple Captain ----------


def test_bench_boost_values_the_bench(setup):
    _, projections, _, _, plan = setup
    boost = plan(chip="bboost", transfers=3, free=3)
    normal = plan(chip="none", transfers=3, free=3)
    bench_xp = lambda p: sum(projections[b["id"]]["xp_horizon"] for b in p.bench)
    assert bench_xp(boost) >= bench_xp(normal) - 1e-6
    assert boost.highlight["kind"] == "bench"
    assert boost.highlight["xp_next"] == pytest.approx(sum(projections[b["id"]]["xp_next"] for b in boost.bench), abs=0.06)


def test_triple_captain_names_the_best_captain_in_the_squad(setup):
    _, projections, _, _, plan = setup
    result = plan(chip="3xc")
    best = max(result.starters, key=lambda p: (projections[p["id"]]["xp_next"], -p["id"]))
    assert result.captain["id"] == best["id"]
    assert result.highlight == {
        "kind": "captain", "player": best["id"], "xp_next": round(projections[best["id"]]["xp_next"], 1),
    }


def test_captain_and_vice_are_different_starters(setup):
    _, _, _, _, plan = setup
    for chip in CHIPS:
        result = plan(chip=chip)
        starter_ids = {p["id"] for p in result.starters}
        assert result.captain["id"] in starter_ids and result.vice["id"] in starter_ids
        assert result.captain["id"] != result.vice["id"]


def test_the_proposed_lineup_is_a_legal_eleven(setup):
    bootstrap, _, _, _, plan = setup
    rules = squad_rules(bootstrap)
    for chip in CHIPS:
        result = plan(chip=chip)
        counts = Counter(p["element_type"] for p in result.starters)
        assert len(result.starters) == 11 and len(result.bench) == 4
        for position, (low, high) in rules.xi.items():
            assert low <= counts[position] <= high


def test_new_players_are_flagged(setup):
    _, _, squad, _, plan = setup
    result = plan(chip="wildcard")
    owned = {p["id"] for p in squad}
    in_squad = {p["id"] for p in result.starters + result.bench}
    assert result.new_ids == in_squad - owned


def test_planning_does_not_mutate_inputs(setup):
    bootstrap, projections, squad, _, plan = setup
    before = copy.deepcopy((bootstrap, projections, squad))
    for chip in CHIPS:
        plan(chip=chip)
    assert (bootstrap, projections, squad) == before


# ---------- Helpers ----------


def test_sell_prices_scale_to_the_known_squad_value():
    squad = [make_player(1, 1, 3, now_cost=100), make_player(2, 1, 3, now_cost=50)]
    prices = estimate_sell_prices(squad, squad_value=135)  # market 150, so 90% each
    assert prices == {1: pytest.approx(90), 2: pytest.approx(45)}
    assert sum(prices.values()) == pytest.approx(135)


def test_sell_prices_never_exceed_market_or_collapse():
    squad = [make_player(1, 1, 3, now_cost=100)]
    assert estimate_sell_prices(squad, squad_value=120) == {1: 100}  # value above market: capped at market
    assert estimate_sell_prices(squad, squad_value=10) == {1: pytest.approx(85)}  # absurd value: floored
    assert estimate_sell_prices(squad, squad_value=None) == {1: 100}
    assert estimate_sell_prices([], squad_value=100) == {}


def test_pair_swaps_matches_by_position_and_sorts_by_value():
    leaving = [make_player(1, 1, 4), make_player(2, 1, 4), make_player(3, 1, 3)]
    joining = [make_player(11, 2, 4), make_player(12, 2, 4), make_player(13, 2, 3)]
    values = {1: 5.0, 2: 1.0, 3: 2.0, 11: 8.0, 12: 9.0, 13: 4.0}
    pairs = pair_swaps(leaving, joining, values, projections=None)
    by_out = {out["id"]: into["id"] for out, into in pairs}
    assert by_out == {2: 12, 1: 11, 3: 13}  # worst sale gets the best replacement
    assert all(out["element_type"] == into["element_type"] for out, into in pairs)


def test_pick_captains_ranks_by_next_gameweek():
    players = [make_player(i, 1, 4) for i in (1, 2, 3)]
    projections = {1: {"xp_next": 3.0}, 2: {"xp_next": 7.0}, 3: {"xp_next": 5.0}}
    captain, vice = pick_captains(players, projections)
    assert (captain["id"], vice["id"]) == (2, 3)


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
