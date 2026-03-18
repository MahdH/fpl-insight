from fastapi import FastAPI
from app.analyzer import get_injured_players, get_strikers_forecast
from app.analyzer import get_top_in_form_players
from app.analyzer import get_injured_players

app = FastAPI(title="Football Performance Forecaster")

@app.get("/")
async def root():
    return {"message": "Football Analysis API is online!"}

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