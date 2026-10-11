import { useState } from 'react'
import { KIND_LABELS, t, type StringKey } from '../i18n'
import type { State } from '../state'
import type { Hello, Language, Overlay, TeamStats } from '../types'
import { explainAttack, linkedMoments } from '../explain'
import { Evidence } from './Shared'

function FeedItem({ o, color, names, lang }: { o: Overlay; color: string; names: Record<string, string>; lang: Language }) {
  const [open, setOpen] = useState(false)
  return (
    <article className="feed-item" dir={o.direction} data-testid="feed-item">
      <div className="feed-top">
        <span className="minute">{o.minute}'</span>
        <span className="chip" style={{ '--team': color } as React.CSSProperties}>{KIND_LABELS[lang][o.kind] ?? o.kind}</span>
        <span className={`badge ${o.source}`}>{o.source === 'ai' ? `✦ ${t(lang, 'aiUpgraded')}` : t(lang, 'instant')}</span>
        <span style={{ flex: 1 }} />
        <button className="link-btn" onClick={() => setOpen(v => !v)} aria-expanded={open}>{t(lang, 'why')}</button>
      </div>
      <h4>{o.headline}</h4>
      <p>{o.body}</p>
      {open && <Evidence overlay={o} names={names} lang={lang} />}
    </article>
  )
}

export function Feed({ state, colors, names, lang }: {
  state: State; colors: Record<string, string>; names: Record<string, string>; lang: Language
}) {
  if (!state.feed.length) return <p className="empty">{t(lang, 'emptyFeed')}</p>
  return (
    <div>
      {state.feed.map(o => (
        <FeedItem key={o.id} o={o} color={(o.team_id && colors[o.team_id]) || 'var(--text)'} names={names} lang={lang} />
      ))}
    </div>
  )
}

function StatRow({ label, home, away, fmt = String, colors }: {
  label: string; home: number; away: number; fmt?: (v: number) => string; colors: [string, string]
}) {
  const total = home + away
  const share = total > 0 ? (100 * home) / total : 50
  return (
    <div className="stat-row">
      <span className="val">{fmt(home)}</span>
      <div className="stat-mid">
        <span className="label">{label}</span>
        <div className="bars" aria-hidden>
          <span style={{ width: `${share}%`, background: colors[0] }} />
          <span style={{ width: `${100 - share}%`, background: colors[1] }} />
        </div>
      </div>
      <span className="val away">{fmt(away)}</span>
    </div>
  )
}

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
          <b>{label(selected.window[0])}'–{label(selected.window[1])}'</b>
          <span style={{ color: why.leader ? colors[why.leader] : undefined }} className="leader">{why.headline}</span>
        </div>
        {why.reasons.length > 0 && <ul>{why.reasons.map(r => <li key={r}>{r}</li>)}</ul>}
        {why.leader && why.opponentReasons.length > 0 && (
          <p className="opp">{names[why.leader === h.home.id ? h.away.id : h.home.id]}: {why.opponentReasons.join(' · ')}</p>
        )}
        {moments.map(o => (
          <div key={o.id} className="attack-ai" dir={o.direction}>
            {o.source === 'ai' && <span className="ai-tag" data-testid="attack-ai-tag">✦ AI</span>} <strong>{o.headline}</strong>
            <p>{o.body}</p>
          </div>
        ))}
        {picked === null && <p className="hint">{t(lang, 'tapBar')}</p>}
      </div>
    </section>
  )
}

