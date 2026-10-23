"""What a manager's FPL history says about their transfers and chips.

The public API doesn't publish free transfers, so they are replayed from the history. The rule was
checked against 698 real managers: every time a points hit revealed a manager's true free-transfer
count (462 times, 103 of them after a chip), the replay matched. The rule:

  * Everyone has 1 free transfer for the second gameweek they play.
  * Each gameweek adds 1, a transfer uses 1, and unused ones bank up to a cap (5 this season).
  * Playing a Wildcard or Free Hit neither spends nor earns a free transfer.
"""

TRANSFER_CHIPS = {"wildcard", "freehit"}
CHIP_ORDER = ("wildcard", "freehit", "bboost", "3xc")
DEFAULT_MAX_FREE_TRANSFERS = 5


def max_free_transfers(bootstrap):
    rules = (bootstrap.get("game_config") or {}).get("rules") or {}
    extra = rules.get("max_extra_free_transfers")
    return 1 + extra if isinstance(extra, int) else DEFAULT_MAX_FREE_TRANSFERS


def free_transfers(history, current_event, max_free=DEFAULT_MAX_FREE_TRANSFERS):
    """Free transfers the manager has for the gameweek after `current_event`, or None if unknown."""
    played = {row["event"]: row for row in (history or {}).get("current") or []}
    if not played or not current_event:
        return None

    chips = {chip["event"]: chip["name"] for chip in history.get("chips") or []}
    free = 1
    # Transfers in a manager's first gameweek are unlimited, so counting starts the week after.
    for event in range(min(played) + 1, current_event + 1):
        if chips.get(event) in TRANSFER_CHIPS:
            continue
        made = played[event]["event_transfers"] if event in played else 0
        free = min(free - min(made, free) + 1, max_free)
    return free


def chip_availability(chip_windows, history, event):
    """Which chips can still be played in gameweek `event`.

    Each chip comes in sets with a window of gameweeks (this season: 2-19 and 20-38), and one use of
    a chip is allowed per window. Returns {"available": [...], "used": [...]} in a stable order;
    chips with no window covering `event` appear in neither list.
    """
    played = (history or {}).get("chips") or []
    available, used = [], []
    for name in CHIP_ORDER:
        window = next(
            (w for w in chip_windows or [] if w["name"] == name and w["start_event"] <= event <= w["stop_event"]),
            None,
        )
        if window is None:
            continue
        already = any(
            chip["name"] == name and window["start_event"] <= chip["event"] <= window["stop_event"] for chip in played
        )
        (used if already else available).append(name)
    return {"available": available, "used": used}
