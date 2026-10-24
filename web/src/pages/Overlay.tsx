// On-screen overlay (OV-*): a transparent page for a browser source over video. A small scorebug and a
// lower third that pops up with the latest graphic.
import { useEffect, useMemo, useState } from 'react'
import { useMatch } from '../api'
import { formatClock, useMatchClock } from '../clock'
import { kitColors } from '../colors'
import { localDigits } from '../digits'
import { KIND_LABELS, t } from '../i18n'
import { capFor, emptyThird, fitText, stepThird } from '../overlayQueue'
import type { Language, Profile } from '../types'

export function Overlay({ matchId, lang }: { matchId: string; lang: Language }) {
  const params = new URLSearchParams(location.search)
  const showBug = params.get('bug') !== '0'
  // DK-9: viewers at home get plain broadcast wording (the backend's 'fan' audience); there is no mode choice.
  const profile: Profile = { mode: 'fan', language: lang, club_id: null, player_id: null }
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

  // The pop-up's text is capped to what fits its box: two lines each, measured from the screen width.
  const [width, setWidth] = useState(() => window.innerWidth)
  useEffect(() => {
    const onResize = () => setWidth(window.innerWidth)
    window.addEventListener('resize', onResize)
    return () => window.removeEventListener('resize', onResize)
  }, [])
  const textWidth = Math.min(760, 0.7 * width) - 42  // box max width minus padding and team stripe
  const headline = o ? fitText(o.headline, capFor(textWidth, 30, 2, 0.45)) : ''
  const body = o ? fitText(o.body, capFor(textWidth, 16, 2)) : ''

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
            <strong dir={o.direction} data-testid="lower-third-headline">{localDigits(headline, lang)}</strong>
            <span className="ov-body" dir={o.direction} data-testid="lower-third-body">{localDigits(body, lang)}</span>
          </>
        )}
      </div>
    </div>
  )
}
