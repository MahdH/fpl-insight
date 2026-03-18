import requests
import pandas as pd

def get_strikers_forecast():
    # 1. Fetch Players Data
    url_bootstrap = "https://fantasy.premierleague.com/api/bootstrap-static/"
    bootstrap_data = requests.get(url_bootstrap).json()
    players_df = pd.DataFrame(bootstrap_data['elements'])
    
    # 2. Fetch Fixtures Data (To get the FDR)
    url_fixtures = "https://fantasy.premierleague.com/api/fixtures/"
    fixtures_data = requests.get(url_fixtures).json()
    fixtures_df = pd.DataFrame(fixtures_data)
    
    # 3. Filter for matches that haven't happened yet
    upcoming = fixtures_df[fixtures_df['finished'] == False].copy()
    
    # 4. CALCULATE TEAM FDR
    # Separate Home and Away fixtures to make a clean list of all upcoming games per team
    home_fdr = upcoming[['event', 'team_h', 'team_h_difficulty']].rename(
        columns={'team_h': 'team', 'team_h_difficulty': 'fdr'})
    away_fdr = upcoming[['event', 'team_a', 'team_a_difficulty']].rename(
        columns={'team_a': 'team', 'team_a_difficulty': 'fdr'})
    
    # Combine them and sort chronologically by Gameweek (event)
    all_team_fixtures = pd.concat([home_fdr, away_fdr]).sort_values(by=['team', 'event'])
    
    # Group by team, grab the next 3 matches, and calculate the average FDR
    next_3_fdr = all_team_fixtures.groupby('team').head(3)
    avg_fdr_df = next_3_fdr.groupby('team')['fdr'].mean().reset_index()
    avg_fdr_df.rename(columns={'fdr': 'avg_next_3_fdr'}, inplace=True)
    
    # 5. FILTER STRIKERS & MERGE
    strikers = players_df[players_df['element_type'] == 4].copy()
    strikers['expected_goals'] = pd.to_numeric(strikers['expected_goals'])
    
    # Join our new FDR math table with our Strikers table using the 'team' ID column
    strikers = pd.merge(strikers, avg_fdr_df, on='team', how='left')
    
    # 6. APPLY THE ALGORITHM
    # Calculate the composite score: xG penalized by fixture difficulty
    strikers['forecast_score'] = strikers['expected_goals'] / strikers['avg_next_3_fdr']
    
    # 7. Sort by our new predictive score!
    top_strikers = strikers.sort_values(by='forecast_score', ascending=False).head(10)
    
    # Clean up the output to look professional
    # (Rounding numbers to 2 decimal places for a cleaner UI)
    top_strikers['expected_goals'] = top_strikers['expected_goals'].round(2)
    top_strikers['avg_next_3_fdr'] = top_strikers['avg_next_3_fdr'].round(2)
    top_strikers['forecast_score'] = top_strikers['forecast_score'].round(2)
    
    columns_to_keep = ['web_name', 'expected_goals', 'avg_next_3_fdr', 'forecast_score']
    clean_df = top_strikers[columns_to_keep]
    
    return clean_df.to_dict(orient="records")

def get_top_in_form_players():
    # 1. Fetch the live data
    url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    response = requests.get(url)
    data = response.json()
    
    # 2. Load into Pandas
    df = pd.DataFrame(data['elements'])
    
    # 3. Convert the 'form' string into a math number
    # (Form is the 30-day / 5-week rolling average)
    df['form'] = pd.to_numeric(df['form'])
    
    # 4. Sort by the highest form and grab exactly the top 5
    top_5 = df.sort_values(by='form', ascending=False).head(5)
    
    # 5. Clean up the output
    columns_to_keep = ['web_name', 'form', 'total_points']
    clean_df = top_5[columns_to_keep]
    
    return clean_df.to_dict(orient="records")

def get_injured_players():
    url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    response = requests.get(url).json()
    df = pd.DataFrame(response['elements'])
    
    # Filter for anyone whose status is NOT 'a' (Available)
    injured = df[df['status'] != 'a'].copy()
    
    # Grab their name, the exact injury news, and their chance of playing
    columns_to_keep = ['web_name', 'status', 'news', 'chance_of_playing_next_round']
    clean_df = injured[columns_to_keep]
    
    return clean_df.to_dict(orient="records")