import copy
import random
from collections import Counter
from itertools import combinations, product

import pytest

from app.squad import (
    BENCH_VALUE,
    CAPTAIN_BONUS,
    HIT_COST,
    OptimisationError,
    Rules,
    best_lineup,
    optimize_squad,
    squad_rules,
)

# ---------- Rules ----------


def test_squad_rules_read_the_api():
    rules = squad_rules({
        "game_config": {"rules": {"squad_squadsize": 15, "squad_squadplay": 11, "squad_team_limit": 3}},
        "element_types": [{"id": 2, "squad_select": 5, "squad_min_play": 3, "squad_max_play": 5}],
    })
    assert (rules.size, rules.xi_size, rules.club_limit) == (15, 11, 3)
    assert rules.shape[2] == 5 and rules.xi[2] == (3, 5)


def test_squad_rules_fall_back_to_standard_fpl():
    rules = squad_rules({})
    assert rules.shape == {1: 2, 2: 5, 3: 5, 4: 3}
    assert rules.xi == {1: (1, 1), 2: (3, 5), 3: (2, 5), 4: (1, 3)}
    assert (rules.size, rules.xi_size, rules.club_limit) == (15, 11, 3)


# ---------- Best lineup for a fixed squad ----------


def standard_squad(values):
    """15 players, 2/5/5/3, ids 1-15, valued by `values` (id -> points)."""
    shape = [(1, 2), (2, 5), (3, 5), (4, 3)]
    squad, next_id = [], 0
    for position, count in shape:
        for _ in range(count):
            next_id += 1
            squad.append({"id": next_id, "element_type": position, "team": next_id, "now_cost": 50})
    return squad, {p["id"]: values[p["id"] - 1] for p in squad}


def test_lineup_has_a_legal_formation_and_best_players():
    squad, values = standard_squad([5, 1, 9, 8, 7, 6, 2, 9.5, 8.5, 7.5, 3, 2, 10, 9, 8])
    lineup = best_lineup(squad, values, squad_rules({}))
    by_id = {p["id"]: p for p in squad}
    counts = Counter(by_id[pid]["element_type"] for pid in lineup.starters)
    assert len(lineup.starters) == 11 and len(lineup.bench) == 4
    assert counts[1] == 1 and 3 <= counts[2] <= 5 and 2 <= counts[3] <= 5 and 1 <= counts[4] <= 3
    assert set(lineup.starters).isdisjoint(lineup.bench)
    # The goalkeeper, and the top forward, are always in.
    assert 1 in lineup.starters and 13 in lineup.starters


def test_lineup_value_counts_bench_and_captain():
    squad, values = standard_squad([4, 0, 3, 3, 3, 3, 0, 3, 3, 3, 0, 0, 3, 3, 3])
    lineup = best_lineup(squad, values, squad_rules({}), bench_value=0.5, captain_bonus=1.0)
    starters = sum(values[i] for i in lineup.starters)
    bench = sum(values[i] for i in lineup.bench)
    assert lineup.value == pytest.approx(starters + 0.5 * bench + max(values[i] for i in lineup.starters))


def test_lineup_prefers_the_formation_that_scores_most():
    # Four elite forwards but only three may start: the fourth sits on the bench.
    squad, values = standard_squad([1, 0, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1, 9, 9, 9])
    lineup = best_lineup(squad, values, squad_rules({}))
    assert {13, 14, 15} <= set(lineup.starters)


def test_lineup_of_an_incomplete_squad_still_returns_eleven():
    squad = [{"id": i, "element_type": 3, "team": i, "now_cost": 50} for i in range(1, 12)]
    values = {i: float(i) for i in range(1, 12)}
    lineup = best_lineup(squad, values, squad_rules({}))
    assert len(lineup.starters) == 11


def test_lineup_does_not_mutate_inputs():
    squad, values = standard_squad(list(range(15)))
    before = copy.deepcopy((squad, values))
    best_lineup(squad, values, squad_rules({}))
    assert (squad, values) == before


# ---------- The optimiser, checked against brute force ----------

MINI = Rules(
    size=6, xi_size=4, club_limit=2,
    shape={1: 1, 2: 2, 3: 2, 4: 1},
    xi={1: (1, 1), 2: (1, 2), 3: (1, 2), 4: (1, 1)},
)


def mini_market(rng):
    """12 players across 4 clubs with random prices and values."""
    layout = [(1, 2), (2, 4), (3, 4), (4, 2)]
    players, values, next_id = [], {}, 0
    for position, count in layout:
        for _ in range(count):
            next_id += 1
            players.append({"id": next_id, "element_type": position, "team": rng.randint(1, 4), "now_cost": rng.randint(40, 100)})
            values[next_id] = round(rng.uniform(0, 12), 2)
    return players, values


def squad_score(ids, players, values, current, free, penalty, hit_cost, bench_value=BENCH_VALUE):
    by_id = {p["id"]: p for p in players}
    lineup = best_lineup([by_id[i] for i in ids], values, MINI, bench_value, CAPTAIN_BONUS)
    new = len(set(ids) - set(current))
    hits = max(0, new - free) if free is not None else 0
    return lineup.value - penalty * new - hit_cost * hits


