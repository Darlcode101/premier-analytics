import { describe, expect, it } from 'vitest'
import { CONTEXT_LABELS, dictionaries, FACT_LABELS, KIND_LABELS } from './i18n'

describe('i18n', () => {
  it('every language has every UI string, non-empty', () => {
    const keys = Object.keys(dictionaries.en).sort()
    for (const [lang, dict] of Object.entries(dictionaries)) {
      expect(Object.keys(dict).sort(), lang).toEqual(keys)
      for (const [k, v] of Object.entries(dict)) expect(v.trim(), `${lang}.${k}`).not.toBe('')
    }
  })

  it('every language labels every fact', () => {
    const keys = Object.keys(FACT_LABELS.en).sort()
    for (const lang of ['es', 'ar'] as const) expect(Object.keys(FACT_LABELS[lang]).sort()).toEqual(keys)
  })

  it('translations are actually translated (not copied English) for most strings', () => {
    for (const lang of ['es', 'ar'] as const) {
      const same = Object.entries(dictionaries[lang]).filter(([k, v]) => v === dictionaries.en[k as keyof typeof dictionaries.en])
      expect(same.length, same.map(([k]) => k).join(',')).toBeLessThanOrEqual(3) // e.g. brand name, "Control"
    }
  })
})


describe('labels', () => {
  it('moment kinds and goal contexts are labelled in every language', () => {
    for (const table of [KIND_LABELS, CONTEXT_LABELS]) {
      const keys = Object.keys(table.en).sort()
      for (const lang of ['es', 'ar'] as const) expect(Object.keys(table[lang]).sort()).toEqual(keys)
    }
  })
})
