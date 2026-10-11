import { useEffect, useMemo, useState } from 'react'
import { localDigits } from '../digits'
import { useMatch } from '../api'
import { Celebration, Crest, Evidence, KindIcon, ZoneMap } from '../components/Shared'
import { Recaps, Stats } from '../components/Panels'
import { KIND_LABELS, LANGUAGE_NAMES, t } from '../i18n'
import { kitColors } from '../colors'
import { scoreboardSides } from '../scoreboard'
import { loadFavourite, saveFavourite } from '../prefs'
import { mirrorFor } from '../zones'
import type { Language, Overlay, Profile } from '../types'

type Tab = 'live' | 'stats' | 'recap' | 'me'

function MomentCard({ o, color, names, lang }: { o: Overlay; color: string; names: Record<string, string>; lang: Language }) {
  const [open, setOpen] = useState(false)
  return (
    <article className={`moment-card k-${o.kind}`} dir={o.direction} data-testid="feed-item" style={{ '--team': color } as React.CSSProperties}>
      <div className="moment-minute">{localDigits(o.minute, lang)}'</div>
      <div className="moment-body">
        <div className="moment-kind"><KindIcon kind={o.kind} /> {KIND_LABELS[lang][o.kind] ?? o.kind}
          {o.source === 'ai' && <span className="ai-tag">AI</span>}
        </div>
        <h3>{localDigits(o.headline, lang)}</h3>
        <p>{localDigits(o.body, lang)}</p>
        <button className="why" onClick={() => setOpen(v => !v)} aria-expanded={open}>{t(lang, 'why')}</button>
        {open && <Evidence overlay={o} names={names} lang={lang} />}
      </div>
    </article>
  )
}

