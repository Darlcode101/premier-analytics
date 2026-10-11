"""Web backend: R-2 live delivery, P-1..P-6 per-viewer experiences, N-2 budget guards."""
import re

import pytest
from fastapi.testclient import TestClient

from premier_analytics.agents import Explanation, FakeLLM, Personalised
from premier_analytics.app import create_app
from premier_analytics.generator import generate_match


def fake_llm():
    def explainer(p):
        fid = re.search(r"\[([^\]]+-f\d+)\]", p).group(1)
        return Explanation(headline="Why it matters", why="A moment that changes the game", evidence=[fid])

    return FakeLLM({
        "explainer": explainer,
        "personaliser": lambda p: Personalised(headline="AI headline", body="AI body"),
        "translator": lambda p: Personalised(headline="Titular IA", body="Cuerpo IA"),
        "recap": lambda p: __import__("premier_analytics.recap", fromlist=["Recap"]).RecapDraft(
            headline="Recap", summary="A match.", key_points=[]),
    })


@pytest.fixture
def client():
    app = create_app(llm=fake_llm(), live_session=False, max_sessions=3)
    with TestClient(app) as c:
        yield c


def start(client, home="har", away="ngc", seed=42, autostart=True):
    r = client.post("/api/matches", json={"home": home, "away": away, "seed": seed, "speed": 0,
                                          "autostart": autostart})
    assert r.status_code == 201, r.text
    return r.json()["match_id"]


def collect(ws, until="end", limit=20_000):
    msgs = []
    for _ in range(limit):
        m = ws.receive_json()
        msgs.append(m)
        if m["type"] == until:
            break
    return msgs


def test_health_and_clubs(client):
    assert client.get("/api/health").json()["status"] == "ok"
    clubs = client.get("/api/clubs").json()
    assert len(clubs) == 8
    assert {"id", "name", "short_name", "colors", "players"} <= set(clubs[0])
    assert {"id", "name", "number", "position"} <= set(clubs[0]["players"][0])


def test_unknown_club_rejected(client):
    r = client.post("/api/matches", json={"home": "har", "away": "nope", "seed": 1, "speed": 0})
    assert r.status_code == 422


def test_full_match_stream(client):
    mid = start(client)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as ws:
        msgs = collect(ws)
    types = [m["type"] for m in msgs]
    assert types[0] == "hello"
    hello = msgs[0]
    assert hello["home"]["name"] and hello["away"]["colors"] and len(hello["home"]["lineup"]) == 11
    assert "event" in types and "stats" in types and "overlay" in types and "screen" in types
    end = msgs[-1]
    final = generate_match("har", "ngc", 42).events[-1]
    assert (end["score_home"], end["score_away"]) == (final.score_home, final.score_away)
    # events carry the clock for synchronised rendering
    ev = next(m for m in msgs if m["type"] == "event")
    assert {"clock_ms", "period", "display_minute", "kind", "x", "y"} <= set(ev)


def test_ai_upgrades_reach_the_viewer(client):
    mid = start(client)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as ws:
        msgs = collect(ws)
    overlays = [m["overlay"] for m in msgs if m["type"] == "overlay"]
    ai = [o for o in overlays if o["source"] == "ai"]
    assert ai and all(o["headline"] == "AI headline" for o in ai)
    fast_ids = {o["id"] for o in overlays if o["source"] == "template"}
    assert {o["id"] for o in ai} <= fast_ids


def test_two_viewers_get_different_experiences(client):
    mid = start(client, autostart=False)  # wait for both viewers, then kick off
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as fan, \
            client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=es") as analyst:
        client.post(f"/api/matches/{mid}/start")
        fan_msgs, analyst_msgs = collect(fan), collect(analyst)
    fan_o = [m["overlay"] for m in fan_msgs if m["type"] == "overlay"]
    an_o = [m["overlay"] for m in analyst_msgs if m["type"] == "overlay"]
    assert len(an_o) > len(fan_o), "analysts see more moments"
    assert all(o["language"] == "es" for o in an_o) and all(o["language"] == "en" for o in fan_o)
    assert {o["audience"] for o in fan_o} == {"fan.en.-.-"}


