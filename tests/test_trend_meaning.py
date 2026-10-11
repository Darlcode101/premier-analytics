"""E-4, E-5: trend moments carry their meaning as facts; comparisons in text are checked."""
import pytest

from premier_analytics.agents import CriticAgent
from premier_analytics.generator import generate_match
from premier_analytics.overlay import Names
from premier_analytics.scout import STAKES, MomentScout, Fact, Moment

TRENDS = ("momentum_shift", "pressure_spell")
MIN = 60_000


def trend_moments(seed):
    m = generate_match("har", "ngc", seed)
    scout = MomentScout("har", "ngc", m.meta.match_id)
    goals = []
    out = []
    for e in m.events:
        if e.type == "goal":
            goals.append(e)
        for mo in scout.observe(e):
            if mo.kind in TRENDS:
                out.append((mo, list(goals)))
    return out


def facts(mo):
    return {f.label: f.value for f in mo.facts}


@pytest.mark.parametrize("seed", [42, 7, 9])
def test_every_trend_moment_has_its_meaning(seed):
    moments = trend_moments(seed)
    assert moments
    for mo, _ in moments:
        f = facts(mo)
        assert f["stakes"] in STAKES.values()
        assert f["spell_rank"] in ("first spell on top", "strongest spell so far", "back on top", "another spell on top")
        assert isinstance(f["window_shots_before"], int) and isinstance(f["opponent_window_shots"], int)
        assert f["shots_trend"] in ("more shots than the 10 minutes before", "fewer shots than the 10 minutes before",
                                    "as many shots as the 10 minutes before")
        assert isinstance(f["goals_in_spell"], int)


@pytest.mark.parametrize("seed", [42, 7, 9])
def test_meaning_is_consistent_with_the_numbers(seed):
    seen_teams = set()
    for mo, goals in trend_moments(seed):
        f = facts(mo)
        mine, theirs = (f["score_home"], f["score_away"]) if mo.team_id == "har" else (f["score_away"], f["score_home"])
        diff = mine - theirs
        expected = ("opener" if mine == theirs == 0 else "level" if diff == 0 else
                    "one_down" if diff == -1 else "behind" if diff < -1 else "one_up" if diff == 1 else "ahead")
        assert f["stakes"] == STAKES[expected]
        before, now = f["window_shots_before"], f["window_shots"]
        trend = "more" if now > before else "fewer" if now < before else "as many"
        assert f["shots_trend"].startswith(trend)
        recent = [g for g in goals if g.team_id == mo.team_id and mo.elapsed_ms - g.elapsed_ms < 10 * MIN]
        assert f["goals_in_spell"] == len(recent)
        if mo.team_id not in seen_teams:
            assert f["spell_rank"] == "first spell on top"
        seen_teams.add(mo.team_id)


# ---------- E-5: comparisons ----------

NAMES = Names(home_id="har", away_id="ngc", clubs={"har": "Harbourside", "ngc": "Northgate"}, players={})
CRITIC = CriticAgent(set(), {"Harbourside", "Northgate"})


def trend(**values):
    fs = [Fact(id=f"m-f{i}", label=k, value=v, subject="har", source_event_ids=["e"]) for i, (k, v) in enumerate(values.items())]
    return Moment(id="m", kind="pressure_spell", severity=0.5, event_id="e", period=1, clock_ms=30 * MIN,
                  elapsed_ms=30 * MIN, team_id="har", facts=fs)


def problems(text, m):
    return CRITIC.review("Harbourside on top", text, m, NAMES).problems


def test_double_needs_two_facts_in_that_ratio():
    m = trend(team_shots=6, opponent_shots=5, window_shots=3, window_shots_before=3, spell_rank="back on top")
    assert any("double" in p for p in problems("Harbourside have double the shots of Northgate.", m))
    ok = trend(team_shots=10, opponent_shots=5, spell_rank="back on top")
    assert problems("Harbourside have double the shots of Northgate.", ok) == []
    ok2 = trend(window_shots=4, window_shots_before=2, spell_rank="back on top")
    assert problems("Twice as many shots as in the ten minutes before.", ok2) == []


def test_three_times_needs_that_ratio():
    m = trend(window_shots=4, window_shots_before=2, spell_rank="back on top")
    assert any("three times" in p for p in problems("Three times the shots of before.", m))


def test_superlatives_need_the_spell_fact():
    back = trend(spell_rank="back on top")
    assert any("strongest" in p for p in problems("Their strongest spell of the match.", back))
    assert any("first time" in p for p in problems("On top for the first time.", back))
    strongest = trend(spell_rank="strongest spell so far")
    assert problems("Their strongest spell of the match.", strongest) == []
    first = trend(spell_rank="first spell on top")
    assert problems("On top for the first time.", first) == []


def test_first_half_is_not_a_superlative():
    assert problems("Pressure building in the first half.", trend(spell_rank="back on top")) == []


def test_score_wording_must_match_the_stakes():
    from premier_analytics.scout import STAKES
    level = trend(stakes=STAKES["opener"], spell_rank="back on top", score_home=0, score_away=0)
    assert any("trail" in p for p in problems("Northgate dominate but trail 0-0.", level))
    assert problems("Northgate dominate but it's still 0-0.", level) == []
    up = trend(stakes=STAKES["one_up"], spell_rank="back on top")
    assert any("equalis" in p for p in problems("Harbourside push for an equaliser.", up))
    down = trend(stakes=STAKES["one_down"], spell_rank="back on top")
    assert any("protect" in p for p in problems("Harbourside protect their lead.", down))


# ---------- E-6: missed chances ----------

