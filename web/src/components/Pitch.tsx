import { useState } from 'react'
import { CONTEXT_LABELS, FACT_LABELS, KIND_LABELS, t } from '../i18n'
import type { State } from '../state'
import type { Language, Overlay } from '../types'

const L = 105
const W = 68

function Markings() {
  const line = { stroke: 'var(--pitch-line)', strokeWidth: 0.35, fill: 'none' }
  return (
    <g {...line}>
      <rect x={0} y={0} width={L} height={W} />
      <line x1={L / 2} y1={0} x2={L / 2} y2={W} />
      <circle cx={L / 2} cy={W / 2} r={9.15} />
      <circle cx={L / 2} cy={W / 2} r={0.4} fill="var(--pitch-line)" />
      {[0, 1].map(side => {
        const x = (v: number) => (side === 0 ? v : L - v)
        const dir = side === 0 ? 1 : -1
        return (
          <g key={side}>
            <rect x={side === 0 ? 0 : L - 16.5} y={W / 2 - 20.16} width={16.5} height={40.32} />
            <rect x={side === 0 ? 0 : L - 5.5} y={W / 2 - 9.16} width={5.5} height={18.32} />
            <circle cx={x(11)} cy={W / 2} r={0.4} fill="var(--pitch-line)" />
            <path d={`M ${x(16.5)} ${W / 2 - 7.3} A 9.15 9.15 0 0 ${side === 0 ? 1 : 0} ${x(16.5)} ${W / 2 + 7.3}`} />
            <rect x={side === 0 ? -2 : L} y={W / 2 - 3.66} width={2} height={7.32} strokeWidth={0.5} />
            <line x1={x(0)} y1={W / 2} x2={x(0) - dir * 0.01} y2={W / 2} />
          </g>
        )
      })}
    </g>
  )
}

function display(value: string | number | boolean, label: string, names: Record<string, string>, lang: Language): string {
  if (label === 'goal_context') return CONTEXT_LABELS[lang][String(value)] ?? String(value)
  if (typeof value === 'string') return names[value] ?? value
  if (label === 'field_tilt') return `${Math.round(Number(value) * 100)}%`
  return String(value)
}

export function Evidence({ overlay, names, lang }: { overlay: Overlay; names: Record<string, string>; lang: Language }) {
  return (
    <dl className="evidence" aria-label={t(lang, 'evidence')}>
      {Object.entries(overlay.data).map(([label, value]) => (
        <div key={label} style={{ display: 'contents' }}>
          <dt>{FACT_LABELS[lang][label] ?? label}</dt>
          <dd>{display(value, label, names, lang)}</dd>
        </div>
      ))}
    </dl>
  )
}

function OverlayCard({ o, color, upgraded, names, lang }: {
  o: Overlay; color: string; upgraded: boolean; names: Record<string, string>; lang: Language
}) {
  const [open, setOpen] = useState(false)
  return (
    <div
      className={`ov ${o.slot}${upgraded && o.source === 'ai' ? ' upgraded' : ''}`}
      dir={o.direction}
      style={{ '--team': color } as React.CSSProperties}
      data-testid={`overlay-${o.slot}`}
      key={`${o.id}:${o.version}`}
    >
      <span className="kind">{KIND_LABELS[lang][o.kind] ?? o.kind}</span>
      <div className="headline">{o.headline}</div>
      <div className="body">{o.body}</div>
      <div className="meta">
        <span className={`badge ${o.source}`}>{o.source === 'ai' ? `✦ ${t(lang, 'aiUpgraded')}` : t(lang, 'instant')}</span>
        <button className="link-btn" onClick={() => setOpen(v => !v)} aria-expanded={open}>{t(lang, 'why')}</button>
      </div>
      {open && <Evidence overlay={o} names={names} lang={lang} />}
    </div>
  )
}

export function Pitch({ state, colors, names, lang }: {
  state: State; colors: Record<string, string>; names: Record<string, string>; lang: Language
}) {
  const { trail, ball, screen } = state
  return (
    <div className="stage" data-testid="pitch">
      <svg viewBox={`-4 -4 ${L + 8} ${W + 8}`} role="img" aria-label="Pitch with live ball position">
        <rect x={-4} y={-4} width={L + 8} height={W + 8} fill="var(--pitch-1)" />
        {Array.from({ length: 10 }, (_, i) => (
          <rect key={i} x={(i * L) / 10} y={0} width={L / 10} height={W} fill={i % 2 ? 'var(--pitch-2)' : 'var(--pitch-1)'} />
        ))}
        <Markings />
        {trail.map((e, i) => {
          const opacity = 0.15 + (0.75 * (i + 1)) / trail.length
          const color = (e.team_id && colors[e.team_id]) || '#fff'
          if (e.end_x === null || e.end_y === null) {
            return <circle key={e.seq} cx={e.x} cy={e.y} r={0.7} fill={color} opacity={opacity} />
          }
          const shot = e.kind === 'shot'
          return (
            <line key={e.seq} x1={e.x} y1={e.y} x2={e.end_x} y2={e.end_y} stroke={color}
              strokeWidth={shot ? 0.7 : 0.4} strokeDasharray={e.outcome === 'complete' || shot ? undefined : '1 1'}
              opacity={opacity} strokeLinecap="round" />
          )
        })}
        {ball && (
          <g style={{ transform: `translate(${ball.x}px, ${ball.y}px)`, transition: 'transform .5s ease-out' }}>
            <circle r={1.6} fill="#fff" opacity={0.25} />
            <circle r={0.9} fill="#fff" stroke="#111" strokeWidth={0.15} />
          </g>
        )}
      </svg>
      <div className="overlay-layer" aria-live="polite">
        {screen.map(o => (
          <OverlayCard key={o.id} o={o} color={(o.team_id && colors[o.team_id]) || 'var(--accent)'}
            upgraded={state.upgraded.has(o.id)} names={names} lang={lang} />
        ))}
      </div>
    </div>
  )
}
