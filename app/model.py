"""Expected-points (xP) model for FPL players.

Follows the approach expert managers use: minutes security first, then underlying
chance quality (xG / xA) rather than goals, adjusted for opponent strength measured by
expected goals, and projected over the next few gameweeks. Every input comes from the
official FPL API, and these functions are pure so they can be unit tested.
"""

import math
from collections import defaultdict
from typing import NamedTuple

POSITIONS = {1: "GKP", 2: "DEF", 3: "MID", 4: "FWD"}

# Used when the live API omits a rule; the live game_config.scoring always takes precedence.
DEFAULT_SCORING = {
    "long_play": 2,
    "short_play": 1,
    "goals_scored": {"GKP": 10, "DEF": 6, "MID": 5, "FWD": 4},
    "assists": 3,
    "clean_sheets": {"GKP": 4, "DEF": 4, "MID": 1, "FWD": 0},
    "goals_conceded": {"GKP": -1, "DEF": -1, "MID": 0, "FWD": 0},
    "saves": 1,
    "defensive_contribution": {"GKP": 0, "DEF": 2, "MID": 2, "FWD": 2},
}

# Per-match actions needed for defensive-contribution points. FPL publishes these in its
# rules but not in the API.
DEFCON_THRESHOLD = {"GKP": 0, "DEF": 10, "MID": 12, "FWD": 12}

HORIZON_GAMEWEEKS = 5
HORIZON_DISCOUNT = 0.9
HOME_EDGE = 1.1
PRIOR_MINUTES = 270
PRIOR_TEAM_GAMES = 4
FIXTURE_MULTIPLIER_RANGE = (0.6, 1.5)
FALLBACK_TEAM_GOALS = 1.35

RATE_FIELDS = {
    "xg": "expected_goals",
    "xa": "expected_assists",
    "saves": "saves",
    "defcon": "defensive_contribution",
    "bonus": "bonus",
}


class Minutes(NamedTuple):
    p_play: float  # probability he starts the next match
    p_60: float  # probability he plays 60+ minutes
    per_start: float  # share of 90 minutes he plays when he starts
    share: float  # expected share of 90 minutes, all things considered


