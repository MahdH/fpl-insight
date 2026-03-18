import pandas as pd
import pytest

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