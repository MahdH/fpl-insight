import pytest

from app.manager import chip_availability, free_transfers, max_free_transfers


def history(transfers, chips=()):
    """A history where `transfers` is {gameweek: transfers made}; missing gameweeks mean no row."""
    return {
        "current": [{"event": gw, "event_transfers": made, "event_transfers_cost": 0} for gw, made in transfers.items()],
        "chips": [{"name": name, "event": gw} for name, gw in chips],
    }


# ---------- Free transfers ----------


@pytest.mark.parametrize("hist, current", [(None, 7), ({}, 7), ({"current": []}, 7), (history({1: 0}), None), (history({1: 0}), 0)])
def test_free_transfers_unknown_without_data(hist, current):
    assert free_transfers(hist, current) is None


def test_a_new_manager_has_one_free_transfer():
    assert free_transfers(history({1: 0}), current_event=1) == 1


def test_a_manager_who_joined_late_starts_counting_from_their_first_gameweek():
    assert free_transfers(history({5: 0}), current_event=5) == 1  # their first squad was unlimited


def test_unused_free_transfers_bank_up_each_week():
    # No transfers in gameweeks 2, 3 and 4: 1 + 3 banked.
    assert free_transfers(history({1: 0, 2: 0, 3: 0, 4: 0}), current_event=4) == 4


def test_using_the_free_transfer_each_week_keeps_it_at_one():
    assert free_transfers(history({1: 0, 2: 1, 3: 1, 4: 1}), current_event=4) == 1


def test_hits_do_not_go_negative():
    # Three transfers on one free: all free ones used, and next week starts again at 1.
    assert free_transfers(history({1: 0, 2: 3}), current_event=2) == 1


def test_the_bank_is_capped():
    quiet = history({gw: 0 for gw in range(1, 13)})
    assert free_transfers(quiet, current_event=12) == 5
    assert free_transfers(quiet, current_event=12, max_free=2) == 2


def test_spending_part_of_a_bank_leaves_the_rest():
    # Bank 3 after gameweeks 2 and 3 (1 -> 2 -> 3); gameweek 4 uses 2 -> 1 left, +1 for the new week.
    assert free_transfers(history({1: 0, 2: 0, 3: 0, 4: 2}), current_event=4) == 2


def test_playing_a_wildcard_or_free_hit_neither_spends_nor_earns_a_free_transfer():
    # Gameweeks 2, 3 unused: 1 -> 2 -> 3. Gameweek 4 is a Wildcard: still 3. Gameweek 5 unused: 4.
    wildcard = history({1: 0, 2: 0, 3: 0, 4: 15, 5: 0}, chips=[("wildcard", 4)])
    assert free_transfers(wildcard, current_event=5) == 4
    # Without the chip rule the 15 transfers would have burned the whole bank.
    no_chip = history({1: 0, 2: 0, 3: 0, 4: 15, 5: 0})
    assert free_transfers(no_chip, current_event=5) == 2
    freehit = history({1: 0, 2: 0, 3: 0, 4: 15, 5: 0}, chips=[("freehit", 4)])
    assert free_transfers(freehit, current_event=5) == 4


def test_bench_boost_and_triple_captain_do_not_change_free_transfers():
    hist = history({1: 0, 2: 1, 3: 0}, chips=[("bboost", 2), ("3xc", 3)])
    assert free_transfers(hist, current_event=3) == 2  # GW2 used 1 (+1), GW3 unused (+1)


def test_gameweeks_a_manager_skipped_count_as_no_transfers():
    # No row for gameweek 3: treated as an unused week.
    assert free_transfers(history({1: 0, 2: 0, 4: 0}), current_event=4) == 4


def test_max_free_transfers_comes_from_the_rules():
    assert max_free_transfers({"game_config": {"rules": {"max_extra_free_transfers": 4}}}) == 5
    assert max_free_transfers({"game_config": {"rules": {"max_extra_free_transfers": 1}}}) == 2
    assert max_free_transfers({}) == 5


# ---------- Chips ----------

WINDOWS = [
    {"name": name, "start_event": start, "stop_event": stop}
    for name, start, stop in [
        ("wildcard", 2, 19), ("wildcard", 20, 38), ("freehit", 2, 19), ("freehit", 20, 38),
        ("bboost", 1, 19), ("bboost", 20, 38), ("3xc", 1, 19), ("3xc", 20, 38),
    ]
]


def test_every_chip_is_available_to_a_manager_who_has_played_none():
    chips = chip_availability(WINDOWS, history({1: 0}), event=8)
    assert chips == {"available": ["wildcard", "freehit", "bboost", "3xc"], "used": []}


def test_a_played_chip_is_used_for_the_rest_of_its_half_of_the_season():
    hist = history({1: 0}, chips=[("freehit", 6), ("3xc", 3)])
    chips = chip_availability(WINDOWS, hist, event=8)
    assert chips == {"available": ["wildcard", "bboost"], "used": ["freehit", "3xc"]}


def test_chips_come_back_in_the_second_half_of_the_season():
    hist = history({1: 0}, chips=[("wildcard", 5), ("freehit", 6), ("bboost", 7), ("3xc", 3)])
    assert chip_availability(WINDOWS, hist, event=19)["available"] == []
    assert chip_availability(WINDOWS, hist, event=20)["available"] == ["wildcard", "freehit", "bboost", "3xc"]


def test_a_chip_played_in_the_second_half_does_not_use_up_the_first():
    hist = history({1: 0}, chips=[("wildcard", 25)])
    assert "wildcard" in chip_availability(WINDOWS, hist, event=8)["available"]
    assert "wildcard" in chip_availability(WINDOWS, hist, event=20)["used"]


def test_wildcard_and_free_hit_are_not_playable_in_gameweek_one():
    chips = chip_availability(WINDOWS, history({1: 0}), event=1)
    assert chips["available"] == ["bboost", "3xc"]


def test_a_chip_played_on_the_last_day_of_its_window_still_counts():
    hist = history({1: 0}, chips=[("wildcard", 19)])
    assert chip_availability(WINDOWS, hist, event=19)["used"] == ["wildcard"]


def test_no_history_or_windows_means_nothing_to_report():
    assert chip_availability(WINDOWS, None, event=8)["available"] == ["wildcard", "freehit", "bboost", "3xc"]
    assert chip_availability(None, history({1: 0}), event=8) == {"available": [], "used": []}
    assert chip_availability(WINDOWS, history({1: 0}), event=39) == {"available": [], "used": []}