def brute_force(players, values, budget, current, prices, max_changes, free, penalty, hit_cost):
    """Score every legal squad and return the best score."""
    by_position = {p: [x for x in players if x["element_type"] == p] for p in MINI.shape}
    best = None
    for combo in product(*(combinations(by_position[p], MINI.shape[p]) for p in MINI.shape)):
        squad = [player for group in combo for player in group]
        ids = [p["id"] for p in squad]
        if max(Counter(p["team"] for p in squad).values()) > MINI.club_limit:
            continue
        if sum(prices[p["id"]] if p["id"] in current else p["now_cost"] for p in squad) > budget:
            continue
        if max_changes is not None and len(set(ids) - set(current)) > max_changes:
            continue
        score = squad_score(ids, players, values, current, free, penalty, hit_cost)
        if best is None or score > best:
            best = score
    return best


@pytest.mark.parametrize("seed", range(30))
def test_optimiser_matches_brute_force(seed):
    rng = random.Random(seed)
    players, values = mini_market(rng)
    by_position = {p: [x for x in players if x["element_type"] == p] for p in MINI.shape}

    # Start from a random legal squad; try to find one that obeys the club limit.
    for _ in range(200):
        current = [x["id"] for p in MINI.shape for x in rng.sample(by_position[p], MINI.shape[p])]
        teams = Counter(next(q["team"] for q in players if q["id"] == i) for i in current)
        if max(teams.values()) <= MINI.club_limit:
            break
    else:
        pytest.skip("no legal starting squad for this seed")

    by_id = {p["id"]: p for p in players}
    prices = {i: by_id[i]["now_cost"] * rng.choice([1.0, 0.97]) for i in current}
    bank = rng.choice([0, 5, 20, 60])
    budget = bank + sum(prices.values())
    max_changes = rng.choice([None, 1, 2, 3])
    free = rng.choice([None, 1, 2]) if max_changes is not None else None
    penalty = rng.choice([0.0, 1.0])

    chosen = optimize_squad(
        players, values, MINI, budget, current=current, sell_prices=prices,
        max_changes=max_changes, free_transfers=free, hit_cost=HIT_COST, change_penalty=penalty,
    )
    expected = brute_force(players, values, budget, set(current), prices, max_changes, free, penalty, HIT_COST)
    got = squad_score(chosen, players, values, set(current), free, penalty, HIT_COST)

    assert got == pytest.approx(expected, abs=0.02)  # the 0.02 absorbs the solver's cheaper-squad tie-break
    # And the squad it returns is legal.
    squad = [by_id[i] for i in chosen]
    assert len(set(chosen)) == MINI.size
    assert Counter(p["element_type"] for p in squad) == Counter(MINI.shape)
    assert max(Counter(p["team"] for p in squad).values()) <= MINI.club_limit
    assert sum(prices[p["id"]] if p["id"] in current else p["now_cost"] for p in squad) <= budget + 1e-6
    if max_changes is not None:
        assert len(set(chosen) - set(current)) <= max_changes


# ---------- Behaviour on the full league ----------


def league_inputs(league):
    from app.model import project_players

    bootstrap, fixtures = league
    projections, _ = project_players(bootstrap, fixtures)
    values = {pid: p["xp_horizon"] for pid, p in projections.items()}
    return bootstrap, projections, values, squad_rules(bootstrap)


def test_a_fresh_squad_respects_every_rule(league):
    bootstrap, _, values, rules = league_inputs(league)
    players = [p for p in bootstrap["elements"] if p["status"] == "a"]
    chosen = optimize_squad(players, values, rules, budget=1000)
    by_id = {p["id"]: p for p in players}
    squad = [by_id[i] for i in chosen]
    assert len(squad) == 15
    assert Counter(p["element_type"] for p in squad) == Counter({1: 2, 2: 5, 3: 5, 4: 3})
    assert max(Counter(p["team"] for p in squad).values()) <= 3
    assert sum(p["now_cost"] for p in squad) <= 1000


def test_a_bigger_budget_never_hurts(league):
    bootstrap, _, values, rules = league_inputs(league)
    players = [p for p in bootstrap["elements"] if p["status"] == "a"]

    def best(budget):
        ids = optimize_squad(players, values, rules, budget=budget)
        return best_lineup([p for p in players if p["id"] in ids], values, rules).value

    assert best(900) <= best(1000) <= best(1200)


def test_zero_changes_returns_the_current_squad(league):
    bootstrap, projections, values, rules = league_inputs(league)
    from tests.conftest import weakest_squad

    squad = weakest_squad(bootstrap, projections)
    players = [p for p in bootstrap["elements"] if p["status"] == "a"] + squad
    ids = [p["id"] for p in squad]
    chosen = optimize_squad(
        {p["id"]: p for p in players}.values(), values, rules,
        budget=sum(p["now_cost"] for p in squad) + 500, current=ids, max_changes=0,
    )
    assert set(chosen) == set(ids)


def test_unaffordable_requests_raise_cleanly(league):
    bootstrap, _, values, rules = league_inputs(league)
    players = [p for p in bootstrap["elements"] if p["status"] == "a"]
    with pytest.raises(OptimisationError):
        optimize_squad(players, values, rules, budget=100)  # £10m cannot buy fifteen players


def test_too_few_players_raise_cleanly(league):
    bootstrap, _, values, rules = league_inputs(league)
    with pytest.raises(OptimisationError):
        optimize_squad(bootstrap["elements"][:10], values, rules, budget=1000)


def test_optimiser_does_not_mutate_inputs(league):
    bootstrap, _, values, rules = league_inputs(league)
    players = [p for p in bootstrap["elements"] if p["status"] == "a"]
    before = copy.deepcopy((players, values))
    optimize_squad(players, values, rules, budget=1000)
    assert (players, values) == before
