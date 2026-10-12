import { describe, expect, it } from 'vitest'
import { emptyThird, GAP_MS, SHOW_MS, stepThird } from './overlayQueue'
import type { Overlay } from './types'

const o = (id: string, version = 1) => ({ id, version }) as Overlay

describe('lower third (OV-2)', () => {
  it('shows the newest graphic, skipping older ones, for a fixed time', () => {
    let s = stepThird(emptyThird(), [o('c'), o('b'), o('a')], 10_000)
    expect(s.current?.id).toBe('c')
    s = stepThird(s, [o('d'), o('c'), o('b'), o('a')], 10_000 + SHOW_MS - 1)
    expect(s.current?.id).toBe('c')                       // still showing
    s = stepThird(s, [o('d'), o('c')], 10_000 + SHOW_MS)
    expect(s.current).toBe(null)                           // slides out
    s = stepThird(s, [o('d'), o('c')], 10_000 + SHOW_MS + GAP_MS)
    expect(s.current?.id).toBe('d')                        // then the next new one
    s = stepThird(s, [o('d'), o('c')], 10_000 + 2 * SHOW_MS + GAP_MS)
    s = stepThird(s, [o('d'), o('c')], 10_000 + 3 * SHOW_MS)
    expect(s.current).toBe(null)                           // nothing new: stays out
  })
  it('upgrades in place when the AI version arrives', () => {
    let s = stepThird(emptyThird(), [o('a', 1)], 5_000)
    s = stepThird(s, [o('a', 2)], 6_000)
    expect(s.current?.version).toBe(2)
    expect(s.since).toBe(5_000)                            // the clock doesn't restart
  })
})
