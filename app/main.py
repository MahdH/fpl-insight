from pathlib import Path
from threading import Lock
from typing import Literal, Optional

import requests
from cachetools import TTLCache, cached
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.analyzer import get_player_image_url
from app.manager import CHIP_ORDER, chip_availability, free_transfers, max_free_transfers
from app.model import expected_goals, neutral_rating, next_gameweek, project_players, team_ratings, upcoming_fixtures
from app.planner import build_plan
from app.squad import OptimisationError, squad_rules

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
history_cache = TTLCache(maxsize=512, ttl=120)

IS_SEASON_ACTIVE = False  # The master switch

Chip = Literal["none", "wildcard", "freehit", "bboost", "3xc"]
CHIP_LABELS = {"wildcard": "Wildcard", "freehit": "Free Hit", "bboost": "Bench Boost", "3xc": "Triple Captain"}
MAX_TRANSFERS = 5


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


def fetch_manager_history(manager_id):
    """A manager's season so far: transfers made each gameweek and the chips they've played, or None."""
    return fetch_manager_json(history_cache, manager_id, f"{FPL_API}/entry/{manager_id}/history/")


def load_projections():
    master = fetch_master_fpl_data()
    projections, first_gameweek = project_players(master, fetch_fixtures())
    return master, projections, first_gameweek


def manager_status(master, history, planning_gameweek):
    """Free transfers and chip availability for the gameweek being planned.

    Both come from the manager's history. If it can't be read they are reported as unknown rather
    than guessed: free transfers become None, and every chip is offered.
    """
    current = next((event["id"] for event in master["events"] if event["is_current"]), None)
    free = free_transfers(history, current, max_free_transfers(master)) if history else None
    if history and planning_gameweek:
        chips = chip_availability(master.get("chips"), history, planning_gameweek)
        chips["known"] = True
    else:
        chips = {"available": list(CHIP_ORDER), "used": [], "known": False}
    return {"free_transfers": free, "free_transfers_known": free is not None, "chips": chips}


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


def squad_card(player, is_captain=False, is_vice_captain=False, multiplier=1, is_new=False):
    """A squad member as the pitch and bench display him."""
    return {
        "name": player["web_name"],
        "position": player["element_type"],  # 1=GK, 2=DEF, 3=MID, 4=FWD
        "price": format_price(player),
        "is_captain": is_captain,
        "is_vice_captain": is_vice_captain,
        "multiplier": multiplier,
        "is_new": is_new,
        "image_url": player_image(player),
    }


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

        card = squad_card(player, pick["is_captain"], pick["is_vice_captain"], pick["multiplier"])
        # A multiplier of 0 means the player is on the bench.
        (starting_xi if pick["multiplier"] > 0 else bench).append(card)

    planning_gameweek = next((event["id"] for event in master_data["events"] if event["is_next"]), None)
    status = manager_status(master_data, fetch_manager_history(manager_id), planning_gameweek)

    return {
        "manager_id": manager_id,
        "team_name": entry.get("name"),
        "manager_name": manager_name or None,
        "gameweek": gameweek,
        "bank": f"£{((squad_data.get('entry_history') or {}).get('bank') or 0) / 10:.1f}m",
        **status,
        "squad": {
            "starting_xi": starting_xi,
            "bench": bench
        }
    }


@app.get("/api/transfer-suggestions/{manager_id}")
def get_transfer_suggestions(
    manager_id: int,
    chip: Chip = "none",
    transfers: Optional[int] = Query(None, ge=1, le=MAX_TRANSFERS),
):
    """The best transfers for a manager's squad.

    `transfers` is the most transfers to make, defaulting to the manager's free transfers. Wildcard and
    Free Hit rebuild the whole squad and ignore it.
    """
    master_data, projections, first_gameweek = load_projections()

    squad_data = fetch_manager_picks(manager_id, current_gameweek(master_data))
    if squad_data is None:
        return {"error": "Manager ID not found."}

    by_id = {p["id"]: p for p in master_data["elements"]}
    squad = [by_id[pick["element"]] for pick in squad_data.get("picks", []) if pick["element"] in by_id]
    if len(squad) != squad_rules(master_data).size:
        return {"error": "Couldn't read a full squad for this manager."}

    planning_gameweek = next((event["id"] for event in master_data["events"] if event["is_next"]), first_gameweek)
    status = manager_status(master_data, fetch_manager_history(manager_id), planning_gameweek)
    if chip != "none" and chip not in status["chips"]["available"]:
        return {"error": f"Your {CHIP_LABELS[chip]} has already been played in this half of the season."}

    free = status["free_transfers"]
    requested = transfers or min(max(free or 1, 1), MAX_TRANSFERS)
    entry_history = squad_data.get("entry_history") or {}
    bank = entry_history.get("bank") or 0

    try:
        plan = build_plan(
            master_data,
            projections,
            squad,
            bank=bank,
            squad_value=entry_history.get("value"),
            chip=chip,
            transfers=requested,
            free_transfers=free if free is not None else 1,
        )
    except OptimisationError as error:
        return {"error": str(error)}

    return {
        "chip": chip,
        "gameweek": planning_gameweek,
        "bank": f"£{bank / 10:.1f}m",
        "free_transfers": free,
        "free_transfers_known": free is not None,
        "transfers_requested": requested,
        **format_plan(plan, master_data, projections),
    }


def format_plan(plan, master, projections):
    """The API shape for a plan: swaps, the proposed squad, a summary and any chip detail."""
    team_names = team_short_names(master)

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

    def card(player):
        return squad_card(
            player,
            is_captain=player["id"] == plan.captain["id"],
            is_vice_captain=player["id"] == plan.vice["id"],
            is_new=player["id"] in plan.new_ids,
        )

    gain = max(0.0, plan.new_xp - plan.current_xp)
    rebuild_horizon = plan.horizon == "xp_next"
    highlight = None
    if plan.highlight and plan.highlight["kind"] == "bench":
        highlight = {"kind": "bench", "xp_next": plan.highlight["xp_next"]}
    elif plan.highlight:
        captain = plan.captain
        highlight = {
            "kind": "captain",
            "name": captain["web_name"],
            "team": team_names.get(captain["team"], ""),
            "price": format_price(captain),
            "xp_next": plan.highlight["xp_next"],
            "image_url": player_image(captain),
        }

    return {
        "suggestions": [
            {
                "position": swap.out["element_type"],
                "out": side(swap.out),
                "in": side(swap.into),
                "xp_gain": round(swap.xp_gain, 1),
                "xp_gain_next": round(swap.xp_gain_next, 1),
                "cost_change": swap.cost_change,
                "reason": swap.reason,
            }
            for swap in plan.swaps
        ],
        "summary": {
            "transfers_used": len(plan.swaps),
            "xp_gain": round(gain, 1),
            "hit_cost": plan.hit_cost,
            "net_gain": round(gain - plan.hit_cost, 1),
            "current_xp": round(plan.current_xp, 1),
            "new_xp": round(plan.new_xp, 1),
            "horizon": "next gameweek" if rebuild_horizon else "next 5 gameweeks",
            "bank_after": f"£{max(plan.bank_after, 0) / 10:.1f}m",
        },
        "squad": {
            "starting_xi": [card(p) for p in sorted(plan.starters, key=lambda p: p["element_type"])],
            "bench": [card(p) for p in plan.bench],
        },
        "highlight": highlight,
        "notes": plan.notes,
    }


@app.get("/api/top-picks")
def get_top_picks():
    master_data, projections, _ = load_projections()
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
    master_data, projections, _ = load_projections()
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
