import copy
from types import SimpleNamespace
from typing import get_args

import pytest
from fastapi.testclient import TestClient

from app import main
from app.model import project_players
from app.planner import CHIPS
from app.squad import OptimisationError
from tests.conftest import weakest_squad


@pytest.fixture
def client(world, monkeypatch):
    bootstrap, fixtures = world
    monkeypatch.setattr(main, "fetch_master_fpl_data", lambda: bootstrap)
    monkeypatch.setattr(main, "fetch_fixtures", lambda: fixtures)
    squad = {
        "entry_history": {"bank": 5},
        "picks": [
            {"element": pid, "is_captain": pid == 10, "is_vice_captain": pid == 30, "multiplier": 0 if pid == 13 else 1}
            for pid in (1, 10, 30, 13)
        ],
    }
    entry = {"name": "Test FC", "player_first_name": "Jane", "player_last_name": "Doe"}
    monkeypatch.setattr(main, "fetch_manager_picks", lambda manager_id, gw: squad if manager_id == 43024 else None)
    monkeypatch.setattr(main, "fetch_manager_entry", lambda manager_id: entry if manager_id == 43024 else None)
    monkeypatch.setattr(main, "fetch_manager_history", lambda manager_id: None)
    return TestClient(main.app)


@pytest.fixture
def league_api(league, monkeypatch):
    """A manager with a full, poor squad in a full league. Tests can edit `state` before calling."""
    bootstrap, fixtures = league
    projections, _ = project_players(bootstrap, fixtures)
    players = weakest_squad(bootstrap, projections)
    state = SimpleNamespace(
        players=players,
        squad={
            "entry_history": {"bank": 10, "value": sum(p["now_cost"] for p in players)},
            "picks": [
                {"element": p["id"], "is_captain": i == 0, "is_vice_captain": i == 1, "multiplier": 1 if i < 11 else 0}
                for i, p in enumerate(players)
            ],
        },
        # One free transfer banked in gameweek 2, then one transfer made every week: 2 free now.
        history={
            "current": [{"event": gw, "event_transfers": 0 if gw < 3 else 1, "event_transfers_cost": 0} for gw in range(1, 8)],
            "chips": [{"name": "3xc", "event": 3}],
        },
    )
    entry = {"name": "League FC", "player_first_name": "Ann", "player_last_name": "Lee"}
    monkeypatch.setattr(main, "fetch_master_fpl_data", lambda: bootstrap)
    monkeypatch.setattr(main, "fetch_fixtures", lambda: fixtures)
    monkeypatch.setattr(main, "fetch_manager_picks", lambda manager_id, gw: state.squad if manager_id == 7 else None)
    monkeypatch.setattr(main, "fetch_manager_entry", lambda manager_id: entry if manager_id == 7 else None)
    monkeypatch.setattr(main, "fetch_manager_history", lambda manager_id: state.history)
    state.client = TestClient(main.app)
    return state


def test_top_picks_are_ranked_forwards_without_injuries(client):
    picks = client.get("/api/top-picks").json()["top_picks"]
    assert len(picks) == 3
    assert [p["custom_index"] for p in picks] == sorted((p["custom_index"] for p in picks), reverse=True)
    assert picks[0]["name"] == "First10 Player10"  # elite xG forward leads, full name
    assert picks[1]["name"].startswith(("F", "M")) and "Player12" not in {p["name"] for p in picks}
    for key in ("name", "position", "price", "projected_points", "custom_index", "xp_next", "ownership_percent", "image_url"):
        assert key in picks[0]


def test_single_name_player_does_not_crash(client):
    names = [p["name"] for p in client.get("/api/top-picks").json()["top_picks"]]
    assert "Mononym" in names


def test_top_performers_shape_and_order(client):
    performers = client.get("/api/top-performers").json()["top_performers"]
    assert [p["rank"] for p in performers] == [1, 2, 3]
    scores = [p["performance_index"] for p in performers]
    assert scores == sorted(scores, reverse=True)
    assert performers[0]["team"].startswith("T")


