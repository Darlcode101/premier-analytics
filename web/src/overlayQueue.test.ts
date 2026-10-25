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

import { capFor, fitText } from './overlayQueue'

describe('fitting text to the pop-up (OV-2)', () => {
  it('keeps text that fits untouched', () => {
    expect(fitText('Short and sweet.', 50)).toBe('Short and sweet.')
  })
  it('trims to the last whole sentence that fits', () => {
    const text = 'Greaves scores from close range. Selene lead for the first time. It ends a long wait.'
    expect(fitText(text, 70)).toBe('Greaves scores from close range. Selene lead for the first time.')
  })
  it('falls back to a word boundary with an ellipsis, never mid-word', () => {
    const text = 'Selene have dominated the ball and the territory for twenty minutes without a shot on target'
    const out = fitText(text, 40)
    expect(out.length).toBeLessThanOrEqual(40)
    expect(out.endsWith('…')).toBe(true)
    expect(text.startsWith(out.slice(0, -1).trimEnd())).toBe(true)
    expect(out.slice(0, -1).endsWith(' ')).toBe(false)
  })
  it('derives the cap from the box: lines × characters per line', () => {
    expect(capFor(700, 16, 2)).toBe(Math.floor(700 / (16 * 0.52)) * 2)
    expect(capFor(300, 16, 2)).toBeLessThan(capFor(700, 16, 2))
  })
})
