from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.analyzer import get_injured_players, get_strikers_forecast
from app.analyzer import get_top_in_form_players
from app.analyzer import get_injured_players
from .analyzer import calculate_striker_score

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