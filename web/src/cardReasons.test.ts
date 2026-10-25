import { describe, expect, it } from 'vitest'
import { cardReasonText } from './cardReasons'
import { LANGUAGES } from './languages'

const REASONS = ['late_tackle', 'tactical_foul', 'holding', 'handball', 'dissent', 'time_wasting',
  'serious_foul_play', 'denied_goal_chance', 'violent_conduct', 'offensive_language']

describe('card reasons (F-6a)', () => {
  it('names the fouled player when there is one', () => {
    expect(cardReasonText('late_tackle', 'Kai Greaves', 'en')).toBe('Late tackle on Kai Greaves')
    expect(cardReasonText('late_tackle', null, 'en')).toBe('Late tackle')
    expect(cardReasonText('dissent', null, 'en')).toBe('Dissent towards the referee')
  })
  it('says when it was a second yellow', () => {
    expect(cardReasonText('time_wasting', null, 'en', true)).toBe('Second yellow: Time-wasting')
  })
  it('returns null for an unknown reason', () => {
    expect(cardReasonText(undefined, null, 'en')).toBeNull()
    expect(cardReasonText('made_up', null, 'en')).toBeNull()
  })
  it.each(LANGUAGES)('every reason has wording in %s', lang => {
    for (const r of REASONS) {
      for (const v of ['Kai Greaves', null]) {
        const text = cardReasonText(r, v, lang)
        expect(text, r).toBeTruthy()
        expect(text).not.toMatch(/undefined|\{/)
      }
    }
  })
})
