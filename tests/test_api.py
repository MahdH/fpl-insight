import copy

import pytest
from fastapi.testclient import TestClient

from app import main


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
    return TestClient(main.app)


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


def test_transfer_suggestions_are_swaps_for_the_loaded_squad(client):
    data = client.get("/api/transfer-suggestions/43024").json()
    assert data["bank"] == "£0.5m"
    swaps = data["suggestions"]
    assert 1 <= len(swaps) <= 3

    squad = {1, 10, 30, 13}
    for swap in swaps:
        assert swap["out"]["id"] in squad  # you can only sell what you own
        assert swap["in"]["id"] not in squad  # and buy what you don't
        assert swap["out"]["position"] == swap["in"]["position"] == swap["position"]
        assert swap["in"]["xp_horizon"] > swap["out"]["xp_horizon"]
        assert swap["xp_gain"] > 0 and swap["reason"]
        for key in ("name", "team", "price", "xp_next", "image_url"):
            assert key in swap["out"] and key in swap["in"]
    assert len({s["out"]["id"] for s in swaps}) == len(swaps)


def test_transfer_suggestions_respect_the_bank(client):
    for swap in client.get("/api/transfer-suggestions/43024").json()["suggestions"]:
        assert swap["cost_change"] <= 0.5  # never more than the £0.5m bank


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
    main.manager_cache.clear()
    main.entry_cache.clear()
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
    main.manager_cache.clear()
    main.entry_cache.clear()


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
    for path in ("/api/top-picks", "/api/top-performers", "/api/target-fixture", "/api/transfer-suggestions/43024"):
        assert client.get(path).status_code == 200
    assert (bootstrap, fixtures) == before
