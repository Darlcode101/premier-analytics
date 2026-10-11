// Pattern Analyst pictures (PA-5): one team's shape on a pitch drawn in its own attacking direction (left to right).
import { localDigits } from '../digits'
import type { Language, PatternNote, TeamShape } from '../types'
import { PITCH_L, PITCH_W } from '../zones'
import { PitchMarkings } from './Shared'

const BOX_X = PITCH_L - 16.5
const CHANNELS = ['left', 'centre', 'right'] as const  // facing right, the top touchline is the attacker's left
const THIRDS = ['defensive', 'middle', 'attacking'] as const

const pct = (k: number, n: number) => (n ? Math.round((100 * k) / n) : 0)

export type PatternView = 'flank' | 'regains' | 'shots'

export function viewFor(kind: PatternNote['kind']): PatternView {
  return kind === 'high_regains' ? 'regains' : kind === 'long_shots' || kind === 'counters' ? 'shots' : 'flank'
}

export function PatternPitch({ note, shape, color, lang }: { note: PatternNote; shape: TeamShape; color: string; lang: Language }) {
  const view = viewFor(note.kind)
  const entries = CHANNELS.reduce((a, c) => a + shape.entries[c], 0)
  const regains = THIRDS.reduce((a, t) => a + shape.regains[t], 0)
  return (
    <svg className="pattern-pitch" viewBox={`0 0 ${PITCH_L} ${PITCH_W}`} role="img" data-testid="pattern-pitch" data-kind={note.kind}
      aria-label={note.text}>
      <rect width={PITCH_L} height={PITCH_W} rx={2} className="pp-grass" />
      <PitchMarkings />
      {view === 'flank' && CHANNELS.map((c, i) => {
        const share = pct(shape.entries[c], entries)
        const y = (i + 0.5) * (PITCH_W / 3)
        const strong = c === note.value
        return (
          <g key={c} data-testid="channel-share" data-channel={c} opacity={strong ? 1 : 0.55}>
            <rect x={70} y={i * (PITCH_W / 3) + 1} width={PITCH_L - 71} height={PITCH_W / 3 - 2} rx={1.5}
              fill={color} opacity={0.12 + (0.6 * share) / 100} />
            <path d={`M 40 ${y} L ${62 + share / 4} ${y}`} stroke={color} strokeWidth={1.2 + share / 14} strokeLinecap="round" />
            <path d={`M ${58 + share / 4} ${y - 3} L ${64 + share / 4} ${y} L ${58 + share / 4} ${y + 3}`} fill="none"
              stroke={color} strokeWidth={1.4} strokeLinejoin="round" />
            <text x={87.5} y={y + 2.4} className="pp-label" textAnchor="middle">{localDigits(`${share}%`, lang)}</text>
          </g>
        )
      })}
      {view === 'regains' && THIRDS.map((t, i) => {
        const share = pct(shape.regains[t], regains)
        return (
          <g key={t} data-testid="third-share">
            <rect x={i * (PITCH_L / 3) + 1} y={1} width={PITCH_L / 3 - 2} height={PITCH_W - 2} rx={1.5}
              fill={color} opacity={0.08 + (0.7 * share) / 100} />
            <text x={(i + 0.5) * (PITCH_L / 3)} y={PITCH_W / 2 + 2.6} className="pp-label" textAnchor="middle">
              {localDigits(`${share}%`, lang)}
            </text>
          </g>
        )
      })}
      {view === 'shots' && shape.shots.map((s, i) => {
        const outside = s.x < BOX_X
        const lit = note.kind === 'counters' ? s.counter : outside
        return (
          <circle key={i} data-testid="shot-dot" cx={s.x} cy={s.y} r={lit ? 1.6 : 1.1}
            fill={lit ? color : 'rgba(255,255,255,.55)'} stroke={lit ? '#fff' : 'none'} strokeWidth={0.4} />
        )
      })}
      <path d={`M ${PITCH_L - 9} 4 L ${PITCH_L - 4} 4`} stroke="rgba(255,255,255,.7)" strokeWidth={0.7} />
      <path d={`M ${PITCH_L - 6} 2.5 L ${PITCH_L - 4} 4 L ${PITCH_L - 6} 5.5`} fill="none" stroke="rgba(255,255,255,.7)" strokeWidth={0.7} />
    </svg>
  )
}
