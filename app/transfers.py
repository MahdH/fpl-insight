"""Squad-aware transfer suggestions: who to sell, and who to buy in their place.

Every candidate swap is a legal single transfer for the loaded squad. It keeps the position,
fits the budget (the sold player's price plus the bank) and respects the three-per-club limit.
Swaps are ranked by how many more expected points (xP) the buy returns than the sell over the
projection horizon. Inputs are never mutated.
"""

from collections import Counter, defaultdict
from typing import NamedTuple

from app.model import to_float

MAX_PER_CLUB = 3
MIN_START_PROBABILITY = 0.6  # a player you buy should be a near-certain starter
MIN_XP_GAIN = 1.0  # xP over the horizon; anything smaller is noise, not a transfer
BENCH_WEIGHT = 0.25  # upgrading a bench slot rarely changes your score, so it ranks lower
OVERPERFORMANCE_FLAG = 1.5  # goals above xG that mark a sell-high candidate

EMPTY_PROJECTION = {"xp_next": 0.0, "xp_horizon": 0.0, "minutes_security": 0.0}


class Swap(NamedTuple):
    out: dict
    into: dict
    xp_gain: float  # horizon xP of the buy minus the sell
    xp_gain_next: float  # same, for the next gameweek only
    cost_change: int  # tenths of £m; positive means the buy costs more
    reason: str  # why the sold player is the one to move


def sell_reason(player, projection):
    chance = player.get("chance_of_playing_next_round")
    if player.get("status") not in (None, "a") or (chance is not None and chance < 100):
        news = (player.get("news") or "").strip()
        if news:
            return news
        return f"{int(chance)}% chance of playing" if chance is not None else "Unavailable"

    if projection["minutes_security"] < MIN_START_PROBABILITY:
        return "Rotation risk: not a reliable starter"

    overperformance = to_float(player.get("goals_scored")) - to_float(player.get("expected_goals"))
    if overperformance >= OVERPERFORMANCE_FLAG:
        return f"Scoring {overperformance:.1f} above his xG, which rarely lasts"

    return "A better-projected option is available"


def suggest_transfers(squad, players, projections, bank, bench_ids=frozenset(), limit=3):
    """The best single transfers for `squad`, at most one per player sold and per player bought.

    `bank` is in tenths of £m, like FPL prices. `bench_ids` are squad members who aren't starting.
    """
    owned = {player["id"] for player in squad}
    clubs = Counter(player["team"] for player in squad)

    candidates = defaultdict(list)
    for player in players:
        projection = projections.get(player["id"])
        if player["id"] in owned or not projection:
            continue
        if projection["minutes_security"] < MIN_START_PROBABILITY or projection["xp_horizon"] <= 0:
            continue
        candidates[player["element_type"]].append((player, projection))

    options = []
    for out in squad:
        out_projection = projections.get(out["id"]) or EMPTY_PROJECTION
        weight = BENCH_WEIGHT if out["id"] in bench_ids else 1.0
        budget = (out.get("now_cost") or 0) + bank

        for into, in_projection in candidates[out["element_type"]]:
            cost = into.get("now_cost") or 0
            if cost > budget:
                continue
            # After the swap the club count is unchanged if both players share a club.
            if clubs[into["team"]] - int(into["team"] == out["team"]) >= MAX_PER_CLUB:
                continue

            gain = in_projection["xp_horizon"] - out_projection["xp_horizon"]
            if gain < MIN_XP_GAIN:
                continue

            cost_change = cost - (out.get("now_cost") or 0)
            swap = Swap(
                out=out,
                into=into,
                xp_gain=gain,
                xp_gain_next=in_projection["xp_next"] - out_projection["xp_next"],
                cost_change=cost_change,
                reason=sell_reason(out, out_projection),
            )
            options.append((gain * weight, swap))

    options.sort(key=lambda option: (-option[0], option[1].cost_change, option[1].into["id"]))

    chosen, sold, bought = [], set(), set()
    for _, swap in options:
        if swap.out["id"] in sold or swap.into["id"] in bought:
            continue
        sold.add(swap.out["id"])
        bought.add(swap.into["id"])
        chosen.append(swap)
        if len(chosen) == limit:
            break
    return chosen
