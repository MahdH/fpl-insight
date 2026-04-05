import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from cachetools import cached, TTLCache
from app.analyzer import get_strikers_forecast, get_top_in_form_players, get_injured_players, get_player_image_url
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI(title="Football Performance Forecaster")

# Mount the static folder
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Create the route for the main URL ("/")
@app.get("/")
def serve_dashboard():
    return FileResponse("static/index.html")

# Tells API to accept requests from local HTML file
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all websites to fetch your data
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Using TTL Cache to refresh the data periodically (e.g., max 100 items, expires after 3600 seconds)
master_db_cache = TTLCache(maxsize=5, ttl=3600)
topform_cache = TTLCache(maxsize=100, ttl=3600)
injured_cache = TTLCache(maxsize=100, ttl=3600)
striker_cache = TTLCache(maxsize=100, ttl=3600)
risk_cache = TTLCache(maxsize=100, ttl=3600)
fixture_cache = TTLCache(maxsize=5, ttl=3600)

"""
@app.get("/")
def root():
    return {"message": "Football Analysis API is running and auto deploying updates!"}
"""
#----------------------------new endpoints----------------------------

@cached(cache=master_db_cache)
def fetch_master_fpl_data():
    """Downloads the entire FPL database once an hour."""
    print("Fetching master database from official FPL servers...")
    response = requests.get("https://fantasy.premierleague.com/api/bootstrap-static/")
    return response.json()

@cached(cache=fixture_cache)
def fetch_upcoming_fixtures():
    """Downloads the future Premier League schedule."""
    print("Fetching upcoming fixtures from FPL servers...")
    # The ?future=1 tag tells FPL to ignore games that already happened
    response = requests.get("https://fantasy.premierleague.com/api/fixtures/?future=1")
    return response.json()

@app.get("/api/top-picks")
def get_top_picks():
    # 1. Grab both databases instantly from local memory
    master_data = fetch_master_fpl_data()
    fixtures = fetch_upcoming_fixtures()
    
    all_players = master_data["elements"]
    
    # 2. Create a fast lookup dictionary for Team Data so we can access attack strengths instantly
    team_lookup = {team["id"]: team for team in master_data["teams"]}
    
    # 3. Figure out exactly which Gameweek is next
    upcoming = [f for f in fixtures if f["event"] is not None]
    if not upcoming:
        return {"top_picks": []}
    next_gw = upcoming[0]["event"]
    next_gw_matches = [f for f in upcoming if f["event"] == next_gw]
    
    # 4. Filter for Forwards only
    forwards = [p for p in all_players if p["element_type"] == 4]
    
    # 5. Run the Proprietary Algorithm
    for player in forwards:
        team_id = player["team"]
        player_team_data = team_lookup.get(team_id, {})
        
        # Find the specific match this player's team is playing next
        player_match = None
        is_home = True
        match_difficulty = 3 # Default fallback
        
        for match in next_gw_matches:
            if match["team_h"] == team_id:
                player_match = match
                is_home = True
                match_difficulty = match["team_h_difficulty"]
                break
            elif match["team_a"] == team_id:
                player_match = match
                is_home = False
                match_difficulty = match["team_a_difficulty"]
                break
                
        # Package the match data for the algorithm
        next_match_data = {
            "difficulty": match_difficulty,
            "is_home": is_home
        }
        
        # Execute the math and attach the score directly to the player's profile
        player["custom_index"] = calculate_native_striker_index(
            player=player, 
            next_match=next_match_data, 
            team_data=player_team_data
        )
        
    # 6. Sort by YOUR algorithm instead of standard FPL metrics
    forwards.sort(key=lambda x: x["custom_index"], reverse=True)
    
    # 7. Grab Top 3 and format for the Frontend
    top_3 = forwards[:3]
    formatted_picks = []
    
    for player in top_3:
        formatted_picks.append({
            "name": f"{player['first_name'][0]}. {player['second_name']}" if player != top_3[0] else f"{player['first_name']} {player['second_name']}",
            "position": "FWD",
            "price": f"£{player['now_cost'] / 10:.1f}m",
            "projected_points": player["ep_next"],
            "custom_index": player["custom_index"], # Send the custom score to the UI!
            "ownership_percent": player["selected_by_percent"],
            "image_url": get_player_image_url(player["photo"].replace(".jpg", ""))
        })
        
    return {"top_picks": formatted_picks}

