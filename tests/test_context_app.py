"""CX-2, CX-3, CX-5, CX-6, CX-8 over the web app: context messages, ask endpoint, explainers."""
import pytest
from fastapi.testclient import TestClient

from premier_analytics.app import create_app
from premier_analytics.context import AskDesk, ResearcherAgent
from premier_analytics.demo_llm import down_llm, scripted_llm, scripted_search

from test_app import collect, start
from test_context import ANSWER, LIB_FOR_APP, FakeSearch


@pytest.fixture
def client():
    app = create_app(llm=scripted_llm(delay=0), live_session=False, max_sessions=5,
                     context_library=LIB_FOR_APP, researcher=ResearcherAgent(FakeSearch(ANSWER)))
    with TestClient(app) as c:
        yield c


def test_analysts_get_context_cards_and_fans_do_not(client):
    mid = start(client, autostart=False)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as desk, \
            client.websocket_connect(f"/ws/matches/{mid}?mode=fan&language=en") as fan:
        desk.receive_json(), fan.receive_json()
        client.post(f"/api/matches/{mid}/start")
        desk_msgs, fan_msgs = collect(desk), collect(fan)
    cards = [m["context"] for m in desk_msgs if m["type"] == "context"]
    assert cards and all(c["language"] == "en" and c["sources"] for c in cards)
    assert not [m for m in fan_msgs if m["type"] == "context"]


def test_late_joining_desk_gets_earlier_cards_in_its_language(client):
    mid = start(client)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as ws:
        collect(ws)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=en") as ws:
        hello = ws.receive_json()
    assert hello["context"] and all(c["language"] == "en" for c in hello["context"])


def test_hello_carries_stat_explainers_in_the_viewers_language(client):
    mid = start(client, autostart=False)
    with client.websocket_connect(f"/ws/matches/{mid}?mode=analyst&language=es") as ws:
        hello = ws.receive_json()
    xg = hello["explainers"]["xg"]
    assert xg["text"].startswith("Los goles esperados") and xg["sources"][0]["url"].startswith("https://")


def test_ask_endpoint(client):
    mid = start(client, autostart=False)
    r = client.post(f"/api/matches/{mid}/ask", json={"question": "Average xG per team?", "language": "en"})
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok" and body["sources"] and body["remaining"] == 14
    assert client.post(f"/api/matches/{mid}/ask", json={"question": "", "language": "en"}).status_code == 422
    assert client.post("/api/matches/nope/ask", json={"question": "x", "language": "en"}).status_code == 404


def test_ask_without_a_researcher_says_so():
    with TestClient(create_app(llm=None, live_session=False, researcher=None)) as c:
        mid = start(c, autostart=False)
        assert c.post(f"/api/matches/{mid}/ask", json={"question": "xG?", "language": "en"}).json()["status"] == "unavailable"


def test_outage_means_no_cards_and_nothing_else_breaks():
    app = create_app(llm=down_llm(), live_session=False, context_library=LIB_FOR_APP,
                     researcher=ResearcherAgent(FakeSearch(RuntimeError("down"))))
    with TestClient(app) as c:
        mid = start(c, autostart=False)
        with c.websocket_connect(f"/ws/matches/{mid}?mode=analyst") as ws:
            ws.receive_json()
            c.post(f"/api/matches/{mid}/start")
            msgs = collect(ws)
        assert not [m for m in msgs if m["type"] == "context"]
        assert any(m["type"] == "incident" for m in msgs)
        assert c.post(f"/api/matches/{mid}/ask", json={"question": "xG?", "language": "en"}).json()["status"] == "error"


def test_scripted_search_for_offline_demos_has_a_source():
    import asyncio
    answer = asyncio.run(AskDesk(ResearcherAgent(scripted_search())).ask("xG?", "en"))
    assert answer["status"] == "ok" and answer["sources"][0]["url"].startswith("https://")
