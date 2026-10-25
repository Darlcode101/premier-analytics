// DK-12: the ten catalogued languages. Each file holds every string the hand-written EN/ES/AR tables have;
// languages.test.ts checks the keys and {placeholders} match English.
import type { CardReason } from '../cardReasons'
import type { DeskKey } from '../deskText'
import type { StringKey } from '../i18n'
import type { Language } from '../languages'
import de from './de.json'
import fr from './fr.json'
import hi from './hi.json'
import it from './it.json'
import ja from './ja.json'
import ko from './ko.json'
import nl from './nl.json'
import pt from './pt.json'
import tr from './tr.json'
import zh from './zh.json'

/** One form for every count, or singular and plural where the language has them. */
export type Plural = string | { one: string; other: string }
export type CataloguedLanguage = 'fr' | 'de' | 'it' | 'pt' | 'nl' | 'tr' | 'zh' | 'ja' | 'ko' | 'hi'

export interface WhyTemplates {
  chance: Plural; penalty: Plural; ifScored: string; outcome: Record<string, string>; goal: Record<string, string>
  setPiece: Record<string, string>; brace: Plural; speed: string; yellow: string; red: Plural; pass: string
  shots: Plural; territory: string; goalsInSpell: Plural; sub: string; halfShots: string; betterChances: string
  evenChances: string; moreBall: string
}

export interface Catalogue {
  ui: Record<StringKey, string>
  desk: Record<DeskKey, string>
  facts: Record<string, string>
  kinds: Record<string, string>
  contexts: Record<string, string>
  why: WhyTemplates
  cards: Record<CardReason, [withVictim: string, alone: string]>
  secondYellow: string
  explain: { onTop: string; even: string; quiet: string; shots: Plural; passes: Plural; regains: Plural }
}

export const CATALOGUES = { fr, de, it, pt, nl, tr, zh, ja, ko, hi } as unknown as Record<CataloguedLanguage, Catalogue>

export function fromCatalogues<T>(pick: (c: Catalogue, lang: CataloguedLanguage) => T): Record<CataloguedLanguage, T> {
  return Object.fromEntries(Object.entries(CATALOGUES).map(([l, c]) => [l, pick(c, l as CataloguedLanguage)])) as
    Record<CataloguedLanguage, T>
}

/** "{n} shots" with n filled in; unknown placeholders are left as they are, so a test can spot them. */
export const fill = (template: string, vars: Record<string, string | number>) =>
  template.replace(/\{(\w+)\}/g, (m, k: string) => (k in vars ? String(vars[k]) : m))

const rules = new Map<string, Intl.PluralRules>()

export function plural(p: Plural, n: number, lang: Language): string {
  if (typeof p === 'string') return p
  let r = rules.get(lang)
  if (!r) rules.set(lang, r = new Intl.PluralRules(lang))
  return r.select(n) === 'one' ? p.one : p.other
}