def test_arabic_viewer_gets_rtl_overlays(client):
    mid = start(client)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=ar") as ws:
        msgs = collect(ws)
    overlays = [m["overlay"] for m in msgs if m["type"] == "overlay"]
    assert overlays and all(o["direction"] == "rtl" for o in overlays)


def test_trace_and_recap_messages(client):
    mid = start(client)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as ws:
        msgs = collect(ws)
    trace = [m["trace"] for m in msgs if m["type"] == "trace"]
    assert {t["agent"] for t in trace} >= {"explainer", "critic", "personaliser"}
    recaps = [m["recap"] for m in msgs if m["type"] == "recap"]
    assert {r["kind"] for r in recaps} == {"half_time", "full_time"}


def test_invalid_profile_closes_socket(client):
    mid = start(client)
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/matches/{mid}?mode=wizard&language=en") as ws:
            ws.receive_json()


def test_unknown_match_is_404(client):
    assert client.post("/api/matches/nope/start").status_code == 404


def test_session_cap(client):
    for seed in range(3):
        start(client, seed=seed)
    r = client.post("/api/matches", json={"home": "har", "away": "ngc", "seed": 9, "speed": 0})
    assert r.status_code == 429


def test_late_joiner_gets_backfill(client):
    """Someone joining mid-match sees the key moments so far, not an empty feed."""
    mid = start(client)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as first:
        collect(first)  # match is now over
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as late:
        hello = late.receive_json()
        assert hello["type"] == "hello"
        backfill = late.receive_json()
    assert backfill["type"] == "backfill"
    assert any(o["kind"] == "goal" for o in backfill["overlays"])


