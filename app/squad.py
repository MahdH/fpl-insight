"""Squad optimiser: the best 15-player FPL squad, or the best way to change an existing one.

One mixed-integer model covers every case. A Wildcard or Free Hit lets it change all fifteen
players; a normal gameweek limits it to a number of transfers and charges points hits beyond the
free ones. The model enforces the game's real rules (budget, three per club, squad shape, valid
formations) jointly, so several transfers can't each spend the same money or stack a fourth
player from one club. Inputs are never mutated.
"""

from collections import defaultdict
from itertools import product
from typing import NamedTuple

BENCH_VALUE = 0.15  # bench cover plays roughly one minute in seven, so it counts for little
CAPTAIN_BONUS = 1.0  # the captain's points count twice, so he is worth his own value once more
HIT_COST = 4.0  # points deducted per transfer beyond the free ones
CHANGE_PENALTY = 1.0  # xP a transfer must beat to be worth making; smaller gains are noise
TIE_BREAK = 1e-4  # per tenth of £m spent, so equal squads resolve to the cheaper one
SOLVER_TIME_LIMIT = 8.0  # seconds; leaves headroom under a serverless function's time limit

DEFAULT_SHAPE = {1: 2, 2: 5, 3: 5, 4: 3}  # squad slots per position
DEFAULT_XI = {1: (1, 1), 2: (3, 5), 3: (2, 5), 4: (1, 3)}  # starters allowed per position


class OptimisationError(Exception):
    """No valid squad could be found."""


class Rules(NamedTuple):
    size: int
    xi_size: int
    club_limit: int
    shape: dict  # element_type -> squad slots
    xi: dict  # element_type -> (min, max) starters


class Lineup(NamedTuple):
    starters: list  # player ids, best first
    bench: list  # player ids, best first
    value: float  # starters + weighted bench + captain bonus


def squad_rules(bootstrap):
    """The game's squad rules from the API, falling back to the standard FPL ones."""
    config = (bootstrap.get("game_config") or {}).get("rules") or {}
    types = {t["id"]: t for t in bootstrap.get("element_types") or []}
    shape, xi = {}, {}
    for position in DEFAULT_SHAPE:
        info = types.get(position, {})
        shape[position] = info.get("squad_select") or DEFAULT_SHAPE[position]
        xi[position] = (
            info.get("squad_min_play") or DEFAULT_XI[position][0],
            info.get("squad_max_play") or DEFAULT_XI[position][1],
        )
    return Rules(
        size=config.get("squad_squadsize") or sum(shape.values()),
        xi_size=config.get("squad_squadplay") or 11,
        club_limit=config.get("squad_team_limit") or 3,
        shape=shape,
        xi=xi,
    )


def best_lineup(squad, values, rules, bench_value=BENCH_VALUE, captain_bonus=CAPTAIN_BONUS):
    """The best starting XI and captain for a fixed squad.

    Tries every legal formation, taking each position's highest-value players first.
    """
    by_position = defaultdict(list)
    for player in squad:
        by_position[player["element_type"]].append(player["id"])
    for ids in by_position.values():
        ids.sort(key=lambda pid: (-values.get(pid, 0.0), pid))

    positions = sorted(rules.xi)
    options = [range(rules.xi[p][0], rules.xi[p][1] + 1) for p in positions]

    best = None
    for counts in product(*options):
        if sum(counts) != rules.xi_size:
            continue
        if any(n > len(by_position[p]) for p, n in zip(positions, counts)):
            continue
        starters = [pid for p, n in zip(positions, counts) for pid in by_position[p][:n]]
        bench = [pid for p, n in zip(positions, counts) for pid in by_position[p][n:]]
        starters.sort(key=lambda pid: (-values.get(pid, 0.0), pid))
        bench.sort(key=lambda pid: (-values.get(pid, 0.0), pid))
        value = (
            sum(values.get(pid, 0.0) for pid in starters)
            + bench_value * sum(values.get(pid, 0.0) for pid in bench)
            + captain_bonus * values.get(starters[0], 0.0)
        )
        if best is None or value > best.value + 1e-9:
            best = Lineup(starters, bench, value)

    if best is None:  # an incomplete squad: no formation fits, so just take the best eleven
        ranked = sorted((p["id"] for p in squad), key=lambda pid: (-values.get(pid, 0.0), pid))
        best = Lineup(ranked[: rules.xi_size], ranked[rules.xi_size :], 0.0)
    return best


