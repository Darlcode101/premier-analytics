"""Overlays: what reaches the screen.

An Overlay is timed, machine-readable JSON a graphics engine can render over the match
feed (R-1). Every moment first gets a *fast-path* overlay from deterministic templates
(R-6); the AI path may later upgrade it in place, keeping the same ID. Each viewer
audience (mode, language, favourite club, focus player) gets its own overlays (P-1..P-4).
Nothing reaches the screen without passing the Validator, and the Scheduler decides
what is on screen when (R-4).
"""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict

from .scout import ANALYST_THRESHOLD, FAN_THRESHOLD, Moment

MAX_HEADLINE = 60
MAX_BODY = 180
STALE_MS = 8_000

Language = Literal["en", "es", "ar"]
Slot = Literal["lower_third", "corner", "ticker"]

KINDS = (
    "goal", "milestone", "big_chance", "woodwork", "shot_on_target", "rocket_shot", "yellow_card",
    "red_card", "great_pass", "substitution", "half_time", "full_time", "momentum_shift", "pressure_spell",
)

SLOTS: dict[str, Slot] = {
    "goal": "lower_third", "milestone": "lower_third", "red_card": "lower_third",
    "half_time": "lower_third", "full_time": "lower_third", "big_chance": "lower_third",
    "woodwork": "lower_third", "rocket_shot": "corner", "momentum_shift": "corner",
    "pressure_spell": "corner", "shot_on_target": "ticker", "yellow_card": "ticker",
    "great_pass": "ticker", "substitution": "ticker",
}
DURATION_MS = {"goal": 12_000, "milestone": 10_000, "half_time": 15_000, "full_time": 15_000, "red_card": 10_000}
DEFAULT_DURATION_MS = 8_000


class ValidationError(ValueError):
    pass


class Names(BaseModel):
    """Display names for IDs in one match."""
    players: dict[str, str]
    clubs: dict[str, str]
    home_id: str
    away_id: str

    @classmethod
    def from_league(cls, league, home_id: str, away_id: str) -> Names:
        players = {p.id: p.name for c in (home_id, away_id) for p in league.squad(c)}
        clubs = {c: league.club(c).short_name for c in (home_id, away_id)}
        return cls(players=players, clubs=clubs, home_id=home_id, away_id=away_id)

    def player(self, pid: str | None) -> str:
        return self.players.get(pid, pid or "")

    def club(self, cid: str | None) -> str:
        return self.clubs.get(cid, cid or "")


class Audience(BaseModel):
    """One viewing experience. Viewers with the same audience share overlays."""
    model_config = ConfigDict(frozen=True)

    mode: Literal["fan", "analyst"] = "fan"
    language: Language = "en"
    club_id: str | None = None
    player_id: str | None = None

    @property
    def key(self) -> str:
        return f"{self.mode}.{self.language}.{self.club_id or '-'}.{self.player_id or '-'}"

    @property
    def threshold(self) -> float:
        return FAN_THRESHOLD if self.mode == "fan" else ANALYST_THRESHOLD

    def wants(self, m: Moment) -> bool:
        return relevance(m, self) >= self.threshold


def _involves(m: Moment, player_id: str) -> bool:
    return m.player_id == player_id or any(f.value == player_id or f.subject == player_id for f in m.facts)


def relevance(m: Moment, a: Audience) -> float:
    """Moment severity, boosted for the viewer's focus player and favourite club."""
    score = m.severity
    if a.player_id and _involves(m, a.player_id):
        score += 0.35
    if a.club_id and m.team_id == a.club_id:
        score += 0.1
    return min(score, 1.0)


class Overlay(BaseModel):
    id: str
    match_id: str
    moment_id: str
    audience: str
    kind: str
    priority: float
    slot: Slot
    clock_in_ms: int
    clock_out_ms: int
    elapsed_in_ms: int
    headline: str
    body: str
    language: Language
    direction: Literal["ltr", "rtl"]
    source: Literal["template", "ai"]
    version: int
    evidence: list[str]
    data: dict[str, Any]
    model: str | None = None


# ---------- templates ----------
# (headline, fan body, analyst body). Variables are filled from the moment's facts.

