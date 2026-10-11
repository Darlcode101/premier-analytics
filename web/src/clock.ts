// Broadcast-style match clock with seconds: "67:23", or "45:00" with "+2:13" in stoppage time.
import { useEffect, useState } from 'react'

const MIN = 60_000
const AHEAD_MS = 10_000  // how far the clock may run past the last event while waiting for the next one

const mmss = (ms: number) => {
  const s = Math.floor(ms / 1000)
  return `${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`
}

export function formatClock(clockMs: number, period: number): { main: string; added: string | null } {
  const end = period === 1 ? 45 * MIN : 90 * MIN
  if (clockMs < end) return { main: mmss(clockMs), added: null }
  const over = Math.floor((clockMs - end) / 1000)
  return { main: mmss(end), added: `+${Math.floor(over / 60)}:${String(over % 60).padStart(2, '0')}` }
}

/** Match time shown `realMs` after the last update, at `speed` match-seconds per second, capped. */
export function advanceClock(clockMs: number, realMs: number, speed: number): number {
  return clockMs + Math.min(Math.max(realMs, 0) * Math.max(speed, 0), AHEAD_MS)
}

/** Ticks the clock smoothly between events while the ball is in play. */
export function useMatchClock(clockMs: number, speed: number, running: boolean): number {
  const [shown, setShown] = useState(clockMs)
  useEffect(() => {
    const start = performance.now()
    const tick = () => {
      const next = running ? advanceClock(clockMs, performance.now() - start, speed) : clockMs
      // Never step backwards when an event lands just behind the ticking clock; a new half resets it.
      setShown(prev => (next < prev && prev - next < AHEAD_MS ? prev : next))
    }
    const first = window.setTimeout(tick, 0)
    const every = running ? window.setInterval(tick, 250) : undefined
    return () => { window.clearTimeout(first); window.clearInterval(every) }
  }, [clockMs, speed, running])
  return shown
}
