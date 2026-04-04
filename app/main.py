from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from cachetools import cached, TTLCache
from app.analyzer import get_strikers_forecast, get_top_in_form_players, get_injured_players, get_player_image_url,


app = FastAPI(title="Football Performance Forecaster")

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


@app.get("/")
def root():
    return {"message": "Football Analysis API is running and auto deploying updates!"}

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
    # 1. Grab the instant, cached FPL data
    data = fetch_master_fpl_data()
    all_players = data["elements"] # 'elements' is FPL's name for players
    
    # 2. Filter for Forwards only
    # In the FPL API, element_type 4 equals a Forward (FWD)
    forwards = [p for p in all_players if p["element_type"] == 4]
    
    # 3. Sort by FPL's internal projection algorithm (Expected Points Next GW)
    # FPL returns this as a string (e.g., "8.5"), so we must convert to float to sort mathematically
    forwards.sort(key=lambda x: float(x["ep_next"]), reverse=True)
    
    # 4. Grab the Top 3 Forwards
    top_3 = forwards[:3]
    
    # 5. Transform the raw FPL data into exactly what our HTML needs
    formatted_picks = []
    for player in top_3:
        formatted_picks.append({
            "name": f"{player['first_name'][0]}. {player['second_name']}" if player != top_3[0] else f"{player['first_name']} {player['second_name']}",
            "position": "FWD",
            "price": f"£{player['now_cost'] / 10:.1f}m", # FPL stores £15.2m as 152
            "projected_points": player["ep_next"],
            "ict_index": player["ict_index"],
            "ownership_percent": player["selected_by_percent"],
            "image_url": get_player_image_url(player["photo"].replace(".jpg", ""))
        })
        
    return {"top_picks": formatted_picks}

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

#----------------------------old endpoints----------------------------

@app.get("/players/top-form")
@cached(cache=topform_cache)
def top_performers():
    data = get_top_in_form_players()
    return {"top_5_players_inform": data}

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