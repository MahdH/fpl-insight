from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.analyzer import calculate_striker_score, get_injured_players, get_strikers_forecast, get_top_in_form_players, get_injured_players
import requests


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
    data = get_strikers_forecast()
    return {"top_strikers": data}