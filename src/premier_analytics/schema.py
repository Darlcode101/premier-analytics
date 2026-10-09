"""Event schema for synthetic match streams.

Coordinate convention: metres on a 105 x 68 pitch, always from the perspective of the
event's ``team_id``, attacking towards x = 105. So a shot has a large x, and a defender's
tackle in their own box has a small x. ``possession_change`` coordinates are from the
new possessing team's perspective. Consumers flip (x -> 105 - x, y -> 68 - y) to draw
both teams on one pitch.

Time: ``clock_ms`` is the match clock as shown on screen (second half starts at 45:00).
``elapsed_ms`` is milliseconds of match time since kickoff, monotonic across both
halves, and is what replay uses for pacing.
"""
from __future__ import annotations

import json
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

PITCH_LENGTH = 105.0
PITCH_WIDTH = 68.0

EventType = Literal[
    "period_start", "period_end", "kickoff", "pass", "shot", "goal", "tackle",
    "interception", "pressure", "possession_change", "foul", "card", "substitution",
]

# Actions only the team in possession can make.
ON_BALL_TYPES = frozenset({"pass", "shot"})

OUTCOMES: dict[str, frozenset[str]] = {
    "pass": frozenset({"complete", "incomplete", "out"}),
    "shot": frozenset({"goal", "saved", "off_target", "blocked", "woodwork"}),
    "tackle": frozenset({"won", "lost"}),
}

POSSESSION_CAUSES = frozenset({
    "tackle", "interception", "incomplete_pass", "out_of_play", "save", "goal_kick",
    "blocked_shot", "rebound", "foul",
})

_REQUIRED: dict[str, tuple[str, ...]] = {
    "period_start": (),
    "period_end": ("score_home", "score_away"),
    "kickoff": ("team_id", "player_id"),
    "pass": ("team_id", "player_id", "x", "y", "end_x", "end_y", "outcome"),
    "shot": ("team_id", "player_id", "x", "y", "end_x", "end_y", "outcome", "shot_speed_kmh", "body_part"),
    "goal": ("team_id", "player_id", "score_home", "score_away", "related_event_id"),
    "tackle": ("team_id", "player_id", "x", "y", "outcome"),
    "interception": ("team_id", "player_id", "x", "y"),
    "pressure": ("team_id", "player_id", "x", "y"),
    "possession_change": ("team_id", "cause", "x", "y"),
    "foul": ("team_id", "player_id", "x", "y", "fouled_player_id"),
    "card": ("team_id", "player_id", "card"),
    "substitution": ("team_id", "player_out_id", "player_in_id"),
}

X = Annotated[float, Field(ge=0.0, le=PITCH_LENGTH)]
Y = Annotated[float, Field(ge=0.0, le=PITCH_WIDTH)]


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    match_id: str
    seq: Annotated[int, Field(ge=0)]
    period: Literal[1, 2]
    clock_ms: Annotated[int, Field(ge=0)]
    elapsed_ms: Annotated[int, Field(ge=0)]
    type: EventType

    team_id: str | None = None
    player_id: str | None = None
    x: X | None = None
    y: Y | None = None
    end_x: X | None = None
    end_y: Y | None = None
    outcome: str | None = None

    receiver_id: str | None = None
    under_pressure: bool | None = None
    shot_speed_kmh: Annotated[float, Field(gt=0)] | None = None
    body_part: Literal["right_foot", "left_foot", "head"] | None = None
    assist_id: str | None = None
    related_event_id: str | None = None
    score_home: Annotated[int, Field(ge=0)] | None = None
    score_away: Annotated[int, Field(ge=0)] | None = None
    fouled_player_id: str | None = None
    card: Literal["yellow", "second_yellow", "red"] | None = None
    player_in_id: str | None = None
    player_out_id: str | None = None
    cause: str | None = None

    @model_validator(mode="after")
    def _type_specific(self) -> Event:
        missing = [f for f in _REQUIRED[self.type] if getattr(self, f) is None]
        if missing:
            raise ValueError(f"{self.type} event missing {missing}")
        allowed = OUTCOMES.get(self.type)
        if allowed is None:
            if self.outcome is not None:
                raise ValueError(f"{self.type} events carry no outcome")
        elif self.outcome not in allowed:
            raise ValueError(f"{self.type} outcome must be one of {sorted(allowed)}")
        if self.type == "pass" and self.outcome == "complete" and self.receiver_id is None:
            raise ValueError("complete pass needs receiver_id")
        if self.type == "possession_change" and self.cause not in POSSESSION_CAUSES:
            raise ValueError(f"unknown possession_change cause {self.cause!r}")
        return self


class Weather(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    condition: Literal["clear", "cloudy", "light_rain", "heavy_rain", "windy", "fog"]
    temp_c: float


class Lineup(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    starting: list[str]
    bench: list[str]


class MatchMeta(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    match_id: str
    seed: int
    home_id: str
    away_id: str
    venue: str
    referee: str
    kickoff_local: str
    weather: Weather
    lineups: dict[str, Lineup]


class Match(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    meta: MatchMeta
    events: list[Event]

    def to_jsonl(self) -> str:
        """Metadata line followed by one line per event: the on-disk and wire format."""
        lines = [self.meta.model_dump_json()]
        lines += [e.model_dump_json(exclude_none=True) for e in self.events]
        return "\n".join(lines) + "\n"


def event_json_schema() -> dict:
    return Event.model_json_schema()


if __name__ == "__main__":
    print(json.dumps(event_json_schema(), indent=2, sort_keys=True))
