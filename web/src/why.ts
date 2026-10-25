// F-7: "Why?" in plain words for fans. Built only from the moment's own facts (no AI), so it is instant
// and every number is one the statistics engine produced. Chance quality (xG) becomes everyday odds.
import { cardReasonText } from './cardReasons'
import { CATALOGUES, fill, fromCatalogues, plural, type CataloguedLanguage } from './locales'
import type { Language, Overlay } from './types'

/** "1 in 8" style odds for a scoring chance. */
export function odds(xg: number): { n: number; outOf: number } {
  if (xg >= 0.5) return { n: Math.round(xg * 10), outOf: 10 }
  return { n: 1, outOf: Math.max(2, Math.round(1 / Math.max(xg, 0.01))) }
}

const PENALTY_XG = 0.78  // engine.PENALTY_XG

interface Words {
  chance: (dist: string, n: number, outOf: number) => string
  penalty: (n: number, outOf: number) => string
  ifScored: (score: string) => string
  outcome: Record<string, string>
  goal: Record<string, (team: string, score: string) => string>
  setPiece: Record<string, string>
  brace: (player: string, n: number) => string
  speed: (kmh: number) => string
  yellow: (player: string) => string
  red: (team: string, left: number) => string
  pass: (dist: string) => string
  shots: (team: string, n: number, mins: number) => string
  territory: (team: string, opp: string) => string
  goalsInSpell: (n: number) => string
  sub: (on: string, off: string) => string
  halfShots: (home: string, away: string, sh: number, sa: number) => string
  betterChances: (team: string) => string
  evenChances: string
  moreBall: (team: string) => string
}

