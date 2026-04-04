import pandas as pd
import pytest
from app.main import calculate_native_striker_index, calculate_native_performer_index

# STRIKER INDEX TESTS

def test_striker_perfect_scenario():
    """Testing the 'Happy Path' for a flawless striker at home."""
    # 1. ARRANGE: Perfect form, max points, easiest fixture, elite home attack
    test_player = {"form": "10.0", "total_points": 250}
    test_match = {"difficulty": 1, "is_home": True}
    test_team = {"strength_attack_home": 1300} # 1250+ grants the full +5 bonus

    # 2. ACT
    score = calculate_native_striker_index(test_player, test_match, test_team)

    # 3. ASSERT: Form(40) + Pedigree(30) + Difficulty(25) + Bonus(5) = 100.0
    assert score == 100.0


def test_striker_safeguard_caps():
    """Testing the Edge Case: Does the math break if a player exceeds the max limits?"""
    # 1. ARRANGE: Impossible stats (form 15.0, 300 points) in an away game
    test_player = {"form": "15.0", "total_points": 300}
    test_match = {"difficulty": 3, "is_home": False}
    test_team = {"strength_attack_away": 1050} # Below 1150, so +0 bonus

    # 2. ACT
    score = calculate_native_striker_index(test_player, test_match, test_team)

    # 3. ASSERT: 
    # Form capped at 10.0 -> 40 points
    # Points capped at 250 -> 30 points
    # Difficulty 3 -> 12.5 points
    # Bonus -> 0 points
    # Expected: 40 + 30 + 12.5 = 82.5
    assert score == 82.5

# PERFORMER INDEX TESTS

def test_performer_minutes_safeguard():
    """Testing the Edge Case: Does a sub with elite stats get filtered out?"""
    # 1. ARRANGE: Amazing stats, but only played 45 minutes total this season
    test_player = {"minutes": 45, "ict_index": "6.0", "bps": 12}
    test_match = {"is_home": True}
    test_team = {"strength_overall_home": 1300}

    # 2. ACT
    score = calculate_native_performer_index(test_player, test_match, test_team)

    # 3. ASSERT: The <90 minutes safeguard should trigger and return 0.0 immediately
    assert score == 0.0


def test_performer_elite_dominance():
    """Testing the 'Happy Path' for an elite performer."""
    # 1. ARRANGE: Played exactly 90 mins, elite ICT (12.0), elite BPS (25.0)
    test_player = {"minutes": 90, "ict_index": "12.0", "bps": 25}
    test_match = {"is_home": True}
    test_team = {"strength_overall_home": 1250} # Grants +5 bonus

    # 2. ACT
    score = calculate_native_performer_index(test_player, test_match, test_team)

    # 3. ASSERT: ICT(50) + BPS(45) + Bonus(5) = 100.0
    assert score == 100.0