import { useEffect, useMemo, useState } from 'react'
import { useMatch } from './api'
import { teamColors } from './colors'
import { Controls } from './components/Controls'
import { Agents, Feed, Momentum, Recaps, Stats } from './components/Panels'
import { Pitch } from './components/Pitch'
import { Setup } from './components/Setup'
import { t, type StringKey } from './i18n'
import type { Profile } from './types'

type Tab = 'feed' | 'stats' | 'agents' | 'recap'
const TABS: [Tab, StringKey][] = [['feed', 'feed'], ['stats', 'stats'], ['agents', 'agents'], ['recap', 'recap']]

function initialMatchId(): string | null {
  return new URLSearchParams(location.search).get('match')
}

export default function App() {
  const [matchId, setMatchId] = useState<string | null>(initialMatchId)
  const [profile, setProfile] = useState<Profile>({ mode: 'fan', language: 'en', club_id: null, player_id: null })
  const [tab, setTab] = useState<Tab>('feed')
  const { state, connected } = useMatch(matchId, profile)
  const lang = profile.language
  const hello = state.hello

  useEffect(() => {
    document.documentElement.lang = lang
    document.documentElement.dir = lang === 'ar' ? 'rtl' : 'ltr'
  }, [lang])

  const colors = useMemo(() => (hello ? teamColors(hello.home, hello.away) : {}), [hello])
  const names = useMemo(() => {
    const out: Record<string, string> = {}
    if (hello) for (const c of [hello.home, hello.away]) {
      out[c.id] = c.short_name
      for (const p of [...c.lineup, ...c.bench]) out[p.id] = p.name
    }
    return out
  }, [hello])

  const start = (id: string) => {
    setMatchId(id)
    history.replaceState(null, '', `?match=${id}`)
  }

  const statusLabel = state.status === 'finished' ? t(lang, 'fullTime')
    : state.status === 'live' ? `${state.minute}'` : t(lang, 'waiting')

  return (
    <div className="app" dir={lang === 'ar' ? 'rtl' : 'ltr'}>
      <header className="topbar">
        <div className="brand">
          <img src="/favicon.svg" width={26} height={26} alt="" />
          <span>{t(lang, 'appTitle')}</span>
          <small>{t(lang, 'tagline')}</small>
        </div>
        <span className="spacer" />
        {matchId && (
          <button className="ghost" onClick={() => { setMatchId(null); history.replaceState(null, '', '/') }}>
            {t(lang, 'newMatch')}
          </button>
        )}
      </header>

      {!matchId && <Setup lang={lang} onStart={start} />}

      {matchId && hello && (
        <>
          <section className="scoreboard" aria-label="Scoreboard">
            <div className="team home">
              <span className="crest" style={{ background: colors[hello.home.id] }} />
              <span>{hello.home.short_name}</span>
            </div>
            <div className="score-box">
              <div className="score" data-testid="score">{state.score[0]} – {state.score[1]}</div>
              <div className="clock" data-testid="clock">
                {state.status === 'live' && <span className="live-dot" aria-hidden />}
                <span>{statusLabel}</span>
              </div>
            </div>
            <div className="team away">
              <span>{hello.away.short_name}</span>
              <span className="crest" style={{ background: colors[hello.away.id] }} />
            </div>
          </section>

          <main className="main">
            <div>
              <Pitch state={state} colors={colors} names={names} lang={lang} />
              <Momentum state={state} hello={hello} colors={colors} lang={lang} />
            </div>
            <aside className="side">
              <Controls profile={profile} onChange={setProfile} hello={hello} />
              <section className="card">
                <div className="tabs" role="tablist">
                  {TABS.map(([id, key]) => (
                    <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
                      {t(lang, key)}{id === 'agents' && state.counts.published ? ` · ${state.counts.published}` : ''}
                    </button>
                  ))}
                </div>
                <div className="tab-body" role="tabpanel">
                  {tab === 'feed' && <Feed state={state} colors={colors} names={names} lang={lang} />}
                  {tab === 'stats' && <Stats state={state} colors={colors} lang={lang} />}
                  {tab === 'agents' && <Agents state={state} lang={lang} />}
                  {tab === 'recap' && <Recaps state={state} lang={lang} />}
                </div>
              </section>
            </aside>
          </main>
        </>
      )}

      {matchId && !hello && (
        <p className="empty" role="status">{connected ? '…' : t(lang, 'waiting')}</p>
      )}
    </div>
  )
}