const HAND_WRITTEN: Record<'en' | 'es' | 'ar', Words> = {
  en: {
    chance: (d, n, o) => `From ${d} m out, chances like this go in about ${n} ${n === 1 ? 'time' : 'times'} in ${o}.`,
    penalty: (n, o) => `Penalties are scored about ${n} times in ${o}.`,
    ifScored: s => `A goal would have made it ${s}.`,
    outcome: { saved: 'The keeper kept it out.', woodwork: 'It hit the frame of the goal.', off_target: 'It went wide.', blocked: 'A defender got in the way.' },
    goal: {
      takes_lead: t => `It puts ${t} ahead.`, equaliser: (_, s) => `It levels the game at ${s}.`,
      extends_lead: t => `It gives ${t} a bigger cushion.`, pulls_one_back: t => `It gets ${t} back in the game.`,
    },
    setPiece: { corner: 'It came from a corner.', penalty: 'It came from the penalty spot.' },
    brace: (p, n) => `That's ${n} goals today for ${p}.`,
    speed: k => `It was struck at ${k} km/h.`,
    yellow: p => `${p} is on a yellow: another one means a red card.`,
    red: (t, n) => `${t} play the rest of the match with ${n} players.`,
    pass: d => `A ${d} m pass, one of the hardest kinds to pull off.`,
    shots: (t, n, m) => `${t} had ${n} ${n === 1 ? 'shot' : 'shots'} in the last ${m} minutes.`,
    territory: (t, o) => `Most of the play was in ${o}'s half, so ${t} kept them pinned back.`,
    goalsInSpell: n => `They scored ${n} ${n === 1 ? 'goal' : 'goals'} in that spell.`,
    sub: (on, off) => `${on} comes on for ${off}.`,
    halfShots: (h, a, sh, sa) => `Shots: ${h} ${sh}, ${a} ${sa}.`,
    betterChances: t => `${t} created the better chances.`,
    evenChances: 'The chances were fairly even.',
    moreBall: t => `${t} had more of the ball.`,
  },
  es: {
    chance: (d, n, o) => `Desde ${d} m, ocasiones así acaban en gol ${n} ${n === 1 ? 'vez' : 'veces'} de cada ${o}.`,
    penalty: (n, o) => `Los penaltis acaban en gol unas ${n} veces de cada ${o}.`,
    ifScored: s => `Un gol habría puesto el ${s}.`,
    outcome: { saved: 'El portero lo evitó.', woodwork: 'El balón dio en la madera.', off_target: 'Se fue fuera.', blocked: 'Un defensor lo bloqueó.' },
    goal: {
      takes_lead: t => `Pone por delante al ${t}.`, equaliser: (_, s) => `Iguala el partido: ${s}.`,
      extends_lead: t => `El ${t} amplía su ventaja.`, pulls_one_back: t => `El ${t} vuelve a meterse en el partido.`,
    },
    setPiece: { corner: 'Llegó tras un córner.', penalty: 'Llegó desde el punto de penalti.' },
    brace: (p, n) => `${p} lleva ${n} goles hoy.`,
    speed: k => `Salió a ${k} km/h.`,
    yellow: p => `${p} tiene amarilla: otra significa la roja.`,
    red: (t, n) => `El ${t} jugará el resto del partido con ${n}.`,
    pass: d => `Un pase de ${d} m, de los más difíciles de completar.`,
    shots: (t, n, m) => `El ${t} hizo ${n} ${n === 1 ? 'tiro' : 'tiros'} en los últimos ${m} minutos.`,
    territory: (t, o) => `Casi todo el juego fue en campo del ${o}: el ${t} lo encerró.`,
    goalsInSpell: n => `Marcaron ${n} ${n === 1 ? 'gol' : 'goles'} en esa fase.`,
    sub: (on, off) => `Entra ${on} por ${off}.`,
    halfShots: (h, a, sh, sa) => `Tiros: ${h} ${sh}, ${a} ${sa}.`,
    betterChances: t => `El ${t} generó las mejores ocasiones.`,
    evenChances: 'Las ocasiones estuvieron bastante igualadas.',
    moreBall: t => `El ${t} tuvo más el balón.`,
  },
  ar: {
    chance: (d, n, o) => `من مسافة ${d} م، تنتهي فرص كهذه بهدف نحو ${n} من كل ${o} مرات.`,
    penalty: (n, o) => `تُسجَّل ركلات الجزاء نحو ${n} من كل ${o} مرات.`,
    ifScored: s => `لو سُجّل الهدف لأصبحت النتيجة ${s}.`,
    outcome: { saved: 'تصدى لها الحارس.', woodwork: 'ارتطمت الكرة بالقائم.', off_target: 'ذهبت خارج المرمى.', blocked: 'اعترضها أحد المدافعين.' },
    goal: {
      takes_lead: t => `هدف يضع ${t} في المقدمة.`, equaliser: (_, s) => `هدف يعيد التعادل: ${s}.`,
      extends_lead: t => `هدف يوسع فارق ${t}.`, pulls_one_back: t => `هدف يعيد ${t} إلى أجواء المباراة.`,
    },
    setPiece: { corner: 'جاء من ركلة ركنية.', penalty: 'جاء من ركلة جزاء.' },
    brace: (p, n) => `أهداف ${p} اليوم: ${n}.`,
    speed: k => `سُددت بسرعة ${k} كم/س.`,
    yellow: p => `${p} لديه إنذار: إنذار آخر يعني الطرد.`,
    red: (t, n) => `${t} يكمل المباراة بـ${n} لاعبين.`,
    pass: d => `تمريرة لمسافة ${d} م، من أصعب التمريرات.`,
    shots: (t, n, m) => `تسديدات ${t} في آخر ${m} دقائق: ${n}.`,
    territory: (t, o) => `دار معظم اللعب في نصف ملعب ${o}، فحاصره ${t}.`,
    goalsInSpell: n => `أهدافهم في تلك الفترة: ${n}.`,
    sub: (on, off) => `${on} يدخل بدلاً من ${off}.`,
    halfShots: (h, a, sh, sa) => `التسديدات: ${h} ${sh}، ${a} ${sa}.`,
    betterChances: t => `صنع ${t} الفرص الأخطر.`,
    evenChances: 'كانت الفرص متقاربة.',
    moreBall: t => `استحوذ ${t} على الكرة أكثر.`,
  },
}

/** DK-12: a catalogued language's templates as the same functions. */
function fromTemplates(lang: CataloguedLanguage): Words {
  const c = CATALOGUES[lang].why
  const n = (p: typeof c.chance, count: number, vars: Record<string, string | number>) => fill(plural(p, count, lang), vars)
  return {
    chance: (d, k, o) => n(c.chance, k, { d, n: k, o }),
    penalty: (k, o) => n(c.penalty, k, { n: k, o }),
    ifScored: s => fill(c.ifScored, { s }),
    outcome: c.outcome,
    goal: Object.fromEntries(Object.entries(c.goal).map(([ctx, t]) => [ctx, (team: string, s: string) => fill(t, { t: team, s })])),
    setPiece: c.setPiece,
    brace: (p, k) => n(c.brace, k, { p, n: k }),
    speed: k => fill(c.speed, { k }),
    yellow: p => fill(c.yellow, { p }),
    red: (t, k) => n(c.red, k, { t, n: k }),
    pass: d => fill(c.pass, { d }),
    shots: (t, k, m) => n(c.shots, k, { t, n: k, m }),
    territory: (t, o) => fill(c.territory, { t, o }),
    goalsInSpell: k => n(c.goalsInSpell, k, { n: k }),
    sub: (on, off) => fill(c.sub, { on, off }),
    halfShots: (h, a, sh, sa) => fill(c.halfShots, { h, a, sh, sa }),
    betterChances: t => fill(c.betterChances, { t }),
    evenChances: c.evenChances,
    moreBall: t => fill(c.moreBall, { t }),
  }
}

