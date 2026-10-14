"""Tiny hand-built matches with hand-calculated answers (golden fixtures)."""
from premier_analytics.schema import Event

HOME, AWAY = "home", "away"
SEC = 1000
MIN = 60 * SEC


class Fx:
    """Append events with auto ids/seq. Times are seconds of elapsed match time (period 1)."""

    def __init__(self):
        self.events: list[Event] = []

    def add(self, etype: str, t: float, **fields) -> Event:
        seq = len(self.events)
        e = Event(
            id=f"fx-{seq:05d}", match_id="fx", seq=seq, period=1,
            clock_ms=int(t * SEC), elapsed_ms=int(t * SEC), type=etype, **fields,
        )
        self.events.append(e)
        return e

    # shorthands
    def kickoff(self, t, team=HOME, player="h9"):
        return self.add("kickoff", t, team_id=team, player_id=player)

    def pass_(self, t, team, x, y, ex, ey, outcome="complete", player=None, receiver=None, pressed=False):
        p = player or ("h8" if team == HOME else "a8")
        r = receiver or ("h10" if team == HOME else "a10")
        return self.add(
            "pass", t, team_id=team, player_id=p, x=x, y=y, end_x=ex, end_y=ey, outcome=outcome,
            receiver_id=r if outcome == "complete" else None, under_pressure=pressed,
        )

    def change(self, t, team, x=50.0, y=34.0, cause="interception"):
        return self.add("possession_change", t, team_id=team, cause=cause, x=x, y=y)

    def shot(self, t, team, x, y, outcome="saved", player=None, body="right_foot", speed=90.0):
        p = player or ("h9" if team == HOME else "a9")
        return self.add(
            "shot", t, team_id=team, player_id=p, x=x, y=y, end_x=105.0, end_y=34.0, outcome=outcome,
            shot_speed_kmh=speed, body_part=body,
        )

    def goal(self, t, team, shot, score_home, score_away, assist=None):
        return self.add(
            "goal", t, team_id=team, player_id=shot.player_id, score_home=score_home,
            score_away=score_away, related_event_id=shot.id, assist_id=assist,
        )

    def tackle(self, t, team, x, y, outcome="won", player=None):
        p = player or ("h4" if team == HOME else "a4")
        return self.add("tackle", t, team_id=team, player_id=p, x=x, y=y, outcome=outcome)

    def interception(self, t, team, x, y, player=None):
        p = player or ("h5" if team == HOME else "a5")
        return self.add("interception", t, team_id=team, player_id=p, x=x, y=y)

    def foul(self, t, team, x, y, player=None, victim=None):
        p = player or ("h4" if team == HOME else "a4")
        v = victim or ("a9" if team == HOME else "h9")
        return self.add("foul", t, team_id=team, player_id=p, x=x, y=y, fouled_player_id=v)

    def card(self, t, team, player, card="yellow", reason=None):
        reason = reason or ("serious_foul_play" if card == "red" else "late_tackle")
        return self.add("card", t, team_id=team, player_id=player, card=card, card_reason=reason)
