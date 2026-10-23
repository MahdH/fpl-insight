from pathlib import Path
from threading import Lock

import requests
from cachetools import TTLCache, cached
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.analyzer import get_player_image_url
from app.model import expected_goals, neutral_rating, next_gameweek, project_players, team_ratings, upcoming_fixtures
from app.transfers import suggest_transfers

app = FastAPI(title="Football Performance Forecaster")

# Vercel's FastAPI preset auto-detects this file as the entrypoint, serves
# public/ from its CDN, and promotes this app.mount() to the CDN at build
# time. Guarding on the directory's existence just means this never crashes
# module import on a deploy target where public/ isn't present.
PUBLIC_DIR = Path(__file__).resolve().parent.parent / "public"

if PUBLIC_DIR.is_dir():
    app.mount("/src", StaticFiles(directory=PUBLIC_DIR / "src"), name="src")

    @app.get("/")
    def serve_dashboard():
        return FileResponse(PUBLIC_DIR / "index.html")

    @app.get("/my-team")
    def serve_my_team():
        return FileResponse(PUBLIC_DIR / "my-team.html")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

FPL_API = "https://fantasy.premierleague.com/api"
REQUEST_TIMEOUT = 10  # seconds; keeps a slow FPL API from hanging the function

cache_lock = Lock()  # FastAPI runs these sync endpoints in a thread pool; TTLCache isn't thread-safe
master_db_cache = TTLCache(maxsize=1, ttl=3600)
fixture_cache = TTLCache(maxsize=1, ttl=3600)
manager_cache = TTLCache(maxsize=512, ttl=120)
entry_cache = TTLCache(maxsize=512, ttl=600)

IS_SEASON_ACTIVE = False  # The master switch


