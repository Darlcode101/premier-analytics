import { useEffect, useRef } from 'react'
import { ballAt, emptyPath, planEvent, type BallPath } from '../ballPath'
import { localDigits } from '../digits'
import { cardReasonText } from '../cardReasons'
import { CONTEXT_LABELS, FACT_LABELS, t } from '../i18n'
import type { State } from '../state'
import type { Language, Overlay } from '../types'
import { attacksRight, describeZone } from '../zones'

export function KindIcon({ kind, size = 16 }: { kind: string; size?: number }) {
  const common = { width: size, height: size, viewBox: '0 0 24 24', 'aria-hidden': true }
  switch (kind) {
    case 'goal':
    case 'milestone':
      return <svg {...common}><circle cx="12" cy="12" r="9" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M12 7l3.5 2.5-1.3 4h-4.4l-1.3-4z" fill="currentColor" /></svg>
    case 'yellow_card':
      return <svg {...common}><rect x="7" y="3" width="10" height="16" rx="2" fill="#ffd400" transform="rotate(8 12 12)" /></svg>
    case 'red_card':
      return <svg {...common}><rect x="7" y="3" width="10" height="16" rx="2" fill="#ff2a3d" transform="rotate(8 12 12)" /></svg>
    case 'substitution':
      return <svg {...common}><path d="M7 4v13l-3-3M17 20V7l3 3" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
    case 'half_time':
    case 'full_time':
      return <svg {...common}><circle cx="13" cy="13" r="7" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M6 13H2M13 6V3h4" stroke="currentColor" strokeWidth="2" /></svg>
    case 'momentum_shift':
    case 'pressure_spell':
      return <svg {...common}><path d="M3 17l6-6 4 4 8-8M15 7h6v6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
    default:
      return <svg {...common}><path d="M4 12h12M12 6l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></svg>
  }
}

function factValue(value: string | number | boolean, label: string, names: Record<string, string>, lang: Language): string {
  if (label === 'goal_context') return CONTEXT_LABELS[lang][String(value)] ?? String(value)
  if (label === 'card_reason') return cardReasonText(String(value), null, lang) ?? String(value)
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
          <dd>{localDigits(factValue(value, label, names, lang), lang)}</dd>
        </div>
      ))}
    </dl>
  )
}

export function zoneSentence(state: State, lang: Language): string | null {
  const h = state.hello
  const team = state.possession
  if (!h || !team || !state.ball) return null
  const z = describeZone(state.ball.x, state.ball.y, attacksRight(team, state.period, h.home.id))
  const club = team === h.home.id ? h.home.short_name : h.away.short_name
  return `${club} · ${t(lang, `third_${z.third}` as never)} · ${t(lang, `channel_${z.channel}` as never)}`
}

const PITCH_L = 105
const PITCH_W = 68

export function PitchMarkings() {
  const line = { stroke: 'rgba(255,255,255,.85)', strokeWidth: 0.5, fill: 'none' }
  return (
    <g {...line}>
      <rect x={0.5} y={0.5} width={PITCH_L - 1} height={PITCH_W - 1} rx={0.5} />
      <line x1={PITCH_L / 2} y1={0.5} x2={PITCH_L / 2} y2={PITCH_W - 0.5} />
      <circle cx={PITCH_L / 2} cy={PITCH_W / 2} r={9.15} />
      <circle cx={PITCH_L / 2} cy={PITCH_W / 2} r={0.6} fill="rgba(255,255,255,.85)" />
      {[0, 1].map(side => {
        const x = (v: number) => (side === 0 ? v : PITCH_L - v)
        return (
          <g key={side}>
            <rect x={side === 0 ? 0.5 : PITCH_L - 17} y={PITCH_W / 2 - 20.16} width={16.5} height={40.32} />
            <rect x={side === 0 ? 0.5 : PITCH_L - 6} y={PITCH_W / 2 - 9.16} width={5.5} height={18.32} />
            <circle cx={x(11)} cy={PITCH_W / 2} r={0.6} fill="rgba(255,255,255,.85)" />
            <path d={`M ${x(17)} ${PITCH_W / 2 - 7.3} A 9.15 9.15 0 0 ${side === 0 ? 1 : 0} ${x(17)} ${PITCH_W / 2 + 7.3}`} />
          </g>
        )
      })}
    </g>
  )
}

