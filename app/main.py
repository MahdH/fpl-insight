from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.analyzer import get_injured_players, get_strikers_forecast
from app.analyzer import get_top_in_form_players
from app.analyzer import get_injured_players


app = FastAPI(title="Football Performance Forecaster")

# Tells API to accept requests from local HTML file
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all websites to fetch your data
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
async def root():
    return {"message": "Football Analysis API is running and auto deploying updates!"}

# Updated endpoint name
@app.get("/strikers/forecast")
async def forecast_strikers():
    data = get_strikers_forecast()
    return {"top_10_strikers": data}

@app.get("/players/top-form")
async def top_performers():
    data = get_top_in_form_players()
    return {"top_5_players_inform": data}

@app.get("/players/injured")
async def injured_players():

    data = get_injured_players()
    return {"injured_players": data}

@app.get("/strikers/forecast")
async def get_striker_forecasts():
    """Fetches live FPL data, runs the forecast algorithm, and returns the top 10 strikers."""
    
    # 1. Fetch live data from the official FPL API
    url = "https://fantasy.premierleague.com/api/bootstrap-static/"
    response = requests.get(url)
    data = response.json()

    # element_type == 4 is the FPL code for Forwards (Strikers)
    strikers = [player for player in data['elements'] if player['element_type'] == 4]
    
    forecast_results = []
    
    # 2. Loop through every striker and run our Pytest-approved algorithm
    for player in strikers:
        # FPL returns form as a string, so we convert it to a float
        recent_form = float(player.get('form', '0.0'))
        total_points = int(player.get('total_points', 0))
        
        # We will use baseline dummy data for the fixture metrics for now to keep the API blazing fast
        avg_fdr = 3.0 
        next_match_is_home = True 
        
        # 3. The Math Engine
        score = calculate_striker_score(
            recent_form=recent_form,
            total_points=total_points,
            next_match_is_home=next_match_is_home,
            avg_fdr=avg_fdr
        )
        
        # 4. Save the result
        forecast_results.append({
            "name": player['web_name'],
            "recent_form": recent_form,
            "total_points": total_points,
            "forecast_score": score
        })
        
    # 5. Sort the list so the highest forecast score is at the top
    forecast_results.sort(key=lambda x: x['forecast_score'], reverse=True)
    
    # Return only the top 10 recommended strikers
    return {"top_strikers": forecast_results[:10]}