def calculate_native_striker_index(player, next_match, team_data):
    """
    Calculates a proprietary 100-point index using FPL's native attack strength ratings.
    """
    # 1. Form Score (Max: 40)
    form_value = min(float(player.get("form", 0.0)), 10.0)
    form_score = (form_value / 10.0) * 40.0
    
    # 2. Pedigree Score (Max: 30)
    points_value = min(player.get("total_points", 0), 250)
    pedigree_score = (points_value / 250.0) * 30.0
    
    # 3. Base Matchup Difficulty (Max: 25)
    difficulty = next_match.get("difficulty", 3)
    difficulty_score = ((5.0 - difficulty) / 4.0) * 25.0
    
    # 4. Dynamic Environment Bonus (Max: 5)
    is_home = next_match.get("is_home", True)
    
    # Grab FPL's native attack rating based on location
    if is_home:
        attack_strength = team_data.get("strength_attack_home", 1100)
    else:
        attack_strength = team_data.get("strength_attack_away", 1100)
        
    dynamic_bonus = 0.0
    
    # Thresholds based on FPL's 1000-1350 scale
    if attack_strength >= 1150:  # "Good" attacking team
        dynamic_bonus += 2.0
    if attack_strength >= 1250:  # "Elite" attacking team
        dynamic_bonus += 3.0
        
    difficulty_score += dynamic_bonus
    
    # 5. Final Aggregation
    final_index = form_score + pedigree_score + difficulty_score
    return round(final_index, 1)

@app.get("/api/risk-alerts")
@cached(cache=risk_cache)
def get_transfer_out_alert():
    # 1. Get the data
    data = fetch_master_fpl_data()
    all_players = data["elements"]
    
    # 2. Filter for "Flagged" players
    # Status 'i' = Injured, 's' = Suspended, 'd' = Doubtful
    # We also check chance_of_playing_next_round < 100
    flagged_players = [
        p for p in all_players 
        if p["status"] != "a" and (p["chance_of_playing_next_round"] is not None and p["chance_of_playing_next_round"] < 100)
    ]
    
    # 3. Sort by Ownership Percentage
    # We want to highlight the "most painful" injury for the community
    flagged_players.sort(key=lambda x: float(x["selected_by_percent"]), reverse=True)
    
    if not flagged_players:
        return {"alert": None}
        
    # 4. Grab the most critical one (Top of the list)
    critical_player = flagged_players[0]
    
    # 5. Format for the Red Bento Card
    return {
        "alert": {
            "name": critical_player["second_name"],
            "full_name": f"{critical_player['first_name']} {critical_player['second_name']}",
            "reason": critical_player["news"], # e.g., "Hamstring injury - Expected return 12 Apr"
            "chance": f"{critical_player['chance_of_playing_next_round']}%",
            "ownership": f"{critical_player['selected_by_percent']}%",
            "image_url": get_player_image_url(critical_player["photo"].replace(".jpg", ""))
        }
    }

@app.get("/api/target-fixture")
def get_target_fixture():
    # 1. Grab both databases instantly from local memory
    master_data = fetch_master_fpl_data()
    fixtures = fetch_upcoming_fixtures()
    
    # 2. Create translation dictionaries
    # The fixture API only gives us numbers (Team 1 vs Team 14). 
    # We need to map those numbers to Short Names (ARS) and Overall Strength ratings.
    team_names = {team["id"]: team["short_name"] for team in master_data["teams"]}
    team_strength = {team["id"]: team["strength"] for team in master_data["teams"]}
    
    # 3. Find exactly which Gameweek is next
    # Filter out any weird null data, and grab the event number of the very first upcoming match
    upcoming = [f for f in fixtures if f["event"] is not None]
    if not upcoming:
        return {"target_fixture": None}
    next_gw = upcoming[0]["event"]
    
    # 4. Isolate only the matches happening in that specific next Gameweek
    next_gw_matches = [f for f in upcoming if f["event"] == next_gw]
    
    # 5. The Sorting Algorithm (The Secret Sauce)
    # We want a fixture where the Home Team has a very low difficulty rating (e.g., 2),
    # BUT we also want to make sure the Home Team is actually a powerhouse (high strength).
    # We sort by lowest difficulty first, then highest team strength.
    target_matches = sorted(
        next_gw_matches,
        key=lambda x: (x["team_h_difficulty"], -team_strength[x["team_h"]])
    )
    
    # 6. Grab the absolute best match
    best_match = target_matches[0]
    home_team = team_names[best_match["team_h"]]
    away_team = team_names[best_match["team_a"]]
    
    # 7. Format for the Blue Bento Card
    return {
        "target_fixture": {
            "match": f"{home_team} vs {away_team}",
            "difficulty": best_match["team_h_difficulty"],
            "max_difficulty": 5
        }
    }