def test_target_fixture(client):
    target = client.get("/api/target-fixture").json()["target_fixture"]
    assert target["match"] in {"T1 vs T2", "T3 vs T2"}
    assert 1 <= target["difficulty"] <= target["max_difficulty"] == 5
    assert target["expected_goals"] > 0


def test_unknown_manager_returns_error(client):
    assert "error" in client.get("/api/transfer-suggestions/1").json()
    assert "error" in client.get("/api/my-team/1").json()


def test_my_team_splits_starters_and_bench(client):
    data = client.get("/api/my-team/43024").json()
    assert data["gameweek"] == 7
    assert len(data["squad"]["starting_xi"]) == 3
    assert [p["name"] for p in data["squad"]["bench"]] == ["Player13"]


def test_my_team_returns_team_and_manager_name(client):
    data = client.get("/api/my-team/43024").json()
    assert data["team_name"] == "Test FC"
    assert data["manager_name"] == "Jane Doe"


def test_my_team_still_loads_when_the_profile_lookup_fails(world, monkeypatch):
    bootstrap, fixtures = world
    monkeypatch.setattr(main, "fetch_master_fpl_data", lambda: bootstrap)
    monkeypatch.setattr(main, "fetch_manager_picks", lambda manager_id, gw: {"picks": [], "entry_history": {}})
    monkeypatch.setattr(main, "fetch_manager_entry", lambda manager_id: None)
    data = TestClient(main.app).get("/api/my-team/43024").json()
    assert data["team_name"] is None and data["manager_name"] is None
    assert data["squad"] == {"starting_xi": [], "bench": []}


# ---------- Manager lookups against the FPL API ----------

class FakeResponse:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {}

    def json(self):
        return self._payload


@pytest.fixture
def fpl_api(monkeypatch):
    for cache in (main.manager_cache, main.entry_cache, main.history_cache):
        cache.clear()
    calls = []
    responses = []

    def fake_get(url, timeout):
        calls.append(url)
        outcome = responses.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(main.requests, "get", fake_get)
    yield calls, responses
    for cache in (main.manager_cache, main.entry_cache, main.history_cache):
        cache.clear()


def test_successful_manager_lookups_are_cached(fpl_api):
    calls, responses = fpl_api
    responses.append(FakeResponse(200, {"name": "Test FC"}))
    assert main.fetch_manager_entry(7)["name"] == "Test FC"
    assert main.fetch_manager_entry(7)["name"] == "Test FC"
    assert len(calls) == 1


def test_failed_manager_lookups_are_retried_not_cached(fpl_api):
    calls, responses = fpl_api
    responses.extend([FakeResponse(404), main.requests.ConnectionError("down"), FakeResponse(200, {"name": "Back"})])
    assert main.fetch_manager_entry(7) is None  # unknown team
    assert main.fetch_manager_entry(7) is None  # network failure
    assert main.fetch_manager_entry(7)["name"] == "Back"  # next click succeeds
    assert len(calls) == 3


def test_history_lookups_are_cached_and_retried_like_the_others(fpl_api):
    calls, responses = fpl_api
    responses.extend([FakeResponse(500), FakeResponse(200, {"current": [], "chips": []})])
    assert main.fetch_manager_history(7) is None  # server error: not cached
    assert main.fetch_manager_history(7) == {"current": [], "chips": []}
    assert main.fetch_manager_history(7) == {"current": [], "chips": []}  # now cached
    assert len(calls) == 2 and calls[0].endswith("/entry/7/history/")


def test_malformed_manager_response_is_a_clean_miss(fpl_api):
    _, responses = fpl_api

    class Broken(FakeResponse):
        def json(self):
            raise ValueError("not json")

    responses.append(Broken(200))
    assert main.fetch_manager_picks(7, 3) is None