def optimize_squad(
    players,
    values,
    rules,
    budget,
    current=(),
    sell_prices=None,
    max_changes=None,
    free_transfers=None,
    hit_cost=HIT_COST,
    change_penalty=0.0,
    bench_value=BENCH_VALUE,
    captain_bonus=CAPTAIN_BONUS,
):
    """The ids of the best squad under the game's rules.

    `players` are the buyable candidates and must include everyone in `current`. `values` maps a
    player id to the points to maximise. `budget` is the most the squad may cost in tenths of £m,
    with `current` players valued at `sell_prices` (their market price if omitted). That makes it
    the bank plus the selling value of the current squad, or the whole budget for a fresh build.

    `max_changes` caps how many new players may join. With `free_transfers` set, each change beyond
    that many costs `hit_cost` points, so extra transfers are only made when they pay for themselves.
    `change_penalty` makes every change beat a minimum gain; it is also what keeps players on a tie.
    """
    # SciPy takes about a second to import, so only plan requests pay for it.
    import numpy as np
    from scipy.optimize import Bounds, LinearConstraint, milp
    from scipy.sparse import coo_matrix

    players = list(players)
    n = len(players)
    if n < rules.size:
        raise OptimisationError("Not enough players to build a squad.")

    index = {player["id"]: k for k, player in enumerate(players)}
    owned = [index[pid] for pid in current if pid in index]
    owned_set = set(owned)
    sell_prices = sell_prices or {}

    x, s, c = 0, n, 2 * n  # squad, starting XI and captain indicators
    hits = 3 * n  # points-hit slack variable
    objective = np.zeros(3 * n + 1)
    for k, player in enumerate(players):
        value = values.get(player["id"], 0.0)
        objective[x + k] = -bench_value * value + TIE_BREAK * (player.get("now_cost") or 0)
        objective[s + k] = -(1 - bench_value) * value
        objective[c + k] = -captain_bonus * value
    for k in owned:
        objective[x + k] -= change_penalty  # every player kept is a change avoided
    objective[hits] = hit_cost

    rows, cols, data, lower, upper = [], [], [], [], []

    def constrain(terms, low, high):
        row = len(lower)
        for col, coefficient in terms:
            rows.append(row)
            cols.append(col)
            data.append(coefficient)
        lower.append(low)
        upper.append(high)

    by_position, by_club = defaultdict(list), defaultdict(list)
    for k, player in enumerate(players):
        by_position[player["element_type"]].append(k)
        by_club[player["team"]].append(k)

    constrain([(x + k, 1) for k in range(n)], rules.size, rules.size)
    for position, slots in rules.shape.items():
        constrain([(x + k, 1) for k in by_position[position]], slots, slots)
    for k in range(n):
        constrain([(s + k, 1), (x + k, -1)], -np.inf, 0)  # only squad members start
        constrain([(c + k, 1), (s + k, -1)], -np.inf, 0)  # only starters captain
    constrain([(s + k, 1) for k in range(n)], rules.xi_size, rules.xi_size)
    for position, (low, high) in rules.xi.items():
        constrain([(s + k, 1) for k in by_position[position]], low, high)
    constrain([(c + k, 1) for k in range(n)], 1, 1)
    for members in by_club.values():
        if len(members) > rules.club_limit:
            constrain([(x + k, 1) for k in members], -np.inf, rules.club_limit)

    # Money: buying costs the market price, keeping a current player counts at his selling price.
    price = [
        sell_prices.get(player["id"], player.get("now_cost") or 0) if k in owned_set else (player.get("now_cost") or 0)
        for k, player in enumerate(players)
    ]
    constrain([(x + k, price[k]) for k in range(n)], -np.inf, budget)

    if max_changes is not None and owned:
        constrain([(x + k, 1) for k in owned], len(owned) - max_changes, np.inf)
    if free_transfers is not None and owned:
        constrain([(x + k, 1) for k in owned] + [(hits, 1)], len(owned) - free_transfers, np.inf)

    matrix = coo_matrix((data, (rows, cols)), shape=(len(lower), 3 * n + 1)).tocsr()
    integrality = np.ones(3 * n + 1)
    integrality[hits] = 0
    upper_bounds = np.ones(3 * n + 1)
    upper_bounds[hits] = rules.size

    result = milp(
        objective,
        constraints=LinearConstraint(matrix, np.array(lower), np.array(upper)),
        integrality=integrality,
        bounds=Bounds(np.zeros(3 * n + 1), upper_bounds),
        options={"time_limit": SOLVER_TIME_LIMIT},
    )
    if result.x is None:
        raise OptimisationError("No squad fits the budget and squad rules.")

    chosen = [players[k]["id"] for k in range(n) if result.x[x + k] > 0.5]
    if len(chosen) != rules.size:
        raise OptimisationError("The optimiser returned an incomplete squad.")
    return chosen