def calculate_native_performer_index(player, next_match, team_data):

    minutes = float(player.get("minutes", 0))
    
    # Safeguard: If they haven't played at least one full game this season, they can't be a top performer
    if minutes < 90:
        return 0.0

    # 1. Underlying Threat Score (Max: 50)
    # We convert cumulative ICT Index to a "Per 90 Minutes" metric. 
    # An elite ICT/90 is around 12.0.
    ict = float(player.get("ict_index", 0.0))
    ict_per_90 = (ict / minutes) * 90.0
    ict_score = min((ict_per_90 / 12.0) * 50.0, 50.0)
    
    # 2. Pitch Dominance Score (Max: 45)
    # BPS (Bonus Points System) measures tackles, key passes, and accuracy.
    # An elite BPS/90 is around 25.0.
    bps = float(player.get("bps", 0.0))
    bps_per_90 = (bps / minutes) * 90.0
    bps_score = min((bps_per_90 / 25.0) * 45.0, 45.0)
    
    # 3. Dynamic Environment Bonus (Max: 5)
    # Because Top Performers can be defenders or attackers, we use 'strength_overall'
    is_home = next_match.get("is_home", True)
    
    if is_home:
        team_strength = team_data.get("strength_overall_home", 1100)
    else:
        team_strength = team_data.get("strength_overall_away", 1100)
        
    dynamic_bonus = 0.0
    
    # Apply the FPL 1000-1350 scale thresholds
    if team_strength >= 1150:  # "Good" team environment
        dynamic_bonus += 2.0
    if team_strength >= 1250:  # "Elite" team environment
        dynamic_bonus += 3.0
        
    # 4. Final Aggregation
    final_index = ict_score + bps_score + dynamic_bonus
    
    # Cap at 100 just in case a player is having a historic, record-breaking season
    return round(min(final_index, 100.0), 1)

@app.get("/api/top-performers")
def get_top_performers():
    # 1. Grab databases from memory
    master_data = fetch_master_fpl_data()
    fixtures = fetch_upcoming_fixtures()
    
    all_players = master_data["elements"]
    
    # 2. Fast lookup for Team names and Team strength data
    team_lookup = {team["id"]: team for team in master_data["teams"]}
    
    # 3. Figure out the next Gameweek matches
    upcoming = [f for f in fixtures if f["event"] is not None]
    if not upcoming:
        return {"top_performers": []}
    
    next_gw = upcoming[0]["event"]
    next_gw_matches = [f for f in upcoming if f["event"] == next_gw]
    
    # 4. Run the Proprietary Algorithm on EVERY player in the league
    for player in all_players:
        team_id = player["team"]
        player_team_data = team_lookup.get(team_id, {})
        
        # Determine if their next match is home or away
        is_home = True
        for match in next_gw_matches:
            if match["team_h"] == team_id:
                is_home = True
                break
            elif match["team_a"] == team_id:
                is_home = False
                break
                
        next_match_data = {"is_home": is_home}
        
        # Calculate and attach the custom index
        player["performance_index"] = calculate_native_performer_index(
            player=player, 
            next_match=next_match_data, 
            team_data=player_team_data
        )
        
    # 5. Sort by YOUR algorithm (Highest to Lowest)
    all_players.sort(key=lambda x: x["performance_index"], reverse=True)
    
    # 6. Grab the Top 3 and format
    top_3 = all_players[:3]
    formatted_performers = []
    
    for index, player in enumerate(top_3):
        team_short_name = team_lookup[player['team']]['short_name']
        
        formatted_performers.append({
            "rank": index + 1,
            "name": f"{player['first_name']} {player['second_name']}",
            "team": f"{team_short_name} • £{player['now_cost'] / 10:.1f}m",
            "performance_index": player["performance_index"], # Your proprietary score
            "form": player["form"], 
            "image_url": get_player_image_url(player["photo"].replace(".jpg", ""))
        })
        
    return {"top_performers": formatted_performers}

#----------------------------old endpoints----------------------------
    
@app.get("/players/injured")
@cached(cache=injured_cache)
def injured_players():
    data = get_injured_players()
    return {"injured_players": data}

@app.get("/strikers/forecast")
@cached(cache=striker_cache)
def get_striker_forecasts():
    data = get_strikers_forecast()
    return {"top_strikers": data}