"""Overlays: R-1 (machine-readable), R-4 (validator + scheduler), R-6 (fast path), P-1..P-4 routing."""
import pytest

from fixtures import AWAY, HOME, Fx
from premier_analytics.overlay import (
    KINDS, MAX_BODY, MAX_HEADLINE, Audience, Names, Scheduler, ValidationError, fast_overlay, relevance,
    validate,
)
from premier_analytics.scout import MomentScout

NAMES = Names(
    players={"h9": "Kai Greaves", "h8": "Elias Ekwueme", "a9": "Rory Coldwell", "a4": "Ivo Varga", "h4": "Lars Lindqvist",
             "h10": "Teo Oakes", "h5": "Jonas Vale", "a5": "Milo Strand", "h6": "Abel Fenwick"},
    clubs={HOME: "Northgate City", AWAY: "Harbourside Athletic"},
    home_id=HOME, away_id=AWAY,
)


def moments_of(fx: Fx):
    scout = MomentScout(HOME, AWAY, match_id="fx")
    return [m for e in fx.events for m in scout.observe(e)]


def goal_moment():
    fx = Fx()
    fx.kickoff(0)
    fx.pass_(3, HOME, 80, 20, 92, 34, player="h8", receiver="h9")
    s = fx.shot(5, HOME, 95, 33, outcome="goal", player="h9")
    fx.goal(5, HOME, s, 1, 0, assist="h8")
    return next(m for m in moments_of(fx) if m.kind == "goal")


def yellow_moment():
    fx = Fx()
    fx.kickoff(0)
    fx.foul(10, AWAY, 30, 30, player="a4")
    fx.card(10, AWAY, "a4", "yellow")
    return next(m for m in moments_of(fx) if m.kind == "yellow_card")


FAN = Audience(mode="fan", language="en")
ANALYST = Audience(mode="analyst", language="en")


# ---------- fast path (R-6) ----------

def test_goal_fast_overlay_content():
    m = goal_moment()
    o = fast_overlay(m, FAN, NAMES)
    assert o.source == "template" and o.version == 1
    assert "Kai Greaves" in o.headline + o.body
    assert "1" in o.headline and "0" in o.headline
    assert o.kind == "goal" and o.priority == m.severity and o.team_id == HOME
    assert o.evidence and set(o.evidence) <= {f.id for f in m.facts}
    assert o.language == "en" and o.direction == "ltr"


def test_analyst_overlay_carries_more_numbers_than_fan():
    m = goal_moment()
    fan, analyst = fast_overlay(m, FAN, NAMES), fast_overlay(m, ANALYST, NAMES)
    digits = lambda s: sum(ch.isdigit() for ch in s)  # noqa: E731
    assert digits(analyst.body) > digits(fan.body)
    assert fan.id != analyst.id  # one overlay per audience


def test_overlay_is_machine_readable_and_timed():
    m = goal_moment()
    o = fast_overlay(m, FAN, NAMES)
    data = o.model_dump(mode="json")
    for key in ("id", "match_id", "moment_id", "kind", "priority", "clock_in_ms", "clock_out_ms",
                "elapsed_in_ms", "slot", "headline", "body", "language", "evidence", "data"):
        assert key in data
    assert o.clock_out_ms > o.clock_in_ms
    assert o.data["score_home"] == 1


@pytest.mark.parametrize("language", ["en", "es", "ar"])
@pytest.mark.parametrize("mode", ["fan", "analyst"])
def test_every_kind_renders_in_every_language(match, league, language, mode):
    """Every moment kind the scout can produce has a template in every language and mode."""
    names = Names.from_league(league, match.meta.home_id, match.meta.away_id)
    scout = MomentScout(match.meta.home_id, match.meta.away_id, match.meta.match_id)
    seen = set()
    audience = Audience(mode=mode, language=language)
    for e in match.events:
        for m in scout.observe(e):
            o = fast_overlay(m, audience, names)
            seen.add(m.kind)
            assert o.headline and len(o.headline) <= MAX_HEADLINE, o.headline
            assert len(o.body) <= MAX_BODY, o.body
            assert "{" not in o.headline + o.body and "None" not in o.headline + o.body
            assert o.direction == ("rtl" if language == "ar" else "ltr")
    assert seen <= set(KINDS)


def test_templates_exist_for_all_kinds():
    from premier_analytics.overlay import TEMPLATES

    for language in ("en", "es", "ar"):
        assert set(TEMPLATES[language]) == set(KINDS), language


# ---------- relevance routing (P-1, P-2, P-3) ----------

def test_goals_always_reach_fans():
    assert relevance(goal_moment(), FAN) >= 0.5


def test_yellow_card_is_analyst_only():
    m = yellow_moment()
    assert not FAN.wants(m) and ANALYST.wants(m)


def test_player_focus_surfaces_minor_moments_for_that_player():
    m = yellow_moment()
    focused = Audience(mode="fan", language="en", player_id="a4")
    other = Audience(mode="fan", language="en", player_id="h9")
    assert focused.wants(m) and not other.wants(m)


def test_favourite_club_boost():
    m = yellow_moment()  # away player booked
    assert relevance(m, Audience(mode="fan", club_id=AWAY)) > relevance(m, Audience(mode="fan", club_id=HOME))


def test_audience_key_is_stable():
    a = Audience(mode="fan", language="es", club_id=HOME)
    assert a.key == Audience(mode="fan", language="es", club_id=HOME).key
    assert a.key != Audience(mode="fan", language="en", club_id=HOME).key


