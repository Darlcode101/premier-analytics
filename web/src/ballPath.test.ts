import { describe, expect, it } from 'vitest'
import { ballAt, emptyPath, MAX_LAG_MS, planEvent } from './ballPath'

const ev = (kind: string, x: number, y: number, end_x: number | null = null, end_y: number | null = null) =>
  ({ kind, x, y, end_x, end_y })

describe('ball path (smooth, event-accurate)', () => {
  it('a pass travels from the passer to the receiver over a realistic time', () => {
    let p = planEvent(emptyPath(50, 34), ev('pass', 40, 30, 60, 30), 1000, 10)
    const start = ballAt(p, 1000)
    const end = ballAt(p, 1000 + MAX_LAG_MS)
    expect(end).toEqual({ x: 60, y: 30 })
    const mid = ballAt(p, (p.points[0].at + p.points[1].at) / 2)
    expect(mid.x).toBeGreaterThan(40); expect(mid.x).toBeLessThan(60)
    expect(start.x).toBeGreaterThanOrEqual(40 - 10)  // eases from where it was
    p = planEvent(p, ev('pass', 60, 30, 80, 50), 1300, 10)
    expect(ballAt(p, 1300 + 3 * MAX_LAG_MS)).toEqual({ x: 80, y: 50 })
  })
  it('never moves backwards in time or lags far behind the match', () => {
    let p = emptyPath(50, 34)
    for (let i = 0; i < 40; i++) p = planEvent(p, ev('pass', 50 + i, 34, 51 + i, 34), 1000 + i, 1)  // a burst
    const last = p.points[p.points.length - 1]
    expect(last.at - 1040).toBeLessThanOrEqual(MAX_LAG_MS)
    for (let i = 1; i < p.points.length; i++) expect(p.points[i].at).toBeGreaterThanOrEqual(p.points[i - 1].at)
  })
  it('restarts snap the ball to the spot instead of flying across', () => {
    let p = planEvent(emptyPath(90, 10), ev('pass', 90, 10, 95, 30), 0, 10)
    p = planEvent(p, ev('kickoff', 52.5, 34), 100, 10)
    expect(ballAt(p, 100)).toEqual({ x: 52.5, y: 34 })
  })
  it('events without a position leave the ball where it is', () => {
    const p = planEvent(emptyPath(30, 20), ev('card', null as never, null as never), 0, 10)
    expect(ballAt(p, 5000)).toEqual({ x: 30, y: 20 })
  })
})
