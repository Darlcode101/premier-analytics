import { useEffect, useMemo, useState } from 'react'
import { localDigits } from '../digits'
import { useMatch } from '../api'
import { Celebration, Crest, Evidence, KindIcon, ZoneMap } from '../components/Shared'
import { Recaps, Stats } from '../components/Panels'
import { KIND_LABELS, LANGUAGE_NAMES, t } from '../i18n'
import { kitColors } from '../colors'
import { involves, scoreboardSides } from '../scoreboard'
import { scorers } from '../desk'
import { loadFavourite, saveFavourite } from '../prefs'
import { mirrorFor } from '../zones'
import type { Language, Overlay, Profile } from '../types'

type Tab = 'live' | 'stats' | 'recap' | 'me'

function MomentCard({ o, color, names, lang, mine }: { o: Overlay; color: string; names: Record<string, string>; lang: Language; mine: boolean }) {
  const [open, setOpen] = useState(false)
  return (
    <article className={`moment-card k-${o.kind}${mine ? ' mine' : ''}`} dir={o.direction} data-testid="feed-item"
      data-mine={mine ? 'true' : undefined} style={{ '--team': color } as React.CSSProperties}>
      <div className="moment-minute">{localDigits(o.minute, lang)}'</div>
      <div className="moment-body">
        <div className="moment-kind"><KindIcon kind={o.kind} /> {KIND_LABELS[lang][o.kind] ?? o.kind}
          {o.source === 'ai' && <span className="ai-tag">AI</span>}
          {mine && <span className="mine-tag"><i aria-hidden />{t(lang, 'yourPlayer')}</span>}
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
  // Possession is shown the way other sports apps do it: a small ball beside the team that has it.
  const ballMark = (clubId_: string) => state.possession === clubId_ && (
    <svg className="poss-ball" data-testid="possession-ball" viewBox="0 0 16 16" width="14" height="14" role="img"
      aria-label={t(lang, 'inPossession')}>
      <circle cx="8" cy="8" r="7" />
      <path d="M8 4.2l2.6 1.9-1 3H6.4l-1-3z M8 1v3.2 M10.6 6.1l3.6-1 M9.6 9.1l2 2.9 M6.4 9.1l-2 2.9 M5.4 6.1l-3.6-1" />
    </svg>
  )

  // Stoppage time is shown as the regular minute plus a red "+n", as on broadcast scorebugs.
  const [base, added] = state.minute.split('+')
  const clock = state.status === 'finished' ? t(lang, 'fullTime') : state.status === 'live' ? `${localDigits(state.minute, lang)}'` : t(lang, 'kickOffSoon')

  return (
    <div className="phone-stage">
      <div className="phone" dir={lang === 'ar' ? 'rtl' : 'ltr'} data-testid="fan-app">
        <section className="hero" data-testid="hero" data-possession={state.possession ?? ''}>
          <div className="hero-top">
            <span className="wordmark small"><span className="mark" aria-hidden /> {t(lang, 'appTitle')}</span>
          </div>
          {board && (
            <div className="hero-score" dir="ltr">
              <div className={`side${board.pinned ? ' pinned' : ''}`} data-testid="hero-left">
                <Crest club={board.left.club} size={46} />
                <span className="club-name">
                  {ballMark(board.left.club.id)}
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
              <div className="score-col">
                <span className="score-clock" data-testid="clock">
                  {state.status === 'live' && added
                    ? <>{localDigits(`${base}'`, lang)}<b className="added-time" data-testid="added-time">+{localDigits(added, lang)}</b></>
                    : clock}
                </span>
                <div className="big-score" data-testid="score">{localDigits(board.left.goals, lang)}<i>–</i>{localDigits(board.right.goals, lang)}</div>
              </div>
              <div className="side" data-testid="hero-right">
                <Crest club={board.right.club} size={46} />
                <span className="club-name">{board.right.club.short_name}{ballMark(board.right.club.id)}</span>
              </div>
            </div>
          )}
          {board && (state.incidents.some(i => i.kind === 'goal')) && (
            <div className="hero-scorers" dir="ltr">
              {[board.left.club, board.right.club].map((c, i) => (
                <ul key={c.id} className={i ? 'right' : 'left'} data-testid={`scorers-${i ? 'right' : 'left'}`}>
                  {scorers(state.incidents, c.id).map(s => (
                    <li key={s.player_id} dir="auto">
                      {(names[s.player_id] ?? '').split(' ').slice(-1)[0]} {s.minutes.map(m => `${localDigits(m, lang)}'`).join(', ')}
                    </li>
                  ))}
                </ul>
              ))}
            </div>
          )}
          {possessionClub && (
            <p className="possession-line">
              <span className="dot" style={{ background: colors[possessionClub.id] }} />{possessionClub.short_name} {t(lang, 'inPossession')}
            </p>
          )}
          {playerId && names[playerId] && (
            <p className="following-chip" data-testid="following">
              <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden><circle cx="12" cy="8" r="4" /><path d="M4 21c0-4.4 3.6-7 8-7s8 2.6 8 7z" /></svg>
              {t(lang, 'following')} <b dir="auto">{names[playerId]}</b>
            </p>
          )}
        </section>

        <section className="sheet">
          {tab === 'live' && (
            <>
              <ZoneMap state={state} colors={colors} lang={lang} layout="row"
                mirror={h ? mirrorFor(clubId, state.period, h.home.id) : false} />
              <div className="timeline">
                {!state.feed.length && <p className="empty">{t(lang, 'emptyFeed')}</p>}
                {state.feed.map(o => (
                  <MomentCard key={o.id} o={o} color={(o.team_id && colors[o.team_id]) || '#37003c'} names={names} lang={lang}
                    mine={involves(o, playerId)} />
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
              {playerId && names[playerId] && (
                <p className="follow-confirm" data-testid="follow-confirm">
                  {t(lang, 'followConfirm').replace('{name}', names[playerId])}
                </p>
              )}
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
