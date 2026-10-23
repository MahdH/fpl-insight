"""Turns a manager's squad, a chip and a transfer count into a concrete plan.

The squad optimiser decides who should be in the squad; this module compares that with the current
squad, pairs each player leaving with the player replacing him, explains why, and prices the plan
(including points hits). Inputs are never mutated.
"""

from collections import defaultdict
from typing import NamedTuple

from app.model import to_float
from app.squad import (
    BENCH_VALUE,
    CHANGE_PENALTY,
    HIT_COST,
    best_lineup,
    optimize_squad,
    squad_rules,
)

CHIPS = ("none", "wildcard", "freehit", "bboost", "3xc")
FULL_REBUILD = {"wildcard", "freehit"}  # chips that allow unlimited free transfers

REBUILD_KEEP_BIAS = 0.01  # on a rebuild, keep a player rather than swap him for an equal one
ROTATION_RISK = 0.6  # below this start probability a player is a rotation risk
OVERPERFORMANCE_FLAG = 1.5  # goals above xG that mark a sell-high candidate
SELL_PRICE_FLOOR = 0.85  # sanity bound when estimating selling prices from the squad's value

# chip -> (projection field to maximise, weight of the bench relative to the starters)
OBJECTIVES = {
    "none": ("xp_horizon", BENCH_VALUE),
    "3xc": ("xp_horizon", BENCH_VALUE),
    "wildcard": ("xp_horizon", BENCH_VALUE),
    "bboost": ("xp_horizon", 1.0),  # every player scores, so the bench matters as much as the XI
    "freehit": ("xp_next", BENCH_VALUE),  # one gameweek only
}


class Swap(NamedTuple):
    out: dict
    into: dict
    xp_gain: float  # buy minus sell, over the plan's horizon
    xp_gain_next: float  # same, next gameweek only
    cost_change: float  # £m the buy costs beyond the sale; negative means money back
    reason: str  # why the sold player is the one to move


class Plan(NamedTuple):
    chip: str
    swaps: list
    starters: list  # player dicts for the proposed XI
    bench: list
    captain: dict
    vice: dict
    new_ids: set  # players in the proposed squad who aren't in the current one
    current_xp: float  # best lineup of the current squad, in the plan's objective
    new_xp: float
    hit_cost: int
    free_transfers: int
    bank_after: float  # tenths of £m
    horizon: str  # "xp_horizon" or "xp_next"
    notes: list
    highlight: dict  # extra chip detail for the UI, or None


def sell_reason(player, projection):
    chance = player.get("chance_of_playing_next_round")
    if player.get("status") not in (None, "a") or (chance is not None and chance < 100):
        news = (player.get("news") or "").strip()
        if news:
            return news
        return f"{int(chance)}% chance of playing" if chance is not None else "Unavailable"

    if projection["minutes_security"] < ROTATION_RISK:
        return "Rotation risk: not a reliable starter"

    overperformance = to_float(player.get("goals_scored")) - to_float(player.get("expected_goals"))
    if overperformance >= OVERPERFORMANCE_FLAG:
        return f"Scoring {overperformance:.1f} above his xG, which rarely lasts"

    return "A better-projected option is available"


def estimate_sell_prices(squad, squad_value):
    """Selling prices, which the API doesn't publish per player.

    Players are sold for less than their market price once they've risen. The total selling value is
    known, so each player is scaled by the same factor: right in total, approximate per player.
    """
    market = sum(p.get("now_cost") or 0 for p in squad)
    ratio = 1.0
    if squad_value and market:
        ratio = min(1.0, max(SELL_PRICE_FLOOR, squad_value / market))
    return {p["id"]: (p.get("now_cost") or 0) * ratio for p in squad}


def pick_captains(starters, projections):
    """Captain and vice-captain: the two starters with the most expected points next gameweek."""
    ranked = sorted(starters, key=lambda p: (-projections[p["id"]]["xp_next"], p["id"]))
    return ranked[0], ranked[1] if len(ranked) > 1 else ranked[0]


def pair_swaps(leaving, joining, values, projections):
    """Match each player leaving with one joining at the same position, best replacement to worst sale."""
    by_position = defaultdict(lambda: ([], []))
    for player in leaving:
        by_position[player["element_type"]][0].append(player)
    for player in joining:
        by_position[player["element_type"]][1].append(player)

    pairs = []
    for outs, ins in by_position.values():
        outs.sort(key=lambda p: (values[p["id"]], p["id"]))
        ins.sort(key=lambda p: (-values[p["id"]], p["id"]))
        pairs.extend(zip(outs, ins))
    return pairs


