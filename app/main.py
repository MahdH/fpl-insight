from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from cachetools import cached, TTLCache
from app.analyzer import get_strikers_forecast, get_top_in_form_players, get_injured_players


app = FastAPI(title="Football Performance Forecaster")

# Tells API to accept requests from local HTML file
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], # Allows all websites to fetch your data
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Use a TTL Cache to refresh the data periodically (e.g., max 100 items, expires after 300 seconds)
route_cache = TTLCache(maxsize=100, ttl=300)

@app.get("/")
@cached(cache=route_cache)
def root():
    return {"message": "Football Analysis API is running and auto deploying updates!"}

@app.get("/players/top-form")
@cached(cache=route_cache)
def top_performers():
    data = get_top_in_form_players()
    return {"top_5_players_inform": data}

@app.get("/players/injured")
@cached(cache=route_cache)
def injured_players():
    data = get_injured_players()
    return {"injured_players": data}

@app.get("/strikers/forecast")
@cached(cache=route_cache)
def get_striker_forecasts():
    data = get_strikers_forecast()
    return {"top_strikers": data}