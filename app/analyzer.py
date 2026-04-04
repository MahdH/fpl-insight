import requests
import pandas as pd

def get_player_image_url(player_code):
    """Converts FPL player code into the official Premier League image URL."""
    return f"https://resources.premierleague.com/premierleague/photos/players/110x140/p{player_code}.png"

#-----------------------------old endpoints----------------------------

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
    strikers['form'] = pd.to_numeric(strikers['form'])
    strikers['total_points'] = pd.to_numeric(strikers['total_points'])
    
    # Join our new FDR math table with our Strikers table using the 'team' ID column
    strikers = pd.merge(strikers, avg_fdr_df, on='team', how='left')
    strikers['avg_next_3_fdr'] = strikers['avg_next_3_fdr'].fillna(3.0)
    
    # 6. APPLY THE ALGORITHM
    # Calculate the composite score using our Pytest-approved algorithm
    strikers['forecast_score'] = strikers.apply(
        lambda row: calculate_striker_score(
            recent_form=float(row['form']),
            total_points=int(row['total_points']),
            next_match_is_home=True,  # baseline assuming home match for now
            avg_fdr=float(row['avg_next_3_fdr'])
        ), axis=1
    )
    
    # 7. Sort by our new predictive score!
    top_strikers = strikers.sort_values(by='forecast_score', ascending=False).head(10)
    
    # Clean up the output to match what the frontend expects
    top_strikers = top_strikers.rename(columns={'web_name': 'name', 'form': 'recent_form'})
    
    columns_to_keep = ['name', 'recent_form', 'total_points', 'forecast_score']
    clean_df = top_strikers[columns_to_keep]
    
    return clean_df.to_dict(orient="records")

def calculate_striker_score(recent_form: float, total_points: int, next_match_is_home: bool, avg_fdr: float, max_season_points: int = 250) -> float:
    """
    Calculates a predictive forecast score (0-100) for a striker.
    """
    # 1. Form Score (Out of 40)
    # Assuming max realistic form over 5 games is around 10.0
    form_score = (min(recent_form, 10.0) / 10.0) * 40 

    # 2. Fixture Difficulty Score (Out of 30)
    # FDR is 1 to 5. We invert it so lower FDR = higher score. 
    # Formula: (5 - avg_fdr) / 4 * 30. (e.g., FDR 2 = 22.5 points)
    fdr_score = max(0, ((5.0 - avg_fdr) / 4.0) * 30)

    # 3. Season Pedigree Score (Out of 20)
    # Compares their total points to a theoretical season max (e.g., Haaland at 250)
    pedigree_score = (min(total_points, max_season_points) / max_season_points) * 20

    # 4. Home/Away Advantage (Out of 10)
    # 10 points for home, 5 points for away
    venue_score = 10 if next_match_is_home else 5

    # Calculate Total
    total_forecast_score = round(form_score + fdr_score + pedigree_score + venue_score, 2)
    
    return total_forecast_score

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