TEMPLATES: dict[str, dict[str, tuple[str, str, str]]] = {
    "en": {
        "goal": ("GOAL! {home} {sh}-{sa} {away}", "{player} scores for {team} ({minute}')",
                 "{player} {minute}' · xG {xg} from {dist} m · {team}: {tshots} shots, {txg} xG"),
        "milestone": ("{milestone}! {player}", "{player} has {pg} goals today",
                      "{player}: {pg} goals · {team}"),
        "big_chance": ("BIG CHANCE · {team}", "{player} so close for {team}!",
                       "{player} {minute}' · xG {xg} from {dist} m · {outcome}"),
        "woodwork": ("OFF THE WOODWORK · {team}", "{player} hits the frame of the goal!",
                     "{player} {minute}' · xG {xg} from {dist} m"),
        "shot_on_target": ("SAVE · {opp}", "{player} forces a save", "{player} {minute}' · xG {xg} from {dist} m"),
        "rocket_shot": ("{speed} KM/H STRIKE", "What a hit from {player}!",
                        "{player} · {speed} km/h from {dist} m · xG {xg}"),
        "yellow_card": ("YELLOW CARD · {team}", "{player} is booked ({minute}')", "{player} booked {minute}' · {team}"),
        "red_card": ("RED CARD · {team}", "{player} is sent off! {team} down to {remaining}",
                     "{player} off {minute}' · {team} down to {remaining} players"),
        "great_pass": ("KEY PASS · {player}", "Brilliant pass from {player}",
                       "{player} · difficulty {difficulty} over {pdist} m"),
        "substitution": ("SUBSTITUTION · {team}", "{player_in} on, {player_out} off",
                         "{minute}' {player_in} replaces {player_out}"),
        "half_time": ("HALF-TIME: {home} {sh}-{sa} {away}", "{home} {sh}-{sa} {away} at the break",
                      "Shots {shots_home}-{shots_away} · xG {xg_home}-{xg_away} · possession {poss}%-{poss_away}%"),
        "full_time": ("FULL-TIME: {home} {sh}-{sa} {away}", "Final score: {home} {sh}-{sa} {away}",
                      "Shots {shots_home}-{shots_away} · xG {xg_home}-{xg_away} · possession {poss}%-{poss_away}%"),
        "momentum_shift": ("MOMENTUM · {team}", "{team} are on top right now",
                           "Last {wmin} min: {wshots} shots, {wxg} xG, field tilt {tilt}%"),
        "pressure_spell": ("PRESSURE · {team}", "{team} are pinning {opp} back",
                           "Last {wmin} min: field tilt {tilt}%, {wshots} shots, {tempo} passes/min"),
    },
    "es": {
        "goal": ("¡GOL! {home} {sh}-{sa} {away}", "Marca {player} para el {team} ({minute}')",
                 "{player} {minute}' · xG {xg} a {dist} m · {team}: {tshots} tiros, {txg} xG"),
        "milestone": ("¡{milestone}! {player}", "{player} lleva {pg} goles hoy", "{player}: {pg} goles · {team}"),
        "big_chance": ("OCASIÓN CLARA · {team}", "¡{player} rozó el gol para el {team}!",
                       "{player} {minute}' · xG {xg} a {dist} m · {outcome}"),
        "woodwork": ("¡AL PALO! · {team}", "¡{player} estrella el balón en la madera!",
                     "{player} {minute}' · xG {xg} a {dist} m"),
        "shot_on_target": ("PARADA · {opp}", "{player} obliga al portero a intervenir",
                           "{player} {minute}' · xG {xg} a {dist} m"),
        "rocket_shot": ("DISPARO A {speed} KM/H", "¡Qué zapatazo de {player}!",
                        "{player} · {speed} km/h a {dist} m · xG {xg}"),
        "yellow_card": ("TARJETA AMARILLA · {team}", "{player} ve la amarilla ({minute}')",
                        "{player} amonestado {minute}' · {team}"),
        "red_card": ("TARJETA ROJA · {team}", "¡Expulsado {player}! El {team} se queda con {remaining}",
                     "{player} expulsado {minute}' · {team} con {remaining} jugadores"),
        "great_pass": ("PASE CLAVE · {player}", "Pase brillante de {player}",
                       "{player} · dificultad {difficulty} en {pdist} m"),
        "substitution": ("CAMBIO · {team}", "Entra {player_in}, sale {player_out}",
                         "{minute}' {player_in} sustituye a {player_out}"),
        "half_time": ("DESCANSO: {home} {sh}-{sa} {away}", "{home} {sh}-{sa} {away} al descanso",
                      "Tiros {shots_home}-{shots_away} · xG {xg_home}-{xg_away} · posesión {poss}%-{poss_away}%"),
        "full_time": ("FINAL: {home} {sh}-{sa} {away}", "Resultado final: {home} {sh}-{sa} {away}",
                      "Tiros {shots_home}-{shots_away} · xG {xg_home}-{xg_away} · posesión {poss}%-{poss_away}%"),
        "momentum_shift": ("DOMINIO · {team}", "El {team} manda ahora mismo",
                           "Últimos {wmin} min: {wshots} tiros, {wxg} xG, inclinación del campo {tilt}%"),
        "pressure_spell": ("PRESIÓN · {team}", "El {team} encierra al {opp}",
                           "Últimos {wmin} min: inclinación {tilt}%, {wshots} tiros, {tempo} pases/min"),
    },
    "ar": {
        "goal": ("هدف! {home} {sh}-{sa} {away}", "{player} يسجل لـ{team} (الدقيقة {minute})",
                 "{player} الدقيقة {minute} · xG {xg} من {dist} م · {team}: {tshots} تسديدات، {txg} xG"),
        "milestone": ("{milestone}! {player}", "{player} يسجل {pg} أهداف اليوم", "{player}: {pg} أهداف · {team}"),
        "big_chance": ("فرصة محققة · {team}", "{player} يقترب كثيراً من التسجيل لـ{team}!",
                       "{player} الدقيقة {minute} · xG {xg} من {dist} م · {outcome}"),
        "woodwork": ("في القائم · {team}", "تسديدة {player} ترتطم بالقائم!",
                     "{player} الدقيقة {minute} · xG {xg} من {dist} م"),
        "shot_on_target": ("تصدٍّ · {opp}", "{player} يجبر الحارس على التصدي",
                           "{player} الدقيقة {minute} · xG {xg} من {dist} م"),
        "rocket_shot": ("تسديدة بسرعة {speed} كم/س", "يا لها من قذيفة من {player}!",
                        "{player} · {speed} كم/س من {dist} م · xG {xg}"),
        "yellow_card": ("بطاقة صفراء · {team}", "إنذار لـ{player} (الدقيقة {minute})",
                        "إنذار {player} الدقيقة {minute} · {team}"),
        "red_card": ("بطاقة حمراء · {team}", "طرد {player}! {team} يكمل بـ{remaining} لاعبين",
                     "طرد {player} الدقيقة {minute} · {team} بـ{remaining} لاعبين"),
        "great_pass": ("تمريرة حاسمة · {player}", "تمريرة رائعة من {player}",
                       "{player} · صعوبة {difficulty} لمسافة {pdist} م"),
        "substitution": ("تبديل · {team}", "دخول {player_in} وخروج {player_out}",
                         "الدقيقة {minute}: {player_in} بدلاً من {player_out}"),
        "half_time": ("نهاية الشوط الأول: {home} {sh}-{sa} {away}", "{home} {sh}-{sa} {away} بين الشوطين",
                      "التسديدات {shots_home}-{shots_away} · xG {xg_home}-{xg_away} · الاستحواذ {poss}%-{poss_away}%"),
        "full_time": ("نهاية المباراة: {home} {sh}-{sa} {away}", "النتيجة النهائية: {home} {sh}-{sa} {away}",
                      "التسديدات {shots_home}-{shots_away} · xG {xg_home}-{xg_away} · الاستحواذ {poss}%-{poss_away}%"),
        "momentum_shift": ("أفضلية · {team}", "{team} يسيطر على المباراة الآن",
                           "آخر {wmin} دقائق: {wshots} تسديدات، {wxg} xG، ميل الملعب {tilt}%"),
        "pressure_spell": ("ضغط · {team}", "{team} يحاصر {opp} في مناطقه",
                           "آخر {wmin} دقائق: ميل الملعب {tilt}%، {wshots} تسديدات، {tempo} تمريرة/د"),
    },
}