def test_serves_built_frontend_with_spa_fallback(tmp_path):
    (tmp_path / "index.html").write_text("<!doctype html><title>PA</title>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "app.js").write_text("console.log(1)")
    app = create_app(llm=None, live_session=False, static_dir=tmp_path)
    with TestClient(app) as c:
        assert "<title>PA</title>" in c.get("/").text
        assert c.get("/assets/app.js").text == "console.log(1)"
        assert "<title>PA</title>" in c.get("/some/client/route").text  # SPA fallback
        assert c.get("/api/health").json()["status"] == "ok"           # API still wins


def test_offline_modes():
    from premier_analytics.demo_llm import down_llm, scripted_llm

    for llm, expect_ai in ((scripted_llm(), True), (down_llm(), False)):
        app = create_app(llm=llm, live_session=False)
        with TestClient(app) as c:
            mid = c.post("/api/matches", json={"home": "har", "away": "ngc", "seed": 7, "speed": 0}).json()["match_id"]
            with c.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=es") as ws:
                msgs = collect(ws)
        overlays = [m["overlay"] for m in msgs if m["type"] == "overlay"]
        assert overlays, "template overlays always flow"
        assert any(o["source"] == "ai" for o in overlays) == expect_ai


def test_finished_unwatched_sessions_free_their_slot():
    app = create_app(llm=None, live_session=False, max_sessions=1)
    with TestClient(app) as c:
        mid = c.post("/api/matches", json={"home": "har", "away": "ngc", "seed": 1, "speed": 0}).json()["match_id"]
        with c.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as ws:
            collect(ws)
        r = c.post("/api/matches", json={"home": "har", "away": "ngc", "seed": 2, "speed": 0})
        assert r.status_code == 201


def test_keyless_auth_when_no_api_key(monkeypatch):
    """With no API key configured the app signs in to Foundry with Entra ID (managed identity in Azure)."""
    from premier_analytics.app import build_llm_from_env

    monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.services.ai.azure.com/api/projects/p")
    monkeypatch.setenv("LIVE_MODEL_DEPLOYMENT", "gpt-4.1-mini")
    monkeypatch.setenv("RECAP_MODEL_DEPLOYMENT", "gpt-5-mini")
    monkeypatch.delenv("AZURE_OPENAI_API_KEY", raising=False)
    llm = build_llm_from_env()
    assert llm is not None
    assert llm.primary.auth == "entra" and llm.fallback.auth == "entra"

    monkeypatch.setenv("AZURE_OPENAI_API_KEY", "local-dev-key")
    assert build_llm_from_env().primary.auth == "key"


def test_no_endpoint_means_no_models(monkeypatch):
    from premier_analytics.app import build_llm_from_env

    monkeypatch.delenv("AZURE_OPENAI_ENDPOINT", raising=False)
    assert build_llm_from_env() is None


def test_late_joiner_gets_momentum_history(client):
    mid = start(client)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as first:
        collect(first)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as late:
        hello = late.receive_json()
    history = hello["momentum"]
    assert len(history) >= 90, "about one point per match minute"
    minutes = [p["minute"] for p in history]
    assert minutes == sorted(minutes) and len(set(minutes)) == len(minutes)
    assert all(-1 <= p["value"] <= 1 for p in history)


def test_models_are_warmed_at_startup():
    warmed = []

    class Warmable:
        name = "warmable"

        async def warm(self):
            warmed.append(True)

        async def generate(self, *a, **k):
            raise RuntimeError("unused")

    with TestClient(create_app(llm=Warmable(), live_session=False)) as c:
        assert c.get("/api/health").status_code == 200
    assert warmed == [True]


def test_azure_app_service_uses_managed_identity_directly(monkeypatch):
    from azure.identity.aio import ManagedIdentityCredential

    from premier_analytics.agents import AgentFrameworkLLM

    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost:42356/msi/token")
    monkeypatch.setenv("IDENTITY_HEADER", "x")
    seen = {}
    import premier_analytics.agents as agents_mod
    real = __import__("azure.identity.aio", fromlist=["get_bearer_token_provider"]).get_bearer_token_provider

    def spy(cred, scope):
        seen["cred"], seen["scope"] = cred, scope
        return real(cred, scope)

    monkeypatch.setattr("azure.identity.aio.get_bearer_token_provider", spy)
    AgentFrameworkLLM("gpt-4.1-mini", "https://example.services.ai.azure.com/api/projects/p")
    assert isinstance(seen["cred"], ManagedIdentityCredential)
    assert seen["scope"] == agents_mod.FOUNDRY_SCOPE


def test_rejoining_viewer_gets_ai_versions_not_templates(client):
    """Regression: backfill rebuilt template overlays even when AI upgrades already existed,
    so refreshing the page lost every earlier explanation."""
    mid = start(client)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as first:
        msgs = collect(first)
    ai_ids = {m["overlay"]["id"] for m in msgs if m["type"] == "overlay" and m["overlay"]["source"] == "ai"}
    assert ai_ids
    with client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as again:
        again.receive_json()  # hello
        backfill = again.receive_json()["overlays"]
    by_id = {o["id"]: o for o in backfill}
    assert all(by_id[i]["source"] == "ai" for i in ai_ids if i in by_id)
    assert any(i in by_id for i in ai_ids)


def test_index_is_never_stale_but_hashed_assets_cache_forever(tmp_path):
    """Regression: browsers kept a stale index.html after a deploy and ran the previous app."""
    (tmp_path / "index.html").write_text("<!doctype html>")
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "index-abc123.js").write_text("1")
    with TestClient(create_app(llm=None, live_session=False, static_dir=tmp_path)) as c:
        for path in ("/", "/fan?match=x"):
            assert c.get(path).headers["cache-control"] == "no-cache"
        assert "immutable" in c.get("/assets/index-abc123.js").headers["cache-control"]


def test_user_assigned_identity_is_selected_by_client_id(monkeypatch):
    from premier_analytics.agents import AgentFrameworkLLM

    monkeypatch.setenv("IDENTITY_ENDPOINT", "http://localhost:42356/msi/token")
    monkeypatch.setenv("IDENTITY_HEADER", "x")
    monkeypatch.setenv("AZURE_CLIENT_ID", "11111111-2222-3333-4444-555555555555")
    seen = {}
    real = __import__("azure.identity.aio", fromlist=["ManagedIdentityCredential"]).ManagedIdentityCredential

    class Spy(real):
        def __init__(self, **kwargs):
            seen.update(kwargs)
            super().__init__(**kwargs)

    monkeypatch.setattr("azure.identity.aio.ManagedIdentityCredential", Spy)
    AgentFrameworkLLM("gpt-4.1-mini", "https://example.services.ai.azure.com/api/projects/p")
    assert seen.get("client_id") == "11111111-2222-3333-4444-555555555555"