def test_risk_alert_picks_most_owned_flagged_player(client):
    alert = client.get("/api/risk-alerts").json()["alert"]
    assert alert["name"] == "Player12"
    assert alert["chance"] == "0%"


def test_endpoints_do_not_mutate_cached_data(client, world):
    bootstrap, fixtures = world
    before = copy.deepcopy((bootstrap, fixtures))
    for path in ("/api/top-picks", "/api/top-performers", "/api/target-fixture", "/api/my-team/43024"):
        assert client.get(path).status_code == 200
    assert (bootstrap, fixtures) == before


# ---------- Free transfers, chips and transfer plans ----------

def plan(league_api, query=""):
    return league_api.client.get(f"/api/transfer-suggestions/7{query}").json()


def test_a_partial_squad_cannot_be_planned(client):
    assert client.get("/api/transfer-suggestions/43024").json() == {"error": "Couldn't read a full squad for this manager."}


def test_my_team_reports_free_transfers_chips_and_bank(league_api):
    data = league_api.client.get("/api/my-team/7").json()
    assert data["free_transfers"] == 2 and data["free_transfers_known"] is True
    assert data["chips"] == {"available": ["wildcard", "freehit", "bboost"], "used": ["3xc"], "known": True}
    assert data["bank"] == "£1.0m"
    assert data["team_name"] == "League FC"


def test_my_team_says_so_when_the_history_is_unavailable(league_api):
    league_api.history = None
    data = league_api.client.get("/api/my-team/7").json()
    assert data["free_transfers"] is None and data["free_transfers_known"] is False
    assert data["chips"] == {"available": ["wildcard", "freehit", "bboost", "3xc"], "used": [], "known": False}


def test_the_transfer_count_defaults_to_the_free_transfers(league_api):
    data = plan(league_api)
    assert data["chip"] == "none" and data["transfers_requested"] == 2 and data["free_transfers"] == 2
    assert 1 <= data["summary"]["transfers_used"] <= 2
    assert data["summary"]["hit_cost"] == 0


def test_the_response_has_everything_the_page_needs(league_api):
    data = plan(league_api, "?transfers=2")
    assert set(data) >= {"chip", "gameweek", "bank", "free_transfers", "transfers_requested", "suggestions", "summary", "squad", "highlight", "notes"}
    assert data["gameweek"] == 8 and data["bank"] == "£1.0m"
    assert set(data["summary"]) == {"transfers_used", "xp_gain", "hit_cost", "net_gain", "current_xp", "new_xp", "horizon", "bank_after"}
    swap = data["suggestions"][0]
    assert set(swap) == {"position", "out", "in", "xp_gain", "xp_gain_next", "cost_change", "reason"}
    for side in (swap["out"], swap["in"]):
        assert {"id", "name", "team", "position", "price", "xp_horizon", "xp_next", "image_url"} <= set(side)


def test_the_proposed_squad_is_a_lineup_with_one_captain(league_api):
    data = plan(league_api, "?transfers=3")
    xi, bench = data["squad"]["starting_xi"], data["squad"]["bench"]
    assert (len(xi), len(bench)) == (11, 4)
    assert sum(p["is_captain"] for p in xi) == 1 and sum(p["is_vice_captain"] for p in xi) == 1
    assert not any(p["is_captain"] or p["is_vice_captain"] for p in bench)
    assert sum(p["is_new"] for p in xi + bench) == data["summary"]["transfers_used"]


def test_the_transfer_count_is_a_cap(league_api):
    assert plan(league_api, "?transfers=1")["summary"]["transfers_used"] <= 1
    assert plan(league_api, "?transfers=1")["transfers_requested"] == 1