LABELS: dict[str, dict[str, str]] = {
    "en": {"brace": "BRACE", "hat_trick": "HAT-TRICK", "goals": "ON FIRE", "saved": "saved",
           "off_target": "off target", "blocked": "blocked", "woodwork": "woodwork"},
    "es": {"brace": "DOBLETE", "hat_trick": "TRIPLETE", "goals": "IMPARABLE", "saved": "parada",
           "off_target": "desviado", "blocked": "bloqueado", "woodwork": "al palo"},
    "ar": {"brace": "ثنائية", "hat_trick": "هاتريك", "goals": "لا يتوقف", "saved": "تصدٍّ",
           "off_target": "خارج المرمى", "blocked": "صدّها الدفاع", "woodwork": "القائم"},
}


def display_minute(m: Moment) -> str:
    """Broadcast-style minute: 45+3 rather than 48 in first-half stoppage time."""
    minute = m.clock_ms // 60_000 + 1
    if m.period == 1 and minute > 45:
        return f"45+{minute - 45}"
    if m.period == 2 and minute > 90:
        return f"90+{minute - 90}"
    return str(minute)


def _num(v: Any) -> str:
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".") if v < 10 else f"{v:.0f}"
    return str(v)


def template_context(m: Moment, names: Names, language: Language) -> dict[str, str]:
    f = {fact.label: fact.value for fact in m.facts}
    team = m.team_id
    opp = names.away_id if team == names.home_id else names.home_id if team else None
    labels = LABELS[language]
    sh = f.get("score_home")
    sa = f.get("score_away")
    poss = f.get("possession_home_pct")
    ctx: dict[str, Any] = {
        "home": names.club(names.home_id), "away": names.club(names.away_id),
        "team": names.club(team), "opp": names.club(opp),
        "player": names.player(m.player_id), "minute": display_minute(m),
        "sh": sh, "sa": sa,
        "xg": f.get("shot_xg"), "dist": f.get("shot_distance_m"), "speed": f.get("shot_speed_kmh"),
        "tshots": f.get("team_shots"), "txg": f.get("team_xg"),
        "pg": f.get("player_goals"), "milestone": labels.get(str(f.get("milestone")), ""),
        "outcome": labels.get(str(f.get("outcome")), f.get("outcome")),
        "remaining": f.get("players_remaining"),
        "difficulty": f.get("pass_difficulty"), "pdist": f.get("pass_distance_m"),
        "player_in": names.player(f.get("player_in")), "player_out": names.player(f.get("player_out")),
        "shots_home": f.get("shots_home"), "shots_away": f.get("shots_away"),
        "xg_home": f.get("xg_home"), "xg_away": f.get("xg_away"),
        "poss": round(poss) if poss is not None else None,
        "poss_away": round(100 - poss) if poss is not None else None,
        "wmin": f.get("window_minutes"), "wshots": f.get("window_shots"), "wxg": f.get("window_xg"),
        "tilt": round(100 * f["field_tilt"]) if "field_tilt" in f else None,
        "tempo": f.get("tempo_passes_per_min"),
    }
    return {k: _num(v) if v is not None else "" for k, v in ctx.items()}


