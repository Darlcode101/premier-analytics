// DK-12: thirteen languages do not fit as buttons, so the choice is a dropdown, each language named in itself.
import { t } from '../i18n'
import { LANGUAGE_NAMES, LANGUAGES, type Language } from '../languages'

export function LanguageSelect({ lang, setLang, className }: { lang: Language; setLang: (l: Language) => void; className: string }) {
  return (
    <select className={className} data-testid="lang-select" aria-label={t(lang, 'language')} value={lang}
      onChange={e => setLang(e.target.value as Language)}>
      {LANGUAGES.map(l => <option key={l} value={l} lang={l}>{LANGUAGE_NAMES[l]}</option>)}
    </select>
  )
}
