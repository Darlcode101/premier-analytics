import { useEffect, useState } from 'react'
import { CONTEXT_LABELS, FACT_LABELS, KIND_LABELS, t } from '../i18n'
import type { State } from '../state'
import type { ClubInfo, Hello, Language, Overlay } from '../types'
import { attacksRight, cellOf, describeZone } from '../zones'

/** Generated shield badge in the club's colours with its initials (fictional clubs, no real crests). */
export function Crest({ club, size = 40 }: { club: ClubInfo; size?: number }) {
  const initials = club.name.split(' ').map(w => w[0]).join('').slice(0, 3).toUpperCase()
  const [a, b] = club.colors
  return (
    <svg width={size} height={size * 1.15} viewBox="0 0 40 46" role="img" aria-label={club.name}>
      <path d="M20 1 L38 7 V22 C38 34 30 41 20 45 C10 41 2 34 2 22 V7 Z" fill={a} stroke="rgba(255,255,255,.9)" strokeWidth="2" />
      <path d="M20 1 L38 7 V22 C38 26 37 29 36 31 L4 31 C3 29 2 26 2 22 V7 Z" fill={a} />
      <path d="M4 31 L36 31 C33 38 27 42 20 45 C13 42 7 38 4 31 Z" fill={b} />
      <text x="20" y="23" textAnchor="middle" fontSize="12" fontWeight="800" fill={b}
        fontFamily="'Barlow Condensed', sans-serif" letterSpacing=".5">{initials}</text>
    </svg>
  )
}

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
          <dd>{factValue(value, label, names, lang)}</dd>
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