@cached(cache=master_db_cache, lock=cache_lock)
def fetch_master_fpl_data():
    """Downloads the entire FPL database once an hour."""
    response = requests.get(f"{FPL_API}/bootstrap-static/", timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


@cached(cache=fixture_cache, lock=cache_lock)
def fetch_fixtures():
    """The whole season's fixtures: played ones size each team's sample, unplayed ones drive projections."""
    response = requests.get(f"{FPL_API}/fixtures/", timeout=REQUEST_TIMEOUT)
    response.raise_for_status()
    return response.json()


def fetch_manager_json(cache, key, url):
    """GET a manager endpoint, caching successes only so a failed lookup is retried on the next click."""
    with cache_lock:
        cached_value = cache.get(key)
    if cached_value is not None:
        return cached_value

    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        data = response.json() if response.status_code == 200 else None
    except (requests.RequestException, ValueError):
        return None

    if data is not None:
        with cache_lock:
            cache[key] = data
    return data


def fetch_manager_picks(manager_id, gameweek):
    """A manager's squad for a gameweek: {"picks": [...], "entry_history": {"bank": ...}}, or None."""
    return fetch_manager_json(
        manager_cache, (manager_id, gameweek), f"{FPL_API}/entry/{manager_id}/event/{gameweek}/picks/"
    )


def fetch_manager_entry(manager_id):
    """A manager's profile (team name, manager name, ranks), or None."""
    return fetch_manager_json(entry_cache, manager_id, f"{FPL_API}/entry/{manager_id}/")


def load_projections():
    master = fetch_master_fpl_data()
    projections, _ = project_players(master, fetch_fixtures())
    return master, projections


def rank_by_xp(players, projections):
    """Players with a positive horizon xP, best first. Injured, suspended and unused players drop out."""
    scored = [p for p in players if projections.get(p["id"], {}).get("xp_horizon", 0) > 0]
    return sorted(scored, key=lambda p: projections[p["id"]]["xp_horizon"], reverse=True)


def current_gameweek(master):
    return next((event["id"] for event in master["events"] if event["is_current"]), 1)


def format_price(player):
    return f"£{player['now_cost'] / 10:.1f}m"


def full_name(player):
    return f"{player['first_name']} {player['second_name']}".strip()


def team_short_names(master):
    return {team["id"]: team["short_name"] for team in master["teams"]}


def short_name(player):
    initial = (player.get("first_name") or "")[:1]
    return f"{initial}. {player['second_name']}" if initial else player["second_name"]


def player_image(player):
    return get_player_image_url(str(player.get("photo", "")).replace(".jpg", ""))


@app.get("/api/system-status")
async def get_system_status():
    return {
        "is_season_active": IS_SEASON_ACTIVE,
        "season_label": "26/27 SEASON"
    }


@app.get("/api/my-team/{manager_id}")
def get_manager_team(manager_id: int):
    master_data = fetch_master_fpl_data()
    all_players = {p["id"]: p for p in master_data["elements"]}
    gameweek = current_gameweek(master_data)

    squad_data = fetch_manager_picks(manager_id, gameweek)
    if squad_data is None:
        return {"error": "Manager ID not found or invalid."}

    entry = fetch_manager_entry(manager_id) or {}
    manager_name = " ".join(filter(None, [entry.get("player_first_name"), entry.get("player_last_name")]))

    starting_xi = []
    bench = []
    for pick in squad_data.get("picks", []):
        player = all_players.get(pick["element"])
        if not player:
            continue

        formatted_player = {
            "name": player["web_name"],
            "position": player["element_type"],  # 1=GK, 2=DEF, 3=MID, 4=FWD
            "price": format_price(player),
            "is_captain": pick["is_captain"],
            "is_vice_captain": pick["is_vice_captain"],
            "multiplier": pick["multiplier"],
            "image_url": player_image(player),
        }
        # A multiplier of 0 means the player is on the bench.
        (starting_xi if pick["multiplier"] > 0 else bench).append(formatted_player)

    return {
        "manager_id": manager_id,
        "team_name": entry.get("name"),
        "manager_name": manager_name or None,
        "gameweek": gameweek,
        "squad": {
            "starting_xi": starting_xi,
            "bench": bench
        }
    }


@app.get("/api/transfer-suggestions/{manager_id}")
def get_transfer_suggestions(manager_id: int):
    master_data, projections = load_projections()

    squad_data = fetch_manager_picks(manager_id, current_gameweek(master_data))
    if squad_data is None:
        return {"error": "Manager ID not found."}

    players = master_data["elements"]
    by_id = {p["id"]: p for p in players}
    picks = [pick for pick in squad_data.get("picks", []) if pick["element"] in by_id]
    bank = (squad_data.get("entry_history") or {}).get("bank") or 0

    swaps = suggest_transfers(
        squad=[by_id[pick["element"]] for pick in picks],
        players=players,
        projections=projections,
        bank=bank,
        bench_ids={pick["element"] for pick in picks if pick["multiplier"] == 0},
    )

    team_names = team_short_names(master_data)

    def side(player):
        return {
            "id": player["id"],
            "name": player["web_name"],
            "team": team_names.get(player["team"], ""),
            "position": player["element_type"],
            "price": format_price(player),
            "xp_horizon": round(projections[player["id"]]["xp_horizon"], 1),
            "xp_next": round(projections[player["id"]]["xp_next"], 1),
            "image_url": player_image(player),
        }

    return {
        "bank": f"£{bank / 10:.1f}m",
        "suggestions": [
            {
                "position": swap.out["element_type"],
                "out": side(swap.out),
                "in": side(swap.into),
                "xp_gain": round(swap.xp_gain, 1),
                "xp_gain_next": round(swap.xp_gain_next, 1),
                "cost_change": round(swap.cost_change / 10, 1),
                "reason": swap.reason,
            }
            for swap in swaps
        ],
    }


@app.get("/api/top-picks")
def get_top_picks():
    master_data, projections = load_projections()
    forwards = [p for p in master_data["elements"] if p["element_type"] == 4]

    return {
        "top_picks": [
            {
                "name": full_name(player) if rank == 0 else short_name(player),
                "position": "FWD",
                "price": format_price(player),
                "projected_points": player["ep_next"],
                "custom_index": round(projections[player["id"]]["xp_horizon"], 1),
                "xp_next": round(projections[player["id"]]["xp_next"], 1),
                "minutes_security": projections[player["id"]]["minutes_security"],
                "goals_minus_xg": projections[player["id"]]["goals_minus_xg"],
                "ownership_percent": player["selected_by_percent"],
                "image_url": player_image(player),
            }
            for rank, player in enumerate(rank_by_xp(forwards, projections)[:3])
        ]
    }


@app.get("/api/risk-alerts")
def get_transfer_out_alert():
    all_players = fetch_master_fpl_data()["elements"]

    # Flagged players (injured, suspended or doubtful), most-owned first: the most painful
    # absence for the community.
    flagged_players = [
        p for p in all_players
        if p["status"] != "a" and p["chance_of_playing_next_round"] is not None and p["chance_of_playing_next_round"] < 100
    ]
    if not flagged_players:
        return {"alert": None}

    critical_player = max(flagged_players, key=lambda p: float(p["selected_by_percent"]))
    return {
        "alert": {
            "name": critical_player["second_name"],
            "full_name": full_name(critical_player),
            "reason": critical_player["news"],
            "chance": f"{critical_player['chance_of_playing_next_round']}%",
            "ownership": f"{critical_player['selected_by_percent']}%",
            "image_url": player_image(critical_player),
        }
    }


@app.get("/api/target-fixture")
def get_target_fixture():
    """The next-gameweek fixture where one side is expected to score the most, by xG."""
    master_data = fetch_master_fpl_data()
    fixtures = fetch_fixtures()
    ratings, league = team_ratings(master_data["elements"], fixtures)
    team_names = {team["id"]: team["short_name"] for team in master_data["teams"]}

    upcoming = upcoming_fixtures(fixtures)
    gameweek = next_gameweek(master_data, upcoming)
    matches = [f for f in upcoming if f["event"] == gameweek]
    if not matches:
        return {"target_fixture": None}

    def rating(team_id):
        return ratings.get(team_id, neutral_rating(league))

    options = []
    for match in matches:
        home, away = rating(match["team_h"]), rating(match["team_a"])
        options.append((expected_goals(home, away, league, True), match, True))
        options.append((expected_goals(away, home, league, False), match, False))
    team_xg, best_match, home_side = max(options, key=lambda option: option[0])

    target_team = best_match["team_h"] if home_side else best_match["team_a"]
    difficulty = best_match["team_h_difficulty"] if home_side else best_match["team_a_difficulty"]
    return {
        "target_fixture": {
            "match": f"{team_names[best_match['team_h']]} vs {team_names[best_match['team_a']]}",
            "team": team_names[target_team],
            "expected_goals": round(team_xg, 2),
            "difficulty": difficulty or 3,
            "max_difficulty": 5
        }
    }


@app.get("/api/top-performers")
def get_top_performers():
    master_data, projections = load_projections()
    team_names = {team["id"]: team["short_name"] for team in master_data["teams"]}

    return {
        "top_performers": [
            {
                "rank": rank + 1,
                "name": full_name(player),
                "team": f"{team_names.get(player['team'], '')} • {format_price(player)}",
                "performance_index": round(projections[player["id"]]["xp_horizon"], 1),
                "xp_next": round(projections[player["id"]]["xp_next"], 1),
                "form": player["form"],
                "image_url": player_image(player),
            }
            for rank, player in enumerate(rank_by_xp(master_data["elements"], projections)[:3])
        ]
    }