export function FanApp({ matchId, lang, setLang }: { matchId: string; lang: Language; setLang: (l: Language) => void }) {
  const [clubId, setClubId] = useState<string | null>(null)
  const [playerId, setPlayerId] = useState<string | null>(null)
  const profile: Profile = { mode: 'fan', language: lang, club_id: clubId, player_id: playerId }
  const { state, dispatch } = useMatch(matchId, profile)
  const [tab, setTab] = useState<Tab>('live')
  const h = state.hello
  const colors = useMemo(() => (h ? kitColors(h.home, h.away) : {}), [h])
  const names = useMemo(() => {
    const out: Record<string, string> = {}
    if (h) for (const c of [h.home, h.away]) {
      out[c.id] = c.short_name
      for (const p of [...c.lineup, ...c.bench]) out[p.id] = p.name
    }
    return out
  }, [h])

  // Bring the recap forward once it arrives at full time.
  useEffect(() => { if (state.recaps.full_time) setTab(tb => (tb === 'live' ? 'recap' : tb)) }, [state.recaps.full_time])

  const possessionClub = h && state.possession ? (state.possession === h.home.id ? h.home : h.away) : null
  const board = h ? scoreboardSides(h.home, h.away, state.score, clubId) : null

  // Restore the remembered favourite once we know which clubs are playing.
  const homeId = h?.home.id
  const awayId = h?.away.id
  useEffect(() => {
    if (homeId && awayId) setClubId(c => c ?? loadFavourite([homeId, awayId]))
  }, [homeId, awayId])
  const chooseClub = (id: string | null) => {
    setClubId(id)
    saveFavourite(id)
  }
  // The wash uses the club's kit colour, the colour fans associate with them.
  const wash = possessionClub && state.possession ? colors[state.possession] : '#37003c'

  const clock = state.status === 'finished' ? t(lang, 'fullTime') : state.status === 'live' ? `${localDigits(state.minute, lang)}'` : t(lang, 'kickOffSoon')

  return (
    <div className="phone-stage">
      <div className="phone" dir={lang === 'ar' ? 'rtl' : 'ltr'} data-testid="fan-app">
        <section className="hero" style={{ '--wash': wash } as React.CSSProperties}
          data-testid="hero" data-possession={state.possession ?? ''}>
          <div className="hero-top">
            <span className="wordmark small"><span className="mark" aria-hidden /> {t(lang, 'appTitle')}</span>
            <span className={`clock-pill${state.status === 'live' ? ' live' : ''}`} data-testid="clock">{clock}</span>
          </div>
          {board && (
            <div className="hero-score" dir="ltr">
              <div className={`side${board.pinned ? ' pinned' : ''}`} data-testid="hero-left">
                <Crest club={board.left.club} size={46} />
                <span className="club-name">
                  {board.left.club.short_name}
                  {board.pinned && (
                    <svg className="fav-star" data-testid="fav-badge" role="img" aria-label={t(lang, 'yourClub')}
                      viewBox="0 0 24 24" width="13" height="13">
                      <title>{t(lang, 'yourClub')}</title>
                      <path d="M12 2.8l2.8 5.9 6.4.8-4.7 4.4 1.2 6.4L12 17.2l-5.7 3.1 1.2-6.4-4.7-4.4 6.4-.8z" />
                    </svg>
                  )}
                </span>
              </div>
              <div className="big-score" data-testid="score">{localDigits(board.left.goals, lang)}<i>–</i>{localDigits(board.right.goals, lang)}</div>
              <div className="side" data-testid="hero-right">
                <Crest club={board.right.club} size={46} /><span>{board.right.club.short_name}</span>
              </div>
            </div>
          )}
          {possessionClub && (
            <p className="possession-line"><span className="dot" />{possessionClub.short_name} {t(lang, 'inPossession')}</p>
          )}
        </section>

        <section className="sheet">
          {tab === 'live' && (
            <>
              <ZoneMap state={state} colors={colors} lang={lang}
                mirror={h ? mirrorFor(clubId, state.period, h.home.id) : false} />
              <div className="timeline">
                {!state.feed.length && <p className="empty">{t(lang, 'emptyFeed')}</p>}
                {state.feed.map(o => (
                  <MomentCard key={o.id} o={o} color={(o.team_id && colors[o.team_id]) || '#37003c'} names={names} lang={lang} />
                ))}
              </div>
            </>
          )}
          {tab === 'stats' && <div className="sheet-pad"><Stats state={state} colors={colors} lang={lang} names={names} topTeam={clubId} /></div>}
          {tab === 'recap' && <div className="sheet-pad"><Recaps state={state} lang={lang} /></div>}
          {tab === 'me' && h && (
            <div className="sheet-pad settings" data-testid="me">
              <h2>{t(lang, 'settings')}</h2>
              <div className="setting">
                <span>{t(lang, 'language')}</span>
                <div className="segmented light" role="group" aria-label={t(lang, 'language')}>
                  {(['en', 'es', 'ar'] as const).map(l => (
                    <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{LANGUAGE_NAMES[l]}</button>
                  ))}
                </div>
              </div>
              <div className="setting">
                <span>{t(lang, 'favouriteClub')}</span>
                <div className="club-pick">
                  {[h.home, h.away].map(c => (
                    <button key={c.id} aria-pressed={clubId === c.id} onClick={() => chooseClub(clubId === c.id ? null : c.id)}>
                      <Crest club={c} size={28} /> {c.short_name}
                    </button>
                  ))}
                </div>
              </div>
              <label className="setting">
                <span>{t(lang, 'followPlayer')}</span>
                <select value={playerId ?? ''} onChange={e => setPlayerId(e.target.value || null)}>
                  <option value="">{t(lang, 'none')}</option>
                  {[h.home, h.away].map(c => (
                    <optgroup key={c.id} label={c.name}>
                      {[...c.lineup, ...c.bench].map(p => <option key={p.id} value={p.id}>{p.number}. {p.name}</option>)}
                    </optgroup>
                  ))}
                </select>
              </label>
              <p className="fictional dark">{t(lang, 'fictional')}</p>
            </div>
          )}
        </section>

        <nav className="tabbar" aria-label="Sections">
          {([['live', 'live2'], ['stats', 'stats'], ['recap', 'recap'], ['me', 'me']] as const).map(([id, key]) => (
            <button key={id} aria-current={tab === id ? 'page' : undefined} onClick={() => setTab(id)}>
              <span className={`tab-icon ${id}`} aria-hidden />
              {t(lang, key)}
              {id === 'recap' && (state.recaps.half_time || state.recaps.full_time) && <i className="badge-dot" />}
            </button>
          ))}
        </nav>

        <Celebration state={state} colors={colors} names={names} lang={lang} onDone={() => dispatch({ type: 'animation_done' })} />
      </div>
    </div>
  )
}
