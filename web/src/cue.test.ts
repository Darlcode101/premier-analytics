import { describe, expect, it } from 'vitest'
import { cueText, MIN_ON_AIR_MS, onAirMs, shownState } from './cue'
import { initialState, reducer, type State } from './state'
import type { Cue, Hello, Incident, Overlay } from './types'

const cue = (extra: Partial<Cue> = {}): Cue => ({
  id: 1, ref: 'm1', kind: 'moment', label: 'goal', source: 'explainer', team_id: 'har', minute: '13',
  reasons: ['big_moment'], state: 'on_air', break_kind: 'goal', window_s: 75, ...extra,
})

describe('on-air timing (GP-2)', () => {
  it('lasts the break at replay speed, never under 6 s, and forever at full time', () => {
    expect(onAirMs(75, 1)).toBe(75_000)
    expect(onAirMs(75, 5)).toBe(15_000)
    expect(onAirMs(40, 60)).toBe(MIN_ON_AIR_MS)
    expect(onAirMs(null, 60)).toBe(Infinity)
  })
  it('keeps showing on air after play resumes until the break has been shown', () => {
    const last = { ref: 'm1', until: 10_000, break_kind: 'goal', window_s: 75 }
    expect(shownState(cue({ state: 'up_next', break_kind: null, window_s: null }), last, 5_000).state).toBe('on_air')
    expect(shownState(cue({ state: 'up_next', break_kind: null, window_s: null }), last, 11_000).state).toBe('up_next')
    expect(shownState(cue({ ref: 'other', state: 'up_next' }), last, 5_000).state).toBe('up_next')
  })
})

describe('cue text (GP-1)', () => {
  const overlay = { id: 'o', moment_id: 'm1', headline: 'GOAL', body: 'Selene lead' } as Overlay
  const sub = { id: 'inc-1', kind: 'sub', card: { fan: { en: ['A comes on for B', 'B: 34 passes'], es: ['Entra A por B'], ar: ['x'] } } } as unknown as Incident
  const state: State = {
    ...initialState, feed: [overlay], incidents: [sub],
    patterns: { minute: '45', elapsed_ms: 0, language: 'en', notes: [{ pattern_id: 'p1', text: 'Left side again' }], alerts: [], fan_lines: {} },
  } as unknown as State
  it('finds the words for moments, patterns and substitutions', () => {
    expect(cueText(cue(), state, 'en')).toEqual({ headline: 'GOAL', body: 'Selene lead' })
    expect(cueText(cue({ kind: 'pattern', ref: 'p1' }), state, 'en')?.headline).toBe('Left side again')
    expect(cueText(cue({ kind: 'sub', ref: 'inc-1' }), state, 'en')).toEqual({ headline: 'A comes on for B', body: 'B: 34 passes' })
    expect(cueText(cue({ kind: 'sub', ref: 'inc-1' }), state, 'es')?.headline).toBe('Entra A por B')
    expect(cueText(cue({ ref: 'missing' }), state, 'en')).toBeNull()
  })
})

describe('cue, note and used messages (GP-4, GP-5)', () => {
  const hello = { type: 'hello', match_id: 'x', status: 'live', cue: cue(), cue_note: 'Producer says', used: ['a'] } as unknown as Hello
  it('a late joiner gets the cue, its note and the used set', () => {
    const s = reducer(initialState, hello)
    expect(s.cue?.ref).toBe('m1')
    expect(s.cueNote).toEqual({ ref: 'm1', text: 'Producer says' })
    expect(s.used).toEqual(new Set(['a']))
  })
  it('a note stays with its talking point when play resumes, and goes when the point changes', () => {
    let s = reducer(initialState, hello)
    s = reducer(s, { type: 'cue', cue: cue({ id: 2, state: 'up_next', break_kind: null, window_s: null }) })
    expect(s.cueNote).toEqual({ ref: 'm1', text: 'Producer says' })
    s = reducer(s, { type: 'cue', cue: cue({ id: 3, ref: 'm2' }) })
    expect(s.cueNote).toBeNull()
    s = reducer(s, { type: 'cue_note', ref: 'm1', language: 'en', text: 'old' })
    expect(s.cueNote).toBeNull()
    s = reducer(s, { type: 'cue_note', ref: 'm2', language: 'en', text: 'new' })
    expect(s.cueNote).toEqual({ ref: 'm2', text: 'new' })
  })
  it('used is toggled by the server', () => {
    let s = reducer(initialState, { type: 'used', ref: 'm1', used: true })
    expect(s.used.has('m1')).toBe(true)
    s = reducer(s, { type: 'used', ref: 'm1', used: false })
    expect(s.used.has('m1')).toBe(false)
  })
})
