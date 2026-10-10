import { useEffect, useState } from 'react'
import { Desk } from './pages/Desk'
import { FanApp } from './pages/FanApp'
import { Landing } from './pages/Landing'
import type { Language } from './types'

function initialLanguage(): Language {
  const l = new URLSearchParams(location.search).get('lang')
  return l === 'es' || l === 'ar' ? l : 'en'
}

/** Three surfaces: landing (start a match), /fan (phone app), /desk (commentator laptop). */
export default function App() {
  const [lang, setLang] = useState<Language>(initialLanguage)
  const matchId = new URLSearchParams(location.search).get('match')
  const path = location.pathname.replace(/\/+$/, '')

  useEffect(() => {
    document.documentElement.lang = lang
    document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr'
  }, [lang])

  if (path === '/fan' && matchId) return <FanApp matchId={matchId} lang={lang} setLang={setLang} />
  if (path === '/desk' && matchId) return <Desk matchId={matchId} lang={lang} setLang={setLang} />
  return <Landing lang={lang} setLang={setLang} />
}
