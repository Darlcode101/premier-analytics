// On-screen overlay (OV-*): a transparent page for a browser source over video. A small scorebug and a
// lower third that pops up with the latest graphic.
import { useEffect, useMemo, useState } from 'react'
import { useMatch } from '../api'
import { formatClock, useMatchClock } from '../clock'
import { kitColors } from '../colors'
import { localDigits } from '../digits'
import { KIND_LABELS, t } from '../i18n'
import { emptyThird, stepThird } from '../overlayQueue'
import type { Language, Mode, Profile } from '../types'

export function Overlay({ matchId, lang }: { matchId: string; lang: Language }) {
  const params = new URLSearchParams(location.search)
  const mode: Mode = params.get('mode') === 'analyst' ? 'analyst' : 'fan'
  const showBug = params.get('bug') !== '0'
  const profile: Profile = { mode, language: lang, club_id: null, player_id: null }
  const { state } = useMatch(matchId, profile)
  const h = state.hello
  const colors = useMemo(() => (h ? kitColors(h.home, h.away) : {}), [h])

  // Transparent page so it can sit over video.
  useEffect(() => {
    document.documentElement.classList.add('overlay-page')
    return () => document.documentElement.classList.remove('overlay-page')
  }, [])

  const [third, setThird] = useState(emptyThird)
  useEffect(() => {
    const tick = () => setThird(s => stepThird(s, state.feed, performance.now()))
    const first = window.setTimeout(tick, 0)
    const every = window.setInterval(tick, 250)
    return () => { window.clearTimeout(first); window.clearInterval(every) }
  }, [state.feed])

  const inPlay = state.status === 'live' && state.lastEvent?.kind !== 'period_end'
  const clockMs = useMatchClock(state.clockMs, h?.speed ?? 1, inPlay)
  const { main, added } = formatClock(clockMs, state.period)
  const o = third.current

  return (
    <div className="ov" dir={lang === 'ar' ? 'rtl' : 'ltr'} data-testid="overlay">
      {showBug && h && (
        <div className="ov-bug" data-testid="scorebug" dir="ltr">
          <span className="ov-team"><i style={{ background: colors[h.home.id] }} />{h.home.id.toUpperCase()}</span>
          <span className="ov-score">{localDigits(state.score[0], lang)}<em>–</em>{localDigits(state.score[1], lang)}</span>
          <span className="ov-team">{h.away.id.toUpperCase()}<i style={{ background: colors[h.away.id] }} /></span>
          <span className="ov-clock" data-testid="clock">
            {state.status === 'finished' ? t(lang, 'fullTime')
              : state.lastEvent?.kind === 'period_end' && state.period === 1 ? t(lang, 'halfTime')
              : localDigits(main, lang)}
            {state.status === 'live' && added && <b>{localDigits(added, lang)}</b>}
          </span>
        </div>
      )}
      <div className={`ov-third${o ? ' in' : ''}`} data-testid="lower-third" data-state={o ? 'in' : 'out'}
        style={{ '--team': (o?.team_id && colors[o.team_id]) || '#37003c' } as React.CSSProperties} aria-live="polite">
        {o && (
          <>
            <span className="ov-kind">{KIND_LABELS[lang][o.kind] ?? o.kind}{o.minute && <> · {localDigits(`${o.minute}'`, lang)}</>}</span>
            <strong dir={o.direction}>{localDigits(o.headline, lang)}</strong>
            <span className="ov-body" dir={o.direction}>{localDigits(o.body, lang)}</span>
          </>
        )}
      </div>
    </div>
  )
}
