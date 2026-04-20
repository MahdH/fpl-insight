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

# Make sure your function is imported at the top!
# from analyzer import calculate_native_performer_index

def test_calculate_native_performer_index():
    
    # --- TEST 1: The Injury Bug (Should return 0.0) ---
    injured_player = {
        "chance_of_playing_next_round": 0, # Red flag!
        "minutes": 1000,
        "ict_index": 100.0,
        "bps": 200,
        "total_points": 100
    }
    # Even with an easy schedule [2, 2, 2], an injured player must score 0
    assert calculate_native_performer_index(injured_player, [2, 2, 2]) == 0.0


    # --- TEST 2: The "Low Minutes" Bug (Should return 0.0) ---
    bench_player = {
        "chance_of_playing_next_round": 100,
        "minutes": 85, # Played less than 360 minutes!
        "ict_index": 15.0, 
        "bps": 30,
        "total_points": 10
    }
    assert calculate_native_performer_index(bench_player, [3, 3, 3]) == 0.0


    # --- TEST 3: The Happy Path (An Elite Superstar) ---
    # We will test a perfect player with 900+ mins, elite stats, and an easy schedule.
    elite_player = {
        "chance_of_playing_next_round": 100,
        "minutes": 900,
        "ict_index": 120.0, # 120 / 10 games = 12.0 per 90 (Max 30 pts)
        "bps": 250,         # 250 / 10 games = 25.0 per 90 (Max 25 pts)
        "total_points": 200 # 200 points pace (Max 25 pts)
    }
    
    # Easy schedule: total difficulty is 6 (2 + 2 + 2)
    # Fixture math: ((15 - 6) / 12.0) * 20.0 = 15.0 pts
    # Total Expected Math: 30 + 25 + 25 + 15 = 95.0 Final Index
    
    easy_schedule = [2, 2, 2]
    assert calculate_native_performer_index(elite_player, easy_schedule) == 95.0


    # --- TEST 4: The Penalty Path (Good player, but terrible schedule) ---
    # Same elite player, but playing Man City, Arsenal, and Liverpool
    hard_schedule = [5, 5, 5] 
    
    # Hard schedule: total difficulty is 15 (5 + 5 + 5)
    # Fixture math: ((15 - 15) / 12.0) * 20.0 = 0.0 pts
    # Total Expected Math: 30 + 25 + 25 + 0 = 80.0 Final Index
    
    assert calculate_native_performer_index(elite_player, hard_schedule) == 80.0

    print("All tests passed! The math is safe.")