import { beforeEach, describe, expect, it } from 'vitest'
import { loadFavourite, saveFavourite } from './prefs'

const store = new Map<string, string>()
beforeEach(() => {
  store.clear()
  ;(globalThis as Record<string, unknown>).localStorage = {
    getItem: (k: string) => store.get(k) ?? null,
    setItem: (k: string, v: string) => void store.set(k, v),
    removeItem: (k: string) => void store.delete(k),
  }
})

describe('favourite club preference', () => {
  it('round-trips and only applies to clubs in the match', () => {
    saveFavourite('ngc')
    expect(loadFavourite(['har', 'ngc'])).toBe('ngc')
    expect(loadFavourite(['kin', 'oak'])).toBe(null)
    saveFavourite(null)
    expect(loadFavourite(['har', 'ngc'])).toBe(null)
  })
  it('never throws when storage is unavailable', () => {
    ;(globalThis as Record<string, unknown>).localStorage = {
      getItem: () => { throw new Error('blocked') }, setItem: () => { throw new Error('blocked') }, removeItem: () => { throw new Error('blocked') },
    }
    expect(() => saveFavourite('ngc')).not.toThrow()
    expect(loadFavourite(['ngc'])).toBe(null)
  })
})
