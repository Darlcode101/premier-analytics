// Smooth, event-accurate ball movement for the mini pitch. Each event becomes waypoints with arrival
// times (a pass travels passer -> receiver over roughly the simulator's pass time at the match speed);
// the ball eases between waypoints at 60 fps. Waypoints are kept in order and never more than
// MAX_LAG_MS behind the live match, and restarts (kick-offs, goal kicks, corners) snap to the spot.
export interface Point { x: number; y: number }
export interface Waypoint extends Point { at: number; snap?: boolean }
export interface BallPath { from: Point & { at: number }; points: Waypoint[] }

export const MAX_LAG_MS = 1000
const MIN_STEP_MS = 60
const SNAP_KINDS = new Set(['kickoff', 'period_start', 'period_end', 'goal', 'corner', 'penalty'])

export const emptyPath = (x: number, y: number): BallPath => ({ from: { x, y, at: 0 }, points: [] })

interface EventLike { kind: string; x: number | null; y: number | null; end_x: number | null; end_y: number | null }

/** Add an event's movement to the path, arriving at real time `now` at `speed` match-seconds per second. */
export function planEvent(path: BallPath, e: EventLike, now: number, speed: number): BallPath {
  if (e.x === null || e.y === null) return path
  const current = ballAt(path, now)
  // Drop waypoints already passed; start from where the ball is now.
  const pending = path.points.filter(p => p.at > now)
  const base: BallPath = { from: { ...current, at: now }, points: pending }
  if (SNAP_KINDS.has(e.kind)) {
    return { from: { x: e.x, y: e.y, at: now }, points: [] }
  }
  const last = (): number => (base.points.length ? base.points[base.points.length - 1].at : now)
  const add = (x: number, y: number, after: number) => {
    const at = Math.min(Math.max(last() + MIN_STEP_MS, now + after), now + MAX_LAG_MS)
    base.points.push({ x, y, at: Math.max(at, last()) })
  }
  const pace = 1000 / Math.max(speed, 1)
  add(e.x, e.y, 0.25 * pace)  // where the action starts
  if (e.end_x !== null && e.end_y !== null) {
    const length = Math.hypot(e.end_x - e.x, e.end_y - e.y)
    const travel = e.kind === 'shot' ? 0.6 * pace : (1.0 + length / 14) * pace  // roughly the simulator's pass time
    add(e.end_x, e.end_y, 0.25 * pace + travel)
  }
  return base
}

const ease = (t: number) => (t < 0.5 ? 2 * t * t : 1 - (-2 * t + 2) ** 2 / 2)

/** Where the ball is at real time `t`. */
export function ballAt(path: BallPath, t: number): Point {
  let prev: Point & { at: number } = path.from
  for (const p of path.points) {
    if (t < p.at) {
      const span = p.at - prev.at
      const k = span <= 0 ? 1 : ease(Math.min(1, Math.max(0, (t - prev.at) / span)))
      return { x: prev.x + (p.x - prev.x) * k, y: prev.y + (p.y - prev.y) * k }
    }
    prev = p
  }
  return { x: prev.x, y: prev.y }
}