MISSED = ("big_chance", "woodwork", "shot_on_target", "rocket_shot")


@pytest.mark.parametrize("seed", [42, 7, 9])
def test_missed_chances_say_what_they_would_have_meant(seed):
    from premier_analytics.scout import IF_SCORED
    m = generate_match("har", "ngc", seed)
    scout = MomentScout("har", "ngc", m.meta.match_id)
    found = 0
    for e in m.events:
        for mo in scout.observe(e):
            if mo.kind not in MISSED:
                continue
            found += 1
            f = facts(mo)
            mine, theirs = (f["score_home"], f["score_away"]) if mo.team_id == "har" else (f["score_away"], f["score_home"])
            diff = mine - theirs
            key = ("opener" if mine == theirs == 0 else "ahead" if diff == 0 else "equalise" if diff == -1
                   else "back" if diff < -1 else "extend")
            assert f["if_scored"] == IF_SCORED[key]
    assert found


def test_captions_must_not_contradict_what_the_miss_would_have_meant():
    from premier_analytics.scout import IF_SCORED
    opener = trend(if_scored=IF_SCORED["opener"])
    assert any("equalis" in p for p in problems("It would have been the equaliser.", opener))
    assert problems("It would have broken the deadlock.", opener) == []
    equalise = trend(if_scored=IF_SCORED["equalise"])
    assert any("lead" in p for p in problems("So close to giving them the lead.", equalise))
    assert problems("So close to levelling it.", equalise) == []


# ---------- E-7: goals ----------

@pytest.mark.parametrize("seed", [42, 7, 9])
def test_goals_say_how_they_fit_the_game(seed):
    from premier_analytics.scout import RUN_OF_PLAY
    m = generate_match("har", "ngc", seed)
    scout = MomentScout("har", "ngc", m.meta.match_id)
    shots = {"har": 0, "ngc": 0}
    shots_at_goal = {"har": 0, "ngc": 0}
    last_goal_ms = 0
    found = 0
    for e in m.events:
        if e.type == "shot":
            shots[e.team_id] += 1
        for mo in scout.observe(e):
            if mo.kind != "goal":
                continue
            found += 1
            f = facts(mo)
            mine, theirs = f["team_xg"], f["opponent_xg"]
            key = "rewards" if mine - theirs > 0.3 else "against" if theirs - mine > 0.3 else "even"
            assert f["run_of_play"] == RUN_OF_PLAY[key]
            assert f["shots_since_their_last_goal"] == shots[mo.team_id] - shots_at_goal[mo.team_id]
            assert f["minutes_since_last_goal"] == (e.elapsed_ms - last_goal_ms) // MIN
        if e.type == "goal":
            shots_at_goal[e.team_id] = shots[e.team_id]
            last_goal_ms = e.elapsed_ms
    assert found


def test_captions_must_not_contradict_the_run_of_play():
    from premier_analytics.scout import RUN_OF_PLAY
    against = trend(run_of_play=RUN_OF_PLAY["against"])
    assert any("deserved" in p for p in problems("A deserved goal after all their pressure.", against))
    assert problems("A goal against the run of play.", against) == []
    rewards = trend(run_of_play=RUN_OF_PLAY["rewards"])
    assert any("against the run of play" in p for p in problems("A goal against the run of play.", rewards))


# ---------- false positives seen when replaying round 6 ----------

def test_doubling_a_lead_is_football_language_not_a_ratio():
    m = trend(team_shots=6, opponent_shots=5, spell_rank="back on top")
    assert problems("Harbourside double their lead.", m) == []
    assert problems("A goal that doubles the advantage.", m) == []
    assert any("double" in p for p in problems("Double the shots of Northgate.", m))


def test_the_score_a_missed_chance_would_have_made_is_allowed():
    from premier_analytics.scout import IF_SCORED
    m = generate_match("kin", "oak", 9)
    scout = MomentScout("kin", "oak", m.meta.match_id)
    for e in m.events:
        for mo in scout.observe(e):
            if mo.kind in MISSED:
                f = facts(mo)
                if mo.team_id == "kin":
                    assert (f["score_home_if_scored"], f["score_away_if_scored"]) == (f["score_home"] + 1, f["score_away"])
                else:
                    assert (f["score_home_if_scored"], f["score_away_if_scored"]) == (f["score_home"], f["score_away"] + 1)
    back = trend(if_scored=IF_SCORED["back"], score_home=2, score_away=0, score_home_if_scored=2, score_away_if_scored=1)
    assert problems("A goal would have made it 2-1 and cut the lead.", back) == []


def test_cutting_the_lead_is_not_taking_it():
    from premier_analytics.scout import IF_SCORED
    back = trend(if_scored=IF_SCORED["back"], score_home=2, score_away=0)
    assert problems("Kingsmere still ahead 2-0; it would have cut the lead.", back) == []
    assert any("level" in p for p in problems("It would have levelled the score.", back))
    goal = Moment(id="g", kind="goal", severity=1, event_id="e", period=2, clock_ms=60 * MIN, elapsed_ms=60 * MIN,
                  team_id="ngc", facts=[Fact(id="g-f0", label="goal_context", value="pulls_one_back", subject="ngc",
                                             source_event_ids=["e"]),
                                        Fact(id="g-f1", label="score_home", value=2, source_event_ids=["e"]),
                                        Fact(id="g-f2", label="score_away", value=1, source_event_ids=["e"])])
    assert problems("Northgate cut the lead to 2-1, Harbourside still ahead.", goal) == []
    assert any("take" in p.lower() or "lead" in p for p in problems("Northgate take the lead!", goal))