const W: Record<Language, Words> = { ...HAND_WRITTEN, ...fromCatalogues((_, lang) => fromTemplates(lang)) }

const num = (v: unknown) => (typeof v === 'number' ? v : Number(v))
const dist = (v: unknown) => String(Math.round(num(v)))

/** 1-3 plain sentences explaining a moment. Empty when there is nothing to add. */
export function whyLines(o: Overlay, names: Record<string, string>, homeId: string, awayId: string, lang: Language): string[] {
  const w = W[lang]
  const d = o.data
  const team = o.team_id ? names[o.team_id] ?? o.team_id : ''
  const opp = o.team_id === homeId ? names[awayId] ?? awayId : names[homeId] ?? homeId
  const player = o.player_id ? names[o.player_id] ?? o.player_id : ''
  const has = (k: string) => d[k] !== undefined && d[k] !== null
  const out: string[] = []
  const chance = () => {
    if (has('shot_xg') && has('shot_distance_m')) {
      const { n, outOf } = odds(num(d.shot_xg))
      out.push(w.chance(dist(d.shot_distance_m), n, outOf))
    }
  }
  switch (o.kind) {
    case 'goal': {
      const ctx = String(d.goal_context ?? '')
      if (w.goal[ctx]) out.push(w.goal[ctx](team, `${d.score_home}-${d.score_away}`))
      if (d.set_piece === 'penalty') out.push(w.setPiece.penalty)
      else {
        chance()
        if (d.set_piece === 'corner') out.push(w.setPiece.corner)
      }
      break
    }
    case 'big_chance':
    case 'woodwork':
    case 'shot_on_target':
    case 'rocket_shot':
      if (o.kind === 'rocket_shot' && has('shot_speed_kmh')) out.push(w.speed(Math.round(num(d.shot_speed_kmh))))
      if (d.set_piece === 'penalty') {
        const { n, outOf } = odds(PENALTY_XG)
        out.push(w.penalty(n, outOf))
      } else chance()
      if (has('score_home_if_scored')) out.push(w.ifScored(`${d.score_home_if_scored}-${d.score_away_if_scored}`))
      else if (w.outcome[String(d.outcome)]) out.push(w.outcome[String(d.outcome)])
      break
    case 'penalty': {
      const { n, outOf } = odds(PENALTY_XG)
      out.push(w.penalty(n, outOf))
      break
    }
    case 'milestone':
      if (has('player_goals')) out.push(w.brace(player, num(d.player_goals)))
      break
    case 'yellow_card':
    case 'red_card': {
      const reason = cardReasonText(String(d.card_reason ?? ''), has('fouled_player') ? names[String(d.fouled_player)] ?? null : null, lang,
        d.card === 'second_yellow')
      if (reason) out.push(`${reason}.`)
      if (o.kind === 'yellow_card') out.push(w.yellow(player))
      else if (has('players_remaining')) out.push(w.red(team, num(d.players_remaining)))
      break
    }
    case 'great_pass':
      if (has('pass_distance_m')) out.push(w.pass(dist(d.pass_distance_m)))
      break
    case 'momentum_shift':
    case 'pressure_spell':
      if (has('window_shots') && has('window_minutes')) out.push(w.shots(team, num(d.window_shots), num(d.window_minutes)))
      if (num(d.field_tilt) >= 0.6) out.push(w.territory(team, opp))
      if (num(d.goals_in_spell) > 0) out.push(w.goalsInSpell(num(d.goals_in_spell)))
      break
    case 'substitution':
      if (has('player_in') && has('player_out')) out.push(w.sub(names[String(d.player_in)] ?? '', names[String(d.player_out)] ?? ''))
      break
    case 'half_time':
    case 'full_time': {
      const home = names[homeId] ?? homeId
      const away = names[awayId] ?? awayId
      if (has('shots_home')) out.push(w.halfShots(home, away, num(d.shots_home), num(d.shots_away)))
      if (has('xg_home')) {
        const diff = num(d.xg_home) - num(d.xg_away)
        out.push(Math.abs(diff) < 0.5 ? w.evenChances : w.betterChances(diff > 0 ? home : away))
      }
      const poss = num(d.possession_home_pct)
      if (poss >= 55 || poss <= 45) out.push(w.moreBall(poss >= 55 ? home : away))
      break
    }
  }
  return out.slice(0, 3)
}
