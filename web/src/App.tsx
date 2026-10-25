import { useEffect, useState } from 'react'
import { Desk } from './pages/Desk'
import { Landing } from './pages/Landing'
import { Overlay } from './pages/Overlay'
import { initialLanguage, saveLanguage, withLanguage } from './prefs'
import { dirOf, type Language } from './languages'

/** Three surfaces: landing (start a match), /desk (the commentator's desk), /overlay (broadcast graphics). */
export default function App() {
  const [lang, setLanguage] = useState<Language>(() => initialLanguage(location.search))
  const setLang = (l: Language) => {
    setLanguage(l)
    saveLanguage(l)
    history.replaceState(history.state, '', withLanguage(location.pathname + location.search, l))
  }
  const matchId = new URLSearchParams(location.search).get('match')
  const path = location.pathname.replace(/\/+$/, '')

  useEffect(() => {
    document.documentElement.lang = lang
    document.documentElement.dir = dirOf(lang)
  }, [lang])

  if (path === '/desk' && matchId) return <Desk matchId={matchId} lang={lang} setLang={setLang} />
  if (path === '/overlay' && matchId) return <Overlay matchId={matchId} lang={lang} />
  return <Landing lang={lang} setLang={setLang} />
}