def test_extra_transfers_beyond_the_free_ones_cost_a_hit(league_api):
    data = plan(league_api, "?transfers=5")
    used = data["summary"]["transfers_used"]
    assert used > 2  # a poor squad is worth more than two transfers
    assert data["summary"]["hit_cost"] == 4 * (used - 2)
    assert data["summary"]["net_gain"] == pytest.approx(data["summary"]["xp_gain"] - data["summary"]["hit_cost"], abs=0.11)


@pytest.mark.parametrize("query", ["?transfers=0", "?transfers=6", "?transfers=abc", "?chip=bogus"])
def test_invalid_options_are_rejected(league_api, query):
    assert league_api.client.get(f"/api/transfer-suggestions/7{query}").status_code == 422


def test_a_chip_already_played_is_refused_with_a_clear_message(league_api):
    assert plan(league_api, "?chip=3xc") == {"error": "Your Triple Captain has already been played in this half of the season."}


def test_a_wildcard_rebuilds_the_squad_without_a_hit(league_api):
    data = plan(league_api, "?chip=wildcard")
    assert data["chip"] == "wildcard" and data["summary"]["hit_cost"] == 0
    assert data["summary"]["transfers_used"] > 5
    assert data["summary"]["horizon"] == "next 5 gameweeks"
    assert data["summary"]["new_xp"] > data["summary"]["current_xp"]
    assert any("Wildcard" in note for note in data["notes"])


def test_a_wildcard_ignores_the_transfer_count(league_api):
    assert plan(league_api, "?chip=wildcard&transfers=1")["suggestions"] == plan(league_api, "?chip=wildcard&transfers=5")["suggestions"]


def test_a_free_hit_plans_one_gameweek(league_api):
    data = plan(league_api, "?chip=freehit")
    assert data["summary"]["horizon"] == "next gameweek"
    assert data["summary"]["hit_cost"] == 0
    assert any("reverts" in note for note in data["notes"])


def test_bench_boost_reports_what_the_bench_adds(league_api):
    data = plan(league_api, "?chip=bboost")
    assert data["highlight"]["kind"] == "bench" and data["highlight"]["xp_next"] >= 0


def test_triple_captain_names_the_captain(league_api):
    league_api.history["chips"] = []  # not yet played
    data = plan(league_api, "?chip=3xc")
    captain = next(p for p in data["squad"]["starting_xi"] if p["is_captain"])
    assert data["highlight"]["kind"] == "captain" and data["highlight"]["name"] == captain["name"]
    assert data["highlight"]["xp_next"] > 0 and data["highlight"]["image_url"]


def test_planning_works_when_the_history_cannot_be_read(league_api):
    league_api.history = None
    data = plan(league_api)
    assert data["free_transfers"] is None and data["free_transfers_known"] is False
    assert data["transfers_requested"] == 1  # assumes the one transfer everyone has
    assert plan(league_api, "?chip=3xc")["highlight"]["kind"] == "captain"  # chips can't be checked, so allowed


def test_an_optimiser_failure_becomes_an_error_message(league_api, monkeypatch):
    def fail(*args, **kwargs):
        raise OptimisationError("No squad fits the budget and squad rules.")

    monkeypatch.setattr(main, "build_plan", fail)
    assert plan(league_api) == {"error": "No squad fits the budget and squad rules."}


def test_unknown_manager_has_no_plan(league_api):
    assert league_api.client.get("/api/transfer-suggestions/999").json() == {"error": "Manager ID not found."}


def test_the_chip_options_match_the_planner():
    assert get_args(main.Chip) == CHIPS


def test_planning_does_not_mutate_cached_data(league_api, league):
    bootstrap, fixtures = league
    before = copy.deepcopy((bootstrap, fixtures, league_api.squad, league_api.history))
    for query in ("", "?transfers=4", "?chip=wildcard", "?chip=freehit", "?chip=bboost"):
        assert league_api.client.get(f"/api/transfer-suggestions/7{query}").status_code == 200
    assert (bootstrap, fixtures, league_api.squad, league_api.history) == before