# ---------- validator (R-4) ----------

def test_validator_accepts_fast_overlay():
    m = goal_moment()
    validate(fast_overlay(m, FAN, NAMES), m, now_elapsed_ms=m.elapsed_ms)


@pytest.mark.parametrize(
    "change, reason",
    [
        ({"evidence": []}, "evidence"),
        ({"evidence": ["made-up-fact"]}, "evidence"),
        ({"headline": "x" * (MAX_HEADLINE + 1)}, "headline"),
        ({"body": "x" * (MAX_BODY + 1)}, "body"),
        ({"clock_out_ms": 0}, "timing"),
    ],
)
def test_validator_rejects(change, reason):
    m = goal_moment()
    bad = fast_overlay(m, FAN, NAMES).model_copy(update=change)
    with pytest.raises(ValidationError, match=reason):
        validate(bad, m, now_elapsed_ms=m.elapsed_ms)


def test_validator_rejects_stale_ai_overlay():
    m = goal_moment()
    ai = fast_overlay(m, FAN, NAMES).model_copy(update={"source": "ai", "version": 2})
    validate(ai, m, now_elapsed_ms=m.elapsed_ms + 7_000)
    with pytest.raises(ValidationError, match="stale"):
        validate(ai, m, now_elapsed_ms=m.elapsed_ms + 9_000)


# ---------- scheduler (R-4) ----------

def ov(oid, priority, t=0, duration=10_000, slot="lower_third"):
    m = goal_moment()
    base = fast_overlay(m, FAN, NAMES)
    return base.model_copy(update={
        "id": oid, "priority": priority, "elapsed_in_ms": t, "clock_in_ms": t,
        "clock_out_ms": t + duration, "slot": slot,
    })


def test_scheduler_caps_concurrent_overlays():
    s = Scheduler(max_on_screen=2)
    s.offer(ov("a", 0.6, slot="lower_third"), now=0)
    s.offer(ov("b", 0.5, slot="corner"), now=0)
    s.offer(ov("c", 0.4, slot="ticker"), now=0)
    assert [o.id for o in s.on_screen(now=0)] == ["a", "b"]


def test_high_priority_preempts_lowest():
    s = Scheduler(max_on_screen=2)
    s.offer(ov("a", 0.6, slot="lower_third"), now=0)
    s.offer(ov("b", 0.4, slot="corner"), now=0)
    s.offer(ov("goal", 0.95, slot="ticker"), now=1_000)
    assert {o.id for o in s.on_screen(now=1_000)} == {"a", "goal"}


def test_expired_overlays_leave_and_queue_drains():
    s = Scheduler(max_on_screen=1)
    s.offer(ov("a", 0.6, t=0, duration=5_000), now=0)
    s.offer(ov("b", 0.5, t=0, duration=8_000), now=0)
    assert [o.id for o in s.on_screen(now=1_000)] == ["a"]
    shown = s.on_screen(now=6_000)
    assert [o.id for o in shown] == ["b"]
    assert shown[0].clock_out_ms > 6_000, "a queued overlay gets its full duration once shown"


def test_stale_queued_overlays_are_dropped():
    s = Scheduler(max_on_screen=1, max_queue_wait_ms=10_000)
    s.offer(ov("a", 0.9, t=0, duration=30_000), now=0)
    s.offer(ov("b", 0.5, t=0, duration=5_000), now=0)
    assert [o.id for o in s.on_screen(now=31_000)] == []


def test_upgrade_replaces_in_place():
    s = Scheduler(max_on_screen=2)
    first = ov("goal", 0.95, t=0, duration=12_000)
    s.offer(first, now=0)
    upgraded = first.model_copy(update={"version": 2, "source": "ai", "body": "Why it matters ..."})
    s.offer(upgraded, now=2_000)
    shown = s.on_screen(now=2_000)
    assert len(shown) == 1 and shown[0].version == 2 and shown[0].body == "Why it matters ..."
    assert shown[0].clock_out_ms >= first.clock_out_ms


def test_older_version_never_replaces_newer():
    s = Scheduler(max_on_screen=2)
    first = ov("goal", 0.95)
    s.offer(first.model_copy(update={"version": 2, "source": "ai"}), now=0)
    s.offer(first, now=100)
    assert s.on_screen(now=100)[0].version == 2


def test_higher_priority_takes_an_occupied_slot():
    s = Scheduler(max_on_screen=2)
    s.offer(ov("a", 0.5, slot="lower_third"), now=0)
    s.offer(ov("goal", 0.95, slot="lower_third"), now=1_000)
    assert [o.id for o in s.on_screen(now=1_000)] == ["goal"]


def test_slots_do_not_collide():
    s = Scheduler(max_on_screen=3)
    s.offer(ov("a", 0.6, slot="lower_third"), now=0)
    s.offer(ov("b", 0.5, slot="lower_third"), now=0)
    s.offer(ov("c", 0.5, slot="corner"), now=0)
    shown = s.on_screen(now=0)
    assert len({o.slot for o in shown}) == len(shown)


def test_overlay_minute_is_broadcast_style():
    fx = Fx()
    fx.add("period_start", 0)
    fx.kickoff(0)
    fx.add("period_end", 48 * 60 + 5, score_home=0, score_away=0)
    ht = next(m for m in moments_of(fx) if m.kind == "half_time")
    assert fast_overlay(ht, FAN, NAMES).minute == "45+4"