function PitchMarkings() {
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

/** A pitch with a glowing hue in the possessing team's colour over the ball's area (one of 9 zones). */
export function ZoneMap({ state, colors, lang, compact = false, mirror = false }: {
  state: State; colors: Record<string, string>; lang: Language; compact?: boolean
  /** Flip the drawing end to end (e.g. so the fan's club always attacks right). The label is unaffected. */
  mirror?: boolean
}) {
  const h = state.hello
  const ball = state.ball && (mirror ? { x: PITCH_L - state.ball.x, y: PITCH_W - state.ball.y } : state.ball)
  const cell = ball ? cellOf(ball.x, ball.y) : null
  const color = (state.possession && colors[state.possession]) || '#00ff85'
  const sentence = zoneSentence(state, lang)
  const attackRight = h && state.possession ? attacksRight(state.possession, state.period, h.home.id) !== mirror : null
  const cx = cell ? (cell.col + 0.5) * (PITCH_L / 3) : PITCH_L / 2
  const cy = cell ? (cell.row + 0.5) * (PITCH_W / 3) : PITCH_W / 2
  return (
    <div className={`zone-card${compact ? ' compact' : ''}`} data-testid="zone-map">
      <div className="zone-head"><span>{t(lang, 'whereBall')}</span></div>
      <svg className="mini-pitch" viewBox={`0 0 ${PITCH_L} ${PITCH_W}`} role="img" aria-label={sentence ?? t(lang, 'offBall')}
        data-testid="mini-pitch" data-mirrored={mirror}>
        <defs>
          <radialGradient id="hue" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor={color} stopOpacity={1} />
            <stop offset="35%" stopColor={color} stopOpacity={0.85} />
            <stop offset="70%" stopColor={color} stopOpacity={0.35} />
            <stop offset="100%" stopColor={color} stopOpacity={0} />
          </radialGradient>
          <clipPath id="pitch-clip"><rect x={0} y={0} width={PITCH_L} height={PITCH_W} rx={2} /></clipPath>
        </defs>
        <g clipPath="url(#pitch-clip)">
          {Array.from({ length: 12 }, (_, i) => (
            <rect key={i} x={(i * PITCH_L) / 12} y={0} width={PITCH_L / 12} height={PITCH_W} className={i % 2 ? 'stripe-b' : 'stripe-a'} />
          ))}
          {cell && (
            <g className="hue" style={{ transform: `translate(${cx}px, ${cy}px)` }} data-testid="pitch-hue" data-color={color}>
              <ellipse rx={26} ry={19} fill="url(#hue)" className="hue-glow" />
              <circle r={1.6} fill="#fff" stroke={color} strokeWidth={0.8} />
            </g>
          )}
          <PitchMarkings />
          {attackRight !== null && (
            <path className="attack-chevron" d={attackRight ? 'M 96 28 L 101 34 L 96 40' : 'M 9 28 L 4 34 L 9 40'}
              stroke={color} strokeWidth={2} fill="none" strokeLinecap="round" strokeLinejoin="round" />
          )}
        </g>
      </svg>
      <p className="zone-text" data-testid="zone-text">{sentence ?? t(lang, 'offBall')}</p>
    </div>
  )
}

export function scoreLine(h: Hello, score: [number, number]) {
  return `${h.home.short_name} ${score[0]}–${score[1]} ${h.away.short_name}`
}

/** Full-screen moment animation (R-8). Plays the head of the queue, then reports done. */
export function Celebration({ state, colors, names, lang, onDone }: {
  state: State; colors: Record<string, string>; names: Record<string, string>; lang: Language; onDone: () => void
}) {
  const current = state.animations[0]
  const [shownId, setShownId] = useState<string | null>(null)
  useEffect(() => {
    if (!current) return
    setShownId(current.moment_id)
    if (current.kind === 'goal' && 'vibrate' in navigator) navigator.vibrate?.([80, 60, 120])
    const reduced = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches
    const ms = reduced ? 1600 : { goal: 3800, red_card: 2400, half_time: 2600, full_time: 3000 }[current.kind] ?? 1900
    const timer = window.setTimeout(onDone, ms)
    return () => window.clearTimeout(timer)
  }, [current?.moment_id]) // eslint-disable-line react-hooks/exhaustive-deps
  if (!current || shownId !== current.moment_id || !state.hello) return null
  const h = state.hello
  const team = current.team_id
  const club = team === h.home.id ? h.home : team === h.away.id ? h.away : null
  const color = (team && colors[team]) || '#37003c'
  const o = current.overlay
  const label = {
    goal: t(lang, 'celebrateGoal'), red_card: t(lang, 'sentOff'), big_chance: t(lang, 'soClose'),
    woodwork: t(lang, 'soClose'), momentum_shift: t(lang, 'momentumSwing'),
    half_time: t(lang, 'whistleHT'), full_time: t(lang, 'whistleFT'),
  }[current.kind] ?? KIND_LABELS[lang][current.kind]
  return (
    <div className={`celebrate ${current.kind}`} style={{ '--team': color } as React.CSSProperties}
      data-testid="celebration" data-kind={current.kind} role="status" aria-live="assertive">
      {current.kind === 'goal' && <div className="confetti" aria-hidden>{Array.from({ length: 28 }, (_, i) => <i key={i} />)}</div>}
      {current.kind === 'red_card' && <div className="red-card-drop" aria-hidden />}
      <div className="celebrate-inner">
        {club && <Crest club={club} size={current.kind === 'goal' ? 64 : 44} />}
        <div className="celebrate-title">{label}</div>
        {(current.kind === 'goal' || current.kind.endsWith('_time')) && (
          <div className="celebrate-score" dir="ltr">{scoreLine(h, [Number(o.data.score_home ?? 0), Number(o.data.score_away ?? 0)])}</div>
        )}
        {current.kind === 'goal' && typeof o.data.scorer === 'string' && (
          <div className="celebrate-sub" data-testid="celebration-scorer">{names[o.data.scorer] ?? o.data.scorer} · {o.minute}'</div>
        )}
        {!['goal', 'half_time', 'full_time'].includes(current.kind) && <div className="celebrate-sub">{o.headline}</div>}
      </div>
    </div>
  )
}
