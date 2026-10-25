import { beforeEach, describe, expect, it } from 'vitest'
import { initialLanguage, saveLanguage, withLanguage } from './prefs'

const store = new Map<string, string>()
beforeEach(() => {
  store.clear()
  ;(globalThis as Record<string, unknown>).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  }
})

describe('language preference', () => {
  it('a saved choice wins over the link, the link over the default', () => {
    expect(initialLanguage('?match=x')).toBe('en')
    expect(initialLanguage('?match=x&lang=es')).toBe('es')
    saveLanguage('ar')
    expect(initialLanguage('?match=x&lang=es')).toBe('ar')  // a QR link carries the laptop's language, not yours
    expect(initialLanguage('?match=x')).toBe('ar')
  })
  it('ignores unknown values', () => {
    expect(initialLanguage('?lang=xx')).toBe('en')
    expect(initialLanguage('?lang=fr')).toBe('fr')  // DK-12
    store.set('pa.language', 'xx')
    expect(initialLanguage('?lang=es')).toBe('es')
  })
  it('keeps the address in step so a reload or a shared link shows the same language', () => {
    expect(withLanguage('/fan?match=abc&lang=en', 'es')).toBe('/fan?match=abc&lang=es')
    expect(withLanguage('/desk?match=abc', 'ar')).toBe('/desk?match=abc&lang=ar')
  })
  it('falls back to the link when storage is unavailable', () => {
    ;(globalThis as Record<string, unknown>).localStorage = {
      getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') }, removeItem: () => { throw new Error('blocked') },
    }
    expect(() => saveLanguage('es')).not.toThrow()
    expect(initialLanguage('?lang=es')).toBe('es')
  })
})