def overlay_id(m: Moment, a: Audience) -> str:
    return f"{m.id}:{a.key}"


def fast_overlay(m: Moment, a: Audience, names: Names) -> Overlay:
    """Deterministic, instantly available overlay built only from the moment's facts."""
    headline_t, fan_t, analyst_t = TEMPLATES[a.language][m.kind]
    ctx = template_context(m, names, a.language)
    duration = DURATION_MS.get(m.kind, DEFAULT_DURATION_MS)
    return Overlay(
        id=overlay_id(m, a), match_id=m.id.rsplit("-mo", 1)[0], moment_id=m.id, audience=a.key,
        kind=m.kind, priority=m.severity, slot=SLOTS[m.kind],
        clock_in_ms=m.clock_ms, clock_out_ms=m.clock_ms + duration, elapsed_in_ms=m.elapsed_ms,
        headline=headline_t.format(**ctx).strip(), body=(analyst_t if a.mode == "analyst" else fan_t).format(**ctx).strip(),
        language=a.language, direction="rtl" if a.language == "ar" else "ltr",
        source="template", version=1, evidence=[fact.id for fact in m.facts],
        data={fact.label: fact.value for fact in m.facts},
    )


# ---------- validator ----------

def validate(o: Overlay, m: Moment, now_elapsed_ms: int, stale_ms: int = STALE_MS) -> Overlay:
    """Raise ValidationError unless the overlay is safe to put on screen."""
    if o.moment_id != m.id:
        raise ValidationError("moment mismatch")
    fact_ids = {f.id for f in m.facts}
    if not o.evidence or not set(o.evidence) <= fact_ids:
        raise ValidationError("evidence missing or not from this moment")
    if not o.headline.strip() or len(o.headline) > MAX_HEADLINE:
        raise ValidationError("headline empty or too long")
    if len(o.body) > MAX_BODY:
        raise ValidationError("body too long")
    if o.clock_out_ms <= o.clock_in_ms:
        raise ValidationError("timing: out before in")
    if o.source == "ai" and now_elapsed_ms - m.elapsed_ms > stale_ms:
        raise ValidationError("stale: AI result arrived too late")
    return o


