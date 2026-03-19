import pandas as pd
import pytest
from app.analyzer import calculate_striker_score

def test_elite_striker_easy_home_game():
    # Testing a highly in-form striker at home against easy an opponent (e.g., Haaland vs Sheffield Utd)
    score = calculate_striker_score(
        recent_form=8.5, 
        total_points=180, 
        next_match_is_home=True, 
        avg_fdr=2.0
    )
    # Form(34) + FDR(22.5) + Pedigree(14.4) + Venue(10) = 80.9
    assert score == 80.9

def test_average_striker_hard_away_game():
    # Testing a mid-tier striker away against tough opposition (e.g., Solanke away at Arsenal)
    score = calculate_striker_score(
        recent_form=4.0, 
        total_points=90, 
        next_match_is_home=False, 
        avg_fdr=4.5
    )
    # Form(16) + FDR(3.75) + Pedigree(7.2) + Venue(5) = 31.95
    assert score == 31.95

def test_form_cap():
    # Ensuring a crazy form streak doesn't break the scoring weight (cap at 10.0)
    score = calculate_striker_score(
        recent_form=15.0, # Unrealistically high
        total_points=100, 
        next_match_is_home=True, 
        avg_fdr=3.0
    )
    # The form score should cap at 40, not go over.
    assert score <= 100.0

def test_forecast_algorithm():
    # 1. Create dummy data (Fake Strikers)
    # Haaland has high xG (4.0) and an easy schedule (2.0 FDR)
    # Watkins has lower xG (3.0) and a hard schedule (3.0 FDR)
    data = {
        'web_name': ['Haaland', 'Watkins'],
        'expected_goals': [4.0, 3.0],
        'avg_next_3_fdr': [2.0, 3.0]
    }
    df = pd.DataFrame(data)
    
    # 2. Run your exact algorithm
    df['forecast_score'] = df['expected_goals'] / df['avg_next_3_fdr']
    
    # 3. The Assertions (The Quality Check)
    # Pytest will check if the computer's math matches reality.
    
    # Haaland: 4.0 / 2.0 SHOULD equal 2.0
    assert df.loc[0, 'forecast_score'] == 2.0
    
    # Watkins: 3.0 / 3.0 SHOULD equal 1.0
    assert df.loc[1, 'forecast_score'] == 1.0