export function Stats({ state, colors, lang, names = {}, topTeam = null }: {
  state: State; colors: Record<string, string>; lang: Language; names?: Record<string, string>; topTeam?: string | null
}) {
  const hello = state.hello
  if (!state.stats || !hello) return <p className="empty">{t(lang, 'waiting')}</p>
  // Same order as the scoreboard: the viewer's pinned club first.
  const flip = topTeam === hello.away.id
  const home = flip ? state.stats.away : state.stats.home
  const away = flip ? state.stats.home : state.stats.away
  const c: [string, string] = flip ? [colors[hello.away.id], colors[hello.home.id]] : [colors[hello.home.id], colors[hello.away.id]]
  const pct = (v: number) => `${Math.round(v)}%`
  const rows: [StringKey, (s: TeamStats) => number, ((v: number) => string)?][] = [
    ['possession', s => s.possession_pct, pct],
    ['shots', s => s.shots],
    ['onTarget', s => s.shots_on_target],
    ['xg', s => s.xg, v => v.toFixed(2)],
    ['passes', s => s.passes],
    ['passAccuracy', s => 100 * s.pass_accuracy, pct],
    ['tacklesWon', s => s.tackles_won],
    ['fouls', s => s.fouls],
    ['cards', s => s.yellow_cards + s.red_cards],
  ]
  const windowRows: [StringKey, (s: TeamStats) => number, ((v: number) => string)?][] = [
    ['fieldTilt', s => 100 * s.window.field_tilt, pct],
    ['shots', s => s.window.shots],
    ['xg', s => s.window.xg, v => v.toFixed(2)],
    ['tempo', s => s.window.tempo, v => v.toFixed(1)],
  ]
  return (
    <div data-testid="stats">
      <AttackMomentumChart state={state} colors={colors} names={names} lang={lang} topTeam={topTeam} />
      <div className="stats-head" dir="ltr">
        <span data-testid="stats-left" style={{ color: c[0] }}>{(flip ? hello.away : hello.home).short_name}</span>
        <span data-testid="stats-right" style={{ color: c[1] }}>{(flip ? hello.home : hello.away).short_name}</span>
      </div>
      {rows.map(([k, get, fmt]) => (
        <StatRow key={k} label={t(lang, k)} home={get(home)} away={get(away)} fmt={fmt} colors={c} />
      ))}
      <h3 className="section-title" style={{ marginTop: 14 }}>{t(lang, 'last10')}</h3>
      {windowRows.map(([k, get, fmt]) => (
        <StatRow key={k} label={t(lang, k)} home={get(home)} away={get(away)} fmt={fmt} colors={c} />
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
          <h3>{r.headline}</h3>
          <p>{r.summary}</p>
          {r.key_points.length > 0 && <ul>{r.key_points.map((p, i) => <li key={i}>{p}</li>)}</ul>}
        </article>
      ))}
    </div>
  )
}

export function Momentum({ state, hello, colors, lang }: {
  state: State; hello: Hello; colors: Record<string, string>; lang: Language
}) {
  const pts = state.momentum
  const W = 100
  const H = 40
  const x = (minute: number) => (Math.min(minute, 96) / 96) * W
  const y = (v: number) => H / 2 - (v * H) / 2
  const line = pts.map((p, i) => `${i ? 'L' : 'M'} ${x(p.minute).toFixed(2)} ${y(p.value).toFixed(2)}`).join(' ')
  const area = pts.length ? `${line} L ${x(pts[pts.length - 1].minute)} ${H / 2} L ${x(pts[0].minute)} ${H / 2} Z` : ''
  return (
    <div className="card momentum">
      <h3 className="section-title">{t(lang, 'momentumChart')}</h3>
      <svg viewBox={`0 0 ${W} ${H}`} preserveAspectRatio="none" role="img"
        aria-label={`${t(lang, 'momentum')}: ${hello.home.short_name} vs ${hello.away.short_name}`}>
        <defs>
          <clipPath id="top"><rect x={0} y={0} width={W} height={H / 2} /></clipPath>
          <clipPath id="bottom"><rect x={0} y={H / 2} width={W} height={H / 2} /></clipPath>
        </defs>
        <line x1={x(45)} y1={0} x2={x(45)} y2={H} stroke="var(--line)" strokeWidth={0.3} />
        <path d={area} fill={colors[hello.home.id]} opacity={0.55} clipPath="url(#top)" />
        <path d={area} fill={colors[hello.away.id]} opacity={0.55} clipPath="url(#bottom)" />
        <line x1={0} y1={H / 2} x2={W} y2={H / 2} stroke="var(--text-faint)" strokeWidth={0.2} />
      </svg>
      <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, color: 'var(--text-faint)' }} dir="ltr">
        <span>0'</span><span>45'</span><span>90'</span>
      </div>
    </div>
  )
}
