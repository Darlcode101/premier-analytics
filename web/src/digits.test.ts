import { describe, expect, it } from 'vitest'
import { localDigits } from './digits'

describe('localDigits', () => {
  it('leaves English and Spanish alone', () => {
    expect(localDigits("67' · xG 0.38 · 62%", 'en')).toBe("67' · xG 0.38 · 62%")
    expect(localDigits('2-1', 'es')).toBe('2-1')
  })
  it('uses Eastern Arabic digits, decimal separator and percent sign in Arabic', () => {
    expect(localDigits('2-1', 'ar')).toBe('٢-١')
    expect(localDigits('xG 0.38', 'ar')).toBe('xG ٠٫٣٨')
    expect(localDigits('62%', 'ar')).toBe('٦٢٪')
    expect(localDigits("45+2'", 'ar')).toBe("٤٥+٢'")
  })
  it('only treats a dot between digits as a decimal point', () => {
    expect(localDigits('Kai Greaves scores. 3 shots.', 'ar')).toBe('Kai Greaves scores. ٣ shots.')
  })
  it('accepts numbers', () => {
    expect(localDigits(10, 'ar')).toBe('١٠')
  })
})
