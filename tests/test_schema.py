"""Event schema: D-2, I-2 (reject malformed), R-1 contract (published JSON schema)."""
import json
from pathlib import Path

import jsonschema
import pytest
from pydantic import ValidationError

from premier_analytics.schema import PITCH_LENGTH, PITCH_WIDTH, Event, event_json_schema

SCHEMA_FILE = Path(__file__).parent.parent / "schemas" / "event.schema.json"


def valid_pass(**overrides):
    base = dict(
        id="m1-e10", match_id="m1", seq=10, period=1, clock_ms=61_000, elapsed_ms=61_000,
        type="pass", team_id="har", player_id="har-08", x=40.0, y=30.0, end_x=55.0, end_y=20.0,
        outcome="complete", receiver_id="har-10", under_pressure=False,
    )
    base.update(overrides)
    return base


def test_valid_pass_parses():
    e = Event.model_validate(valid_pass())
    assert e.type == "pass"


@pytest.mark.parametrize("field", ["id", "match_id", "seq", "period", "clock_ms", "elapsed_ms", "type"])
def test_missing_core_field_rejected(field):
    data = valid_pass()
    del data[field]
    with pytest.raises(ValidationError):
        Event.model_validate(data)


@pytest.mark.parametrize(
    "overrides",
    [
        {"x": PITCH_LENGTH + 0.1},
        {"x": -0.1},
        {"y": PITCH_WIDTH + 0.1},
        {"end_x": 200.0},
        {"type": "teleport"},
        {"period": 3},
        {"clock_ms": -1},
        {"outcome": "goal"},  # not a valid pass outcome
        {"unknown_field": 1},  # schema is closed
    ],
)
def test_malformed_event_rejected(overrides):
    with pytest.raises(ValidationError):
        Event.model_validate(valid_pass(**overrides))


@pytest.mark.parametrize("missing", ["end_x", "end_y", "outcome", "player_id", "team_id"])
def test_pass_requires_type_specific_fields(missing):
    data = valid_pass()
    del data[missing]
    with pytest.raises(ValidationError):
        Event.model_validate(data)


def test_complete_pass_requires_receiver():
    data = valid_pass()
    del data["receiver_id"]
    with pytest.raises(ValidationError):
        Event.model_validate(data)


def test_shot_requires_speed_and_valid_outcome():
    shot = dict(
        id="m1-e11", match_id="m1", seq=11, period=1, clock_ms=62_000, elapsed_ms=62_000,
        type="shot", team_id="har", player_id="har-09", x=92.0, y=34.0, end_x=105.0, end_y=34.0,
        outcome="saved", shot_speed_kmh=95.0, body_part="right_foot",
    )
    Event.model_validate(shot)
    with pytest.raises(ValidationError):
        Event.model_validate({**shot, "shot_speed_kmh": None})
    with pytest.raises(ValidationError):
        Event.model_validate({**shot, "outcome": "complete"})


def test_goal_requires_score_and_shot_link():
    goal = dict(
        id="m1-e12", match_id="m1", seq=12, period=1, clock_ms=62_000, elapsed_ms=62_000,
        type="goal", team_id="har", player_id="har-09", score_home=1, score_away=0,
        related_event_id="m1-e11",
    )
    Event.model_validate(goal)
    for missing in ("score_home", "score_away", "related_event_id"):
        bad = dict(goal)
        del bad[missing]
        with pytest.raises(ValidationError):
            Event.model_validate(bad)


def test_published_schema_file_is_current():
    """The checked-in JSON schema must match the code, so external consumers see the truth."""
    assert SCHEMA_FILE.exists(), "run: python -m premier_analytics.schema > schemas/event.schema.json"
    assert json.loads(SCHEMA_FILE.read_text()) == event_json_schema()


def test_generated_events_validate_against_published_schema(match):
    schema = json.loads(SCHEMA_FILE.read_text())
    validator = jsonschema.Draft202012Validator(schema)
    for e in match.events:
        validator.validate(json.loads(e.model_dump_json(exclude_none=True)))