/** Moves the ball along the events at 60 fps without re-rendering React (see ballPath.ts). */
function useBallMotion(state: State, mirror: boolean) {
  const ref = useRef<SVGGElement>(null)
  const path = useRef<BallPath>(emptyPath(PITCH_L / 2, PITCH_W / 2))
  const lastSeq = useRef(-1)
  const speed = state.hello?.speed ?? 1
  useEffect(() => {
    const now = performance.now()
    for (const e of state.trail) {  // every new event, even when several arrive at once
      if (e.seq > lastSeq.current) {
        path.current = planEvent(path.current, e, now, speed)
        lastSeq.current = e.seq
      }
    }
  }, [state.trail, speed])
  useEffect(() => {
    let raf = 0
    const tick = () => {
      const p = ballAt(path.current, performance.now())
      const x = mirror ? PITCH_L - p.x : p.x
      const y = mirror ? PITCH_W - p.y : p.y
      ref.current?.setAttribute('transform', `translate(${x.toFixed(2)} ${y.toFixed(2)})`)
      raf = requestAnimationFrame(tick)
    }
    raf = requestAnimationFrame(tick)
    return () => cancelAnimationFrame(raf)
  }, [mirror])
  return ref
}

/** A pitch with a football that follows the play. */
export function ZoneMap({ state, colors, lang, compact = false, mirror = false, layout = 'stack' }: {
  state: State; colors: Record<string, string>; lang: Language; compact?: boolean
  /** 'bare': just the pitch, centred and compact (fan app); the zone sentence becomes its accessible label. */
  layout?: 'stack' | 'bare'
  /** Flip the drawing end to end (e.g. so the fan's club always attacks right). The label is unaffected. */
  mirror?: boolean
}) {
  const h = state.hello
  const color = (state.possession && colors[state.possession]) || '#00ff85'
  const sentence = zoneSentence(state, lang)
  const attackRight = h && state.possession ? attacksRight(state.possession, state.period, h.home.id) !== mirror : null
  const ballRef = useBallMotion(state, mirror)
  return (
    <div className={`zone-card${compact ? ' compact' : ''}${layout === 'bare' ? ' bare' : ''}`} data-testid="zone-map">
      {layout !== 'bare' && <div className="zone-head"><span>{t(lang, 'whereBall')}</span></div>}
      <svg className="mini-pitch" viewBox={`0 0 ${PITCH_L} ${PITCH_W}`} role="img" aria-label={sentence ?? t(lang, 'offBall')}
        data-testid="mini-pitch" data-mirrored={mirror}>
        <defs>
          <clipPath id="pitch-clip"><rect x={0} y={0} width={PITCH_L} height={PITCH_W} rx={2} /></clipPath>
        </defs>
        <g clipPath="url(#pitch-clip)">
          {Array.from({ length: 12 }, (_, i) => (
            <rect key={i} x={(i * PITCH_L) / 12} y={0} width={PITCH_L / 12} height={PITCH_W} className={i % 2 ? 'stripe-b' : 'stripe-a'} />
          ))}
          <PitchMarkings />
          {/* drawn last so it sits on top of the pitch lines, solid */}
          {state.trail.length > 0 && (
            <g ref={ballRef} className="ball-marker" data-testid="ball">
              <circle r={2.6} fill="#fff" stroke="#1a1a1a" strokeWidth={0.35} />
              <path d="M 0 -1.1 L 1.05 -0.35 L 0.65 0.9 L -0.65 0.9 L -1.05 -0.35 Z" fill="#1a1a1a" />
              <path d="M 0 -1.1 L 0 -2.6 M 1.05 -0.35 L 2.45 -0.85 M 0.65 0.9 L 1.5 2.1 M -0.65 0.9 L -1.5 2.1 M -1.05 -0.35 L -2.45 -0.85"
                stroke="#1a1a1a" strokeWidth={0.35} />
            </g>
          )}
          {attackRight !== null && layout !== 'bare' && (
            <path className="attack-chevron" d={attackRight ? 'M 96 28 L 101 34 L 96 40' : 'M 9 28 L 4 34 L 9 40'}
              stroke={color} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
          )}
        </g>
      </svg>
      {layout !== 'bare' && <p className="zone-text" data-testid="zone-text">{sentence ?? t(lang, 'offBall')}</p>}
    </div>
  )
}