# ---------- scheduler ----------

class Scheduler:
    """Decides what one audience sees: at most `max_on_screen` overlays, one per slot,
    highest priority first. Newer versions of an overlay replace older ones in place."""

    def __init__(self, max_on_screen: int = 2, max_queue_wait_ms: int = 10_000):
        self.max_on_screen = max_on_screen
        self.max_queue_wait_ms = max_queue_wait_ms
        self._showing: dict[str, Overlay] = {}
        self._ends: dict[str, int] = {}
        self._queue: dict[str, tuple[Overlay, int]] = {}

    @staticmethod
    def _duration(o: Overlay) -> int:
        return o.clock_out_ms - o.clock_in_ms

    def offer(self, o: Overlay, now: int) -> None:
        current = self._showing.get(o.id)
        if current is not None:
            if o.version > current.version:
                out = max(current.clock_out_ms, o.clock_out_ms)
                self._showing[o.id] = o.model_copy(update={
                    "slot": current.slot, "clock_in_ms": current.clock_in_ms, "clock_out_ms": out,
                    "elapsed_in_ms": current.elapsed_in_ms,
                })
                self._ends[o.id] = current.elapsed_in_ms + out - current.clock_in_ms
            return
        queued = self._queue.get(o.id)
        if queued is not None and o.version <= queued[0].version:
            return
        self._queue[o.id] = (o, queued[1] if queued else now)
        self._fill(now)

    def _show(self, o: Overlay, now: int) -> None:
        shift = now - o.elapsed_in_ms
        shown = o.model_copy(update={
            "elapsed_in_ms": now, "clock_in_ms": o.clock_in_ms + shift, "clock_out_ms": o.clock_out_ms + shift,
        })
        self._showing[o.id] = shown
        self._ends[o.id] = now + self._duration(o)

    def _evict(self, oid: str) -> None:
        self._showing.pop(oid, None)
        self._ends.pop(oid, None)

    def _fill(self, now: int) -> None:
        for oid, (o, offered) in sorted(self._queue.items(), key=lambda kv: -kv[1][0].priority):
            occupant = next((s for s in self._showing.values() if s.slot == o.slot), None)
            if occupant is not None:
                if o.priority <= occupant.priority:
                    continue
                self._evict(occupant.id)
            elif len(self._showing) >= self.max_on_screen:
                lowest = min(self._showing.values(), key=lambda s: s.priority)
                if o.priority <= lowest.priority:
                    continue
                self._evict(lowest.id)
            del self._queue[oid]
            self._show(o, now)

    def on_screen(self, now: int) -> list[Overlay]:
        for oid in [oid for oid, end in self._ends.items() if end <= now]:
            self._evict(oid)
        for oid in [oid for oid, (_, offered) in self._queue.items() if now - offered > self.max_queue_wait_ms]:
            del self._queue[oid]
        self._fill(now)
        return sorted(self._showing.values(), key=lambda s: -s.priority)