def build_plan(master, projections, squad, bank, squad_value, chip, transfers, free_transfers):
    """Plan the best squad for `chip`.

    `squad` is the manager's 15 players, `bank` and `squad_value` are in tenths of £m, `transfers`
    is the most the manager wants to make (ignored for Wildcard and Free Hit) and `free_transfers`
    is how many of them are free. Raises OptimisationError if no valid squad exists.
    """
    rules = squad_rules(master)
    field, bench_value = OBJECTIVES[chip]
    values = {pid: projection[field] for pid, projection in projections.items()}

    current_ids = [p["id"] for p in squad]
    sell_prices = estimate_sell_prices(squad, squad_value)
    budget = bank + sum(sell_prices.values())

    # Only available players are worth buying, but you can always keep who you already have.
    candidates = {p["id"]: p for p in master["elements"] if p.get("status") == "a"}
    candidates.update({p["id"]: p for p in squad})

    rebuild = chip in FULL_REBUILD
    chosen = optimize_squad(
        list(candidates.values()),
        values,
        rules,
        budget=budget,
        current=current_ids,
        sell_prices=sell_prices,
        max_changes=None if rebuild else transfers,
        free_transfers=None if rebuild else free_transfers,
        hit_cost=HIT_COST,
        change_penalty=REBUILD_KEEP_BIAS if rebuild else CHANGE_PENALTY,
        bench_value=bench_value,
    )

    new_squad = [candidates[pid] for pid in chosen]
    lineup = best_lineup(new_squad, values, rules, bench_value)
    current_lineup = best_lineup(squad, values, rules, bench_value)
    by_id = {p["id"]: p for p in new_squad}

    kept, owned = set(chosen), set(current_ids)
    leaving = [p for p in squad if p["id"] not in kept]
    joining = [p for p in new_squad if p["id"] not in owned]
    swaps = [
        Swap(
            out=out,
            into=into,
            xp_gain=values[into["id"]] - values[out["id"]],
            xp_gain_next=projections[into["id"]]["xp_next"] - projections[out["id"]]["xp_next"],
            cost_change=round(((into.get("now_cost") or 0) - sell_prices[out["id"]]) / 10, 1),
            reason=sell_reason(out, projections[out["id"]]),
        )
        for out, into in pair_swaps(leaving, joining, values, projections)
    ]
    swaps.sort(key=lambda swap: (-swap.xp_gain, swap.out["id"]))

    starters = [by_id[pid] for pid in lineup.starters]
    bench = [by_id[pid] for pid in lineup.bench]
    captain, vice = pick_captains(starters, projections)

    paid_for = 0 if rebuild else max(0, len(swaps) - free_transfers)
    bank_after = bank + sum(sell_prices[p["id"]] for p in leaving) - sum(p.get("now_cost") or 0 for p in joining)

    plan = Plan(
        chip=chip,
        swaps=swaps,
        starters=starters,
        bench=bench,
        captain=captain,
        vice=vice,
        new_ids={p["id"] for p in joining},
        current_xp=current_lineup.value,
        new_xp=lineup.value,
        hit_cost=int(HIT_COST * paid_for),
        free_transfers=free_transfers,
        bank_after=bank_after,
        horizon=field,
        notes=[],
        highlight=None,
    )
    return annotate(plan, projections, transfers)


def annotate(plan, projections, requested):
    """Add the notes and chip-specific detail that explain a plan to the manager."""
    notes = []
    chip = plan.chip
    used = len(plan.swaps)

    if chip == "wildcard":
        notes.append("Wildcard: unlimited transfers with no points hit, built for the next 5 gameweeks.")
    elif chip == "freehit":
        notes.append("Free Hit: built for next gameweek only. Your squad reverts to its current players afterwards.")
    elif used == 0:
        notes.append("Your squad is already well set: no transfer is worth making right now.")
    elif requested and used < requested:
        if requested > plan.free_transfers:
            notes.append(
                f"Only {used} of {requested} transfers are worth making: transfers beyond your "
                f"{plan.free_transfers} free one{'s' if plan.free_transfers != 1 else ''} cost a "
                f"{int(HIT_COST)}-point hit each and wouldn't pay for themselves."
            )
        else:
            notes.append(f"Only {used} of {requested} transfers are worth making: the rest wouldn't add enough.")

    highlight = None
    if chip == "bboost":
        bench_xp = sum(projections[p["id"]]["xp_next"] for p in plan.bench)
        highlight = {"kind": "bench", "xp_next": round(bench_xp, 1), "players": [p["id"] for p in plan.bench]}
    elif chip == "3xc":
        captain_xp = projections[plan.captain["id"]]["xp_next"]
        # A normal captain already doubles his points; Triple Captain adds his points once more.
        highlight = {"kind": "captain", "player": plan.captain["id"], "xp_next": round(captain_xp, 1)}

    return plan._replace(notes=notes, highlight=highlight)
