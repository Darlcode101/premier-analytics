import { describe, expect, it } from 'vitest'
import { phrasesFor, speechLanguage } from './listen'
import { initialState, reducer } from './state'
import type { FactFlag, Hello, Language } from './types'

const hello = {
  home: { short_name: 'Harbourside', name: 'Harbourside Athletic', lineup: [{ name: 'Zane Kowalczyk' }], bench: [{ name: 'Leandro Ashworth' }] },
  away: { short_name: 'Northgate', name: 'Northgate City', lineup: [{ name: 'Pablo Wakefield-Ames' }], bench: [] },
} as unknown as Hello

describe('Listen (FC-1)', () => {
  it('biases recognition towards the match\'s names: full names, surnames and clubs, once each', () => {
    const p = phrasesFor(hello)
    for (const word of ['Zane Kowalczyk', 'Kowalczyk', 'Wakefield-Ames', 'Harbourside', 'Northgate City']) expect(p).toContain(word)
    expect(new Set(p).size).toBe(p.length)
  })
  it('listens in the desk\'s language', () => {
    expect(speechLanguage('en')).toBe('en-GB')
    expect(speechLanguage('es')).toBe('es-ES')
    expect(speechLanguage('ar')).toBe('ar-SA')
    expect(speechLanguage('pt')).toBe('pt-BR')
    expect(speechLanguage('zh')).toBe('zh-CN')
  })
})

describe('fact-check flags (FC-2)', () => {
  const flag = (subject: string) => ({ verdict: 'wrong', subject, text: { en: `${subject}: 1 shot, not 3` } }) as unknown as FactFlag
  it('newest first, a running count, at most ten kept', () => {
    let s = reducer(initialState, { type: 'fact_check', checked: 2, flags: [flag('A')], status: 'ok' })
    s = reducer(s, { type: 'fact_check', checked: 1, flags: [flag('B')], status: 'ok' })
    expect(s.factFlags.map(f => f.subject)).toEqual(['B', 'A'])
    expect(s.factChecked).toBe(3)
    for (let i = 0; i < 12; i++) s = reducer(s, { type: 'fact_check', checked: 1, flags: [flag(`x${i}`)], status: 'ok' })
    expect(s.factFlags).toHaveLength(10)
  })
})

describe('fact-check log (FC-2, 10-25)', () => {
  it('a line shows at once as checking, then gets its results by id', () => {
    let s = reducer(initialState, { type: 'said_local', id: 'l1', line: 'Kowalczyk has 3 shots' })
    s = reducer(s, { type: 'said_local', id: 'l2', line: 'What a game' })
    expect(s.factLog.map(l => [l.id, l.status])).toEqual([['l2', 'checking'], ['l1', 'checking']])
    s = reducer(s, { type: 'fact_check', id: 'l1', checked: 1, flags: [], status: 'ok',
      results: [{ verdict: 'correct', text: { en: 'Zane Kowalczyk: 1 shot' } as Record<Language, string> }] })
    s = reducer(s, { type: 'fact_check', id: 'l2', checked: 0, flags: [], status: 'ok', results: [] })
    expect(s.factLog.find(l => l.id === 'l1')?.results[0].verdict).toBe('correct')
    expect(s.factLog.map(l => l.status)).toEqual(['done', 'done'])
  })
})
