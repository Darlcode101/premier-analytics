import { useState } from 'react'
import { localDigits } from '../digits'
import { t } from '../i18n'
import type { State } from '../state'
import type { Language, TeamStats } from '../types'
import { explainAttack, linkedMoments } from '../explain'

/** Per-minute bars towards the team on top, with the reasons for any bar you tap. */
export function AttackMomentumChart({ state, colors, names, lang, topTeam }: {
  state: State; colors: Record<string, string>; names: Record<string, string>; lang: Language; topTeam: string | null
}) {
  const [picked, setPicked] = useState<number | null>(null)
  const h = state.hello
  const series = state.attack
  if (!h || !series.length) return null
  const top = topTeam ?? h.home.id
  const bottom = top === h.home.id ? h.away.id : h.home.id
  const sign = top === h.home.id ? 1 : -1
  const n = Math.max(96, series.length)
  const W = n * 3
  const H = 84
  const mid = H / 2
  const momentMinutes = new Set(
    state.feed.filter(o => o.kind === 'momentum_shift' || o.kind === 'pressure_spell').map(o => Math.floor(o.elapsed_in_ms / 60_000)),
  )
  const halftime = series.findIndex((p, i) => i > 0 && p.label === '46' && series[i - 1].label.startsWith('45'))
  const selected = series[picked ?? series.length - 1]
  const why = explainAttack(selected, h.home.id, h.away.id, names, lang)
  const moments = linkedMoments(state.feed, selected)
  const label = (m: number) => series[m]?.label ?? String(m + 1)
  return (
    <section className="attack-chart" data-testid="attack-momentum">
      <h3 className="section-title">{t(lang, 'attackMomentum')}</h3>
      <div className="attack-legend" dir="ltr">
        <span><i style={{ background: colors[top] }} />{names[top]}</span>
        <span><i style={{ background: colors[bottom] }} />{names[bottom]}</span>
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="group" aria-label={t(lang, 'attackMomentum')}>
        <line x1={0} x2={W} y1={mid} y2={mid} className="axis" />
        {halftime > 0 && <line x1={halftime * 3} x2={halftime * 3} y1={4} y2={H - 4} className="ht" />}
        {series.map(p => {
          const v = p.value * sign
          const hgt = Math.max(Math.abs(v) * (mid - 6), v === 0 ? 0 : 1)
          const isSel = p.minute === selected.minute
          return (
            <g key={p.minute} onClick={() => setPicked(p.minute)} className={`bar${isSel ? ' sel' : ''}`}
              data-testid="attack-bar" role="button" aria-label={`${label(p.minute)}'`}>
              <rect x={p.minute * 3} y={0} width={3} height={H} fill="transparent" />
              <rect x={p.minute * 3 + 0.4} y={v >= 0 ? mid - hgt : mid} width={2.2} height={hgt} rx={0.6}
                fill={v >= 0 ? colors[top] : colors[bottom]} opacity={isSel ? 1 : 0.8} />
              {momentMinutes.has(p.minute) && <circle cx={p.minute * 3 + 1.5} cy={v >= 0 ? mid - hgt - 3 : mid + hgt + 3} r={1.3} className="moment-dot" />}
            </g>
          )
        })}
      </svg>
      <div className="attack-why" data-testid="attack-why">
        <div className="attack-why-head">
          <b>{localDigits(`${label(selected.window[0])}'–${label(selected.window[1])}'`, lang)}</b>
          <span style={{ color: why.leader ? colors[why.leader] : undefined }} className="leader">{why.headline}</span>
        </div>
        {why.reasons.length > 0 && <ul>{why.reasons.map(r => <li key={r}>{localDigits(r, lang)}</li>)}</ul>}
        {why.leader && why.opponentReasons.length > 0 && (
          <p className="opp">{names[why.leader === h.home.id ? h.away.id : h.home.id]}: {localDigits(why.opponentReasons.join(' · '), lang)}</p>
        )}
        {moments.map(o => (
          <div key={o.id} className="attack-ai" dir={o.direction}>
            {o.source === 'ai' && <span className="ai-tag" data-testid="attack-ai-tag">AI</span>} <strong>{localDigits(o.headline, lang)}</strong>
            <p>{localDigits(o.body, lang)}</p>
          </div>
        ))}
        {picked === null && <p className="hint">{t(lang, 'tapBar')}</p>}
      </div>
    </section>
  )
}

export type Period = 'match' | 'first_half' | 'second_half'

/** A team's figures for the whole match or one half (halves carry the same fields). */
export function forPeriod(s: TeamStats, period: Period): TeamStats {
  const half = period === 'match' ? null : s[period]
  return half ? { ...s, ...half } : s
}

export function HalfSwitch({ period, setPeriod, state, labels, className = 'half-switch' }: {
  period: Period; setPeriod: (p: Period) => void; state: State; labels: [string, string, string]; className?: string
}) {
  const secondReady = Boolean(state.stats?.home.second_half)
  return (
    <div className={className} role="group" data-testid="half-switch">
      {(['match', 'first_half', 'second_half'] as const).map((p, i) => (
        <button key={p} aria-pressed={period === p} disabled={p === 'second_half' && !secondReady} onClick={() => setPeriod(p)}>
          {labels[i]}
        </button>
      ))}
    </div>
  )
}

export function Agents({ state, lang }: { state: State; lang: Language }) {
  const { counts, trace } = state
  return (
    <div data-testid="agents">
      <p className="pipeline-note">{t(lang, 'pipeline')}</p>
      <div className="trace-summary">
        <div><strong className="outcome-published">{counts.published}</strong><span>{t(lang, 'published')}</span></div>
        <div><strong className="outcome-rejected">{counts.rejected}</strong><span>{t(lang, 'rejected')}</span></div>
        <div><strong className="outcome-stale">{counts.stale}</strong><span>{t(lang, 'stale')}</span></div>
        <div><strong className="outcome-error">{counts.error}</strong><span>{t(lang, 'errors')}</span></div>
      </div>
      {!trace.length && <p className="empty">{t(lang, 'emptyTrace')}</p>}
      {trace.slice(0, 80).map((e, i) => (
        <div className="trace-item" key={i} dir="ltr">
          <span className="agent">{e.agent}</span>
          <span className={`outcome-${e.outcome}`}>{e.outcome}{e.model ? ` · ${e.model.split('|')[0]}` : ''}</span>
          <span style={{ color: 'var(--text-faint)' }}>{e.ms ? `${e.ms} ms` : ''}</span>
          {e.detail && <span className="detail">{e.detail.slice(0, 160)}</span>}
        </div>
      ))}
    </div>
  )
}

export function Recaps({ state, lang }: { state: State; lang: Language }) {
  const items = (['full_time', 'half_time'] as const).map(k => state.recaps[k]).filter(Boolean)
  if (!items.length) return <p className="empty">{t(lang, 'emptyRecap')}</p>
  return (
    <div data-testid="recaps">
      {items.map(r => r && (
        <article className="recap-card" key={r.kind} dir={lang === 'ar' ? 'rtl' : 'ltr'}>
          <span className="chip">{r.kind === 'full_time' ? t(lang, 'fullTime') : t(lang, 'halfTime')}</span>
          <h3>{localDigits(r.headline, lang)}</h3>
          <p>{localDigits(r.summary, lang)}</p>
          {r.key_points.length > 0 && <ul>{r.key_points.map((p, i) => <li key={i}>{localDigits(p, lang)}</li>)}</ul>}
        </article>
      ))}
    </div>
  )
}