def to_float(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def clamp(value, low, high):
    return max(low, min(high, value))


def availability(player):
    chance = player.get("chance_of_playing_next_round")
    if chance is not None:
        return clamp(to_float(chance) / 100, 0.0, 1.0)
    return 1.0 if player.get("status") == "a" else 0.0


def minutes_profile(player, team_games):
    starts = player.get("starts") or 0
    minutes = player.get("minutes") or 0
    if team_games <= 0 or starts <= 0:
        return Minutes(0.0, 0.0, 0.0, 0.0)

    start_rate = min(starts / team_games, 1.0)
    per_start = min(minutes / starts, 90.0) / 90
    p_play = availability(player) * start_rate
    # Players averaging 75+ minutes per start almost always reach 60; under 30 almost never do.
    p_60 = p_play * clamp((per_start * 90 - 30) / 45, 0.0, 1.0)
    return Minutes(p_play, p_60, per_start, p_play * per_start)


def per90(total, minutes, prior_per90, prior_minutes=PRIOR_MINUTES):
    """Bayesian-smoothed per-90 rate: small samples are pulled toward the position average."""
    return (total + prior_per90 * prior_minutes / 90) / ((minutes + prior_minutes) / 90)


def poisson_at_least(mu, k):
    if k <= 0:
        return 1.0
    if mu <= 0:
        return 0.0
    term = math.exp(-mu)
    below = term
    for i in range(1, k):
        term *= mu / i
        below += term
    return clamp(1.0 - below, 0.0, 1.0)


def scoring_rules(bootstrap):
    live = (bootstrap.get("game_config") or {}).get("scoring") or {}
    rules = {}
    for key, default in DEFAULT_SCORING.items():
        value = live.get(key)
        if isinstance(default, dict):
            merged = dict(default)
            if isinstance(value, dict):
                merged.update({pos: value[pos] for pos in default if isinstance(value.get(pos), (int, float))})
            rules[key] = merged
        else:
            rules[key] = value if isinstance(value, (int, float)) else default
    return rules


def position_priors(players):
    totals = defaultdict(lambda: defaultdict(float))
    minutes = defaultdict(float)
    for player in players:
        pos = POSITIONS.get(player.get("element_type"))
        played = player.get("minutes") or 0
        if pos is None or played <= 0:
            continue
        minutes[pos] += played
        for key, field in RATE_FIELDS.items():
            totals[pos][key] += to_float(player.get(field))

    return {
        pos: {key: (totals[pos][key] / minutes[pos] * 90 if minutes[pos] else 0.0) for key in RATE_FIELDS}
        for pos in POSITIONS.values()
    }


def player_rates(player, prior):
    minutes = player.get("minutes") or 0
    return {key: per90(to_float(player.get(field)), minutes, prior[key]) for key, field in RATE_FIELDS.items()}


def is_played(fixture):
    return bool(fixture.get("finished") or fixture.get("finished_provisional"))


def team_ratings(players, fixtures):
    """Per-game attack (xG for) and defence (xG against) for every team, plus the league average.

    A team's xG against is the sum of its goalkeepers' expected_goals_conceded, since one
    goalkeeper is on the pitch for every minute. Ratings are shrunk toward the league
    average so a handful of games can't produce extreme values.
    """
    games = defaultdict(int)
    for fixture in fixtures:
        if is_played(fixture):
            games[fixture["team_h"]] += 1
            games[fixture["team_a"]] += 1

    xg_for = defaultdict(float)
    xg_against = defaultdict(float)
    for player in players:
        xg_for[player["team"]] += to_float(player.get("expected_goals"))
        if player.get("element_type") == 1:
            xg_against[player["team"]] += to_float(player.get("expected_goals_conceded"))

    total_games = sum(games.values())
    league = sum(xg_for.values()) / total_games if total_games else 0.0
    if league <= 0:
        league = FALLBACK_TEAM_GOALS

    ratings = {}
    for team_id in set(games) | set(xg_for):
        played = games.get(team_id, 0)
        ratings[team_id] = {
            "games": played,
            "attack": (xg_for[team_id] + league * PRIOR_TEAM_GAMES) / (played + PRIOR_TEAM_GAMES),
            "defence": (xg_against[team_id] + league * PRIOR_TEAM_GAMES) / (played + PRIOR_TEAM_GAMES),
        }
    return ratings, league


def neutral_rating(league):
    return {"games": 0, "attack": league, "defence": league}


def expected_goals(attacking, defending, league, at_home):
    venue = HOME_EDGE if at_home else 1 / HOME_EDGE
    return attacking["attack"] * defending["defence"] / league * venue


def fixture_points(pos, rates, mins, team, opponent, at_home, league, scoring):
    """Expected FPL points for one player in one fixture."""
    if mins.p_play <= 0:
        return 0.0

    venue = HOME_EDGE if at_home else 1 / HOME_EDGE
    attack_multiplier = clamp(opponent["defence"] / league * venue, *FIXTURE_MULTIPLIER_RANGE)
    goals = rates["xg"] * mins.share * attack_multiplier
    assists = rates["xa"] * mins.share * attack_multiplier
    conceded = expected_goals(opponent, team, league, not at_home)

    points = scoring["long_play"] * mins.p_60 + scoring["short_play"] * (mins.p_play - mins.p_60)
    points += goals * scoring["goals_scored"][pos] + assists * scoring["assists"]
    points += mins.p_60 * math.exp(-conceded) * scoring["clean_sheets"][pos]
    points += mins.share * conceded / 2 * scoring["goals_conceded"][pos]
    points += mins.share * rates["bonus"]

    if pos == "GKP":
        points += mins.share * rates["saves"] / 3 * scoring["saves"]

    threshold = DEFCON_THRESHOLD[pos]
    if threshold:
        hit = poisson_at_least(rates["defcon"] * mins.per_start, threshold)
        points += mins.p_play * hit * scoring["defensive_contribution"][pos]

    return points


def upcoming_fixtures(fixtures):
    unplayed = [f for f in fixtures if f.get("event") and not is_played(f)]
    return sorted(unplayed, key=lambda f: (f["event"], f.get("kickoff_time") or ""))


def next_gameweek(bootstrap, upcoming):
    """The next transfer deadline's gameweek, falling back to the earliest unplayed one."""
    for event in bootstrap.get("events", []):
        if event.get("is_next"):
            return event["id"]
    return upcoming[0]["event"] if upcoming else None


def project_players(bootstrap, fixtures, horizon=HORIZON_GAMEWEEKS):
    """Project every player's xP for the next gameweek and a discounted multi-gameweek horizon.

    Returns ({player_id: projection}, first_gameweek). Inputs are never mutated.
    """
    players = bootstrap.get("elements", [])
    scoring = scoring_rules(bootstrap)
    ratings, league = team_ratings(players, fixtures)
    priors = position_priors(players)

    upcoming = upcoming_fixtures(fixtures)
    start = next_gameweek(bootstrap, upcoming)
    window = sorted({f["event"] for f in upcoming if start is not None and f["event"] >= start})[:horizon]
    weights = {gw: HORIZON_DISCOUNT**i for i, gw in enumerate(window)}

    # A team can appear twice in one gameweek (double) or not at all (blank).
    schedule = defaultdict(list)
    for fixture in upcoming:
        if fixture["event"] in weights:
            schedule[fixture["team_h"]].append((fixture["event"], fixture["team_a"], True))
            schedule[fixture["team_a"]].append((fixture["event"], fixture["team_h"], False))

    projections = {}
    for player in players:
        pos = POSITIONS.get(player.get("element_type"))
        if pos is None:
            continue
        team = ratings.get(player["team"], neutral_rating(league))
        mins = minutes_profile(player, team["games"])
        rates = player_rates(player, priors[pos])

        xp_next = 0.0
        xp_horizon = 0.0
        for gw, opponent_id, at_home in schedule.get(player["team"], []):
            opponent = ratings.get(opponent_id, neutral_rating(league))
            points = fixture_points(pos, rates, mins, team, opponent, at_home, league, scoring)
            xp_horizon += points * weights[gw]
            if gw == window[0]:
                xp_next += points

        price = (player.get("now_cost") or 0) / 10
        projections[player["id"]] = {
            "xp_next": round(xp_next, 2),
            "xp_horizon": round(xp_horizon, 2),
            "minutes_security": round(mins.p_play, 2),
            "value": round(xp_horizon / price, 2) if price else 0.0,
            "goals_minus_xg": round((player.get("goals_scored") or 0) - to_float(player.get("expected_goals")), 2),
        }

    return projections, (window[0] if window else None)
