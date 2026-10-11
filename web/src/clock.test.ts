import { describe, expect, it } from 'vitest'
import { advanceClock, formatClock } from './clock'

const MIN = 60_000

describe('match clock with seconds', () => {
  it('shows minutes and seconds in normal time', () => {
    expect(formatClock(0, 1)).toEqual({ main: '00:00', added: null })
    expect(formatClock(23 * MIN + 7_000, 1)).toEqual({ main: '23:07', added: null })
    expect(formatClock(67 * MIN + 59_999, 2)).toEqual({ main: '67:59', added: null })
  })
  it('freezes at 45:00 or 90:00 and counts stoppage time separately', () => {
    expect(formatClock(47 * MIN + 13_000, 1)).toEqual({ main: '45:00', added: '+2:13' })
    expect(formatClock(90 * MIN, 2)).toEqual({ main: '90:00', added: '+0:00' })
    expect(formatClock(94 * MIN + 5_000, 2)).toEqual({ main: '90:00', added: '+4:05' })
    expect(formatClock(46 * MIN, 2)).toEqual({ main: '46:00', added: null })  // second half starts at 45:00
  })
  it('runs on between events at match speed, but never far ahead of the data', () => {
    expect(advanceClock(10 * MIN, 1_000, 10)).toBe(10 * MIN + 10_000)   // 1 s real at 10x
    expect(advanceClock(10 * MIN, 60_000, 10)).toBe(10 * MIN + 10_000)  // capped while waiting for the next event
    expect(advanceClock(10 * MIN, 2_000, 0)).toBe(10 * MIN)
  })
})
