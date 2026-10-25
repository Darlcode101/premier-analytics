import { describe, expect, it } from 'vitest'
import { deskDictionaries } from './deskText'
import { explainAttack } from './explain'
import { CONTEXT_LABELS, dictionaries, FACT_LABELS, KIND_LABELS } from './i18n'
import { dirOf, LANGUAGE_NAMES, LANGUAGES } from './languages'
import { speechLanguage } from './listen'
import { CATALOGUES, fill, plural } from './locales'
import type { AttackPoint } from './types'

// DK-12: 13 languages. Hand-written EN/ES/AR, catalogued for the other ten.
const placeholders = (s: string) => [...s.matchAll(/\{(\w+)\}/g)].map(m => m[1]).sort()

function sameShape(table: Record<string, Record<string, string>>, name: string) {
  const en = table.en
  for (const lang of LANGUAGES) {
    const theirs = table[lang]
    expect(Object.keys(theirs).sort(), `${name}.${lang}`).toEqual(Object.keys(en).sort())
    for (const [k, v] of Object.entries(en)) {
      expect(theirs[k]?.trim(), `${name}.${lang}.${k}`).toBeTruthy()
      expect(placeholders(theirs[k]), `${name}.${lang}.${k}`).toEqual(placeholders(v))
    }
  }
}

describe('13 languages (DK-12)', () => {
  it('each named in itself, once; only Arabic right to left', () => {
    expect(LANGUAGES).toHaveLength(13)
    expect(new Set(Object.values(LANGUAGE_NAMES)).size).toBe(13)
    expect(LANGUAGES.filter(l => dirOf(l) === 'rtl')).toEqual(['ar'])
  })

  it('every desk, landing and label string exists with English\'s placeholders', () => {
    sameShape(dictionaries, 'ui')
    sameShape(deskDictionaries, 'desk')
    sameShape(FACT_LABELS, 'facts')
    sameShape(KIND_LABELS, 'kinds')
    sameShape(CONTEXT_LABELS, 'contexts')
  })

  it('catalogues are translated, not copied English', () => {
    for (const lang of Object.keys(CATALOGUES) as (keyof typeof CATALOGUES)[]) {
      for (const [table, en] of [[dictionaries[lang], dictionaries.en], [deskDictionaries[lang], deskDictionaries.en]] as const) {
        const same = Object.entries(table).filter(([k, v]) => v === (en as Record<string, string>)[k] && /[a-z]{4}/.test(v))
        expect(same.length, `${lang}: ${same.map(([k]) => k).join(', ')}`).toBeLessThanOrEqual(8)  // cognates: Possession, Corners
      }
    }
  })

  it('a speech locale for every language', () => {
    for (const lang of LANGUAGES) expect(speechLanguage(lang)).toMatch(new RegExp(`^${lang}-[A-Z]{2}$`))
  })

  it('momentum reasons read cleanly in every language', () => {
    const p = { minute: 30, window: [25, 30], value: 0.6, home: { shots: 1, xg: 0.3, final_third_passes: 4, high_regains: 2 },
      away: { shots: 0, xg: 0, final_third_passes: 1, high_regains: 0 } } as unknown as AttackPoint
    for (const lang of LANGUAGES) {
      const e = explainAttack(p, 'har', 'ngc', { har: 'Harbourside', ngc: 'Northgate' }, lang)
      expect(e.headline, lang).toContain('Harbourside')
      expect(e.reasons, lang).toHaveLength(3)
      expect([e.headline, ...e.reasons, ...e.opponentReasons].join(' '), lang).not.toMatch(/undefined|\{/)
      expect(e.reasons.join(' '), lang).toMatch(/4/)
    }
  })
})

describe('plural forms', () => {
  const p = { one: 'one {n}', other: 'other {n}' }
  it('follow each language\'s rules', () => {
    expect(fill(plural(p, 1, 'de'), { n: 1 })).toBe('one 1')
    expect(fill(plural(p, 0, 'de'), { n: 0 })).toBe('other 0')
    expect(plural(p, 0, 'fr')).toBe('one {n}')  // French: 0 and 1 are singular
    expect(plural(p, 2, 'fr')).toBe('other {n}')
  })
  it('a plain string is used for every count', () => {
    expect(plural('{n} 本', 1, 'ja')).toBe('{n} 本')
    expect(fill('{a} and {b}', { a: 'x', b: 2 })).toBe('x and 2')
  })
})
