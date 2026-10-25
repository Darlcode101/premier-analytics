// Plain-language reasons behind an attack-momentum bar. Built only from the bar's own counts,
// so every number shown is one the statistics engine produced.
import { fill, fromCatalogues, plural } from './locales'
import type { AttackCounts, AttackPoint, Language, Overlay } from './types'

const EVEN = 0.15

interface Words {
  onTop: (team: string) => string
  even: string
  quiet: string
  shots: (n: number, xg: string) => string
  passes: (n: number) => string
  regains: (n: number) => string
}

const HAND_WRITTEN: Record<'en' | 'es' | 'ar', Words> = {
  en: {
    onTop: team => `${team} on top`, even: 'Evenly balanced', quiet: 'Quiet spell',
    shots: (n, xg) => `${n} ${n === 1 ? 'shot' : 'shots'} (${xg} xG)`,
    passes: n => `${n} ${n === 1 ? 'pass' : 'passes'} into the final third`,
    regains: n => `won the ball ${n} ${n === 1 ? 'time' : 'times'} in the opponent's half`,
  },
  es: {
    onTop: team => `${team} domina`, even: 'Partido equilibrado', quiet: 'Fase tranquila',
    shots: (n, xg) => `${n} ${n === 1 ? 'tiro' : 'tiros'} (${xg} xG)`,
    passes: n => `${n} ${n === 1 ? 'pase' : 'pases'} al último tercio`,
    regains: n => `recuperó el balón ${n} ${n === 1 ? 'vez' : 'veces'} en campo rival`,
  },
  ar: {
    onTop: team => `${team} يسيطر`, even: 'متكافئ', quiet: 'فترة هادئة',
    shots: (n, xg) => `${n} تسديدة (${xg} xG)`,
    passes: n => `${n} تمريرة إلى الثلث الأخير`,
    regains: n => `استعاد الكرة ${n} مرات في نصف الخصم`,
  },
}

// DK-12: the catalogued languages.
const TEXT: Record<Language, Words> = {
  ...HAND_WRITTEN,
  ...fromCatalogues(({ explain: e }, lang) => ({
    onTop: (team: string) => fill(e.onTop, { team }), even: e.even, quiet: e.quiet,
    shots: (n: number, xg: string) => fill(plural(e.shots, n, lang), { n, xg }),
    passes: (n: number) => fill(plural(e.passes, n, lang), { n }),
    regains: (n: number) => fill(plural(e.regains, n, lang), { n }),
  })),
}

function reasons(c: AttackCounts, lang: Language): string[] {
  const t = TEXT[lang]
  const out: string[] = []
  if (c.shots) out.push(t.shots(c.shots, String(Math.round(c.xg * 100) / 100)))
  if (c.final_third_passes) out.push(t.passes(c.final_third_passes))
  if (c.high_regains) out.push(t.regains(c.high_regains))
  return out
}

export interface AttackExplanation {
  leader: string | null
  headline: string
  reasons: string[]          // why the leader is on top
  opponentReasons: string[]  // what the other side managed
}

export function explainAttack(p: AttackPoint, homeId: string, awayId: string,
  names: Record<string, string>, lang: Language): AttackExplanation {
  const t = TEXT[lang]
  const home = reasons(p.home, lang)
  const away = reasons(p.away, lang)
  if (!home.length && !away.length) return { leader: null, headline: t.quiet, reasons: [], opponentReasons: [] }
  if (Math.abs(p.value) < EVEN) return { leader: null, headline: t.even, reasons: home, opponentReasons: away }
  const homeLeads = p.value > 0
  const leader = homeLeads ? homeId : awayId
  return {
    leader, headline: t.onTop(names[leader] ?? leader),
    reasons: homeLeads ? home : away, opponentReasons: homeLeads ? away : home,
  }
}

/** AI-explained momentum and pressure moments that fall in (or just after) a bar's window. */
export function linkedMoments(feed: Overlay[], p: AttackPoint): Overlay[] {
  return feed
    .filter(o => o.kind === 'momentum_shift' || o.kind === 'pressure_spell')
    .filter(o => {
      const m = Math.floor(o.elapsed_in_ms / 60_000)
      return m >= p.window[0] && m <= p.window[1] + 1
    })
    .sort((a, b) => a.elapsed_in_ms - b.elapsed_in_ms)
}
