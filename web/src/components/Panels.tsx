import { useState } from 'react'
import { KIND_LABELS, t, type StringKey } from '../i18n'
import type { State } from '../state'
import type { Hello, Language, Overlay, TeamStats } from '../types'
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

export function Stats({ state, colors, lang }: { state: State; colors: Record<string, string>; lang: Language }) {
  const hello = state.hello
  if (!state.stats || !hello) return <p className="empty">{t(lang, 'waiting')}</p>
  const { home, away, chaos } = state.stats
  const c: [string, string] = [colors[hello.home.id], colors[hello.away.id]]
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
      {rows.map(([k, get, fmt]) => (
        <StatRow key={k} label={t(lang, k)} home={get(home)} away={get(away)} fmt={fmt} colors={c} />
      ))}
      <h3 className="section-title" style={{ marginTop: 14 }}>{t(lang, 'last10')}</h3>
      {windowRows.map(([k, get, fmt]) => (
        <StatRow key={k} label={t(lang, k)} home={get(home)} away={get(away)} fmt={fmt} colors={c} />
      ))}
      <div className="stat-row">
        <span className="val">{t(lang, 'control')}</span>
        <div className="stat-mid">
          <span className="label">{t(lang, 'chaos')}</span>
          <div className="bars" aria-label={`${Math.round(chaos * 100)}%`}>
            <span style={{ width: `${100 - chaos * 100}%`, background: 'var(--accent)' }} />
            <span style={{ width: `${chaos * 100}%`, background: 'var(--danger)' }} />
          </div>
        </div>
        <span className="val away">{t(lang, 'chaosLabel')}</span>
      </div>
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
