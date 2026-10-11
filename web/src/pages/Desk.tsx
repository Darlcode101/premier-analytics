import { useMemo, useState } from 'react'
import { useMatch } from '../api'
import { teamColors } from '../colors'
import { Agents, Momentum, Recaps, Stats } from '../components/Panels'
import { Crest, Evidence, KindIcon, ZoneMap } from '../components/Shared'
import { KIND_LABELS, LANGUAGE_NAMES, t } from '../i18n'
import type { Language, Overlay, Profile } from '../types'

type Tab = 'stats' | 'agents' | 'recap'

function TalkingPoint({ o, color, names, lang }: { o: Overlay; color: string; names: Record<string, string>; lang: Language }) {
  const [open, setOpen] = useState(false)
  return (
    <article className="talking-point" dir={o.direction} data-testid="feed-item" style={{ '--team': color } as React.CSSProperties}>
      <header>
        <span className="tp-minute">{o.minute}'</span>
        <span className="tp-kind"><KindIcon kind={o.kind} size={14} /> {KIND_LABELS[lang][o.kind] ?? o.kind}</span>
        {o.source === 'ai' ? <span className="ai-tag">✦ AI</span> : <span className="instant-tag">{t(lang, 'instant')}</span>}
        <button className="why" onClick={() => setOpen(v => !v)} aria-expanded={open}>{t(lang, 'why')}</button>
      </header>
      <h3>{o.headline}</h3>
      <p>{o.body}</p>
      {open && <Evidence overlay={o} names={names} lang={lang} />}
    </article>
  )
}

export function Desk({ matchId, lang, setLang }: { matchId: string; lang: Language; setLang: (l: Language) => void }) {
  const profile: Profile = { mode: 'analyst', language: lang, club_id: null, player_id: null }
  const { state } = useMatch(matchId, profile)
  const [tab, setTab] = useState<Tab>('stats')
  const h = state.hello
  const colors = useMemo(() => (h ? teamColors(h.home, h.away) : {}), [h])
  const names = useMemo(() => {
    const out: Record<string, string> = {}
    if (h) for (const c of [h.home, h.away]) {
      out[c.id] = c.short_name
      for (const p of [...c.lineup, ...c.bench]) out[p.id] = p.name
    }
    return out
  }, [h])
  const clock = state.status === 'finished' ? t(lang, 'fullTime') : state.status === 'live' ? `${state.minute}'` : t(lang, 'kickOffSoon')
  const possessionClub = h && state.possession ? (state.possession === h.home.id ? h.home : h.away) : null

  return (
    <div className="desk" dir={lang === 'ar' ? 'rtl' : 'ltr'} data-testid="desk">
      <header className="desk-bar">
        <span className="wordmark"><span className="mark" aria-hidden /> {t(lang, 'deskTitle')}</span>
        {h && (
          <div className="desk-score">
            <Crest club={h.home} size={30} /><b>{h.home.short_name}</b>
            <span className="big" data-testid="score" dir="ltr">{state.score[0]} – {state.score[1]}</span>
            <b>{h.away.short_name}</b><Crest club={h.away} size={30} />
            <span className={`clock-pill${state.status === 'live' ? ' live' : ''}`} data-testid="clock">{clock}</span>
          </div>
        )}
        <div className="lang-switch" role="group" aria-label={t(lang, 'language')}>
          {(['en', 'es', 'ar'] as const).map(l => (
            <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{LANGUAGE_NAMES[l]}</button>
          ))}
        </div>
      </header>

      {h && (
        <main className="desk-grid">
          <section className="desk-col points" aria-labelledby="tp-title">
            <h2 id="tp-title">{t(lang, 'talkingPoints')}</h2>
            {!state.feed.length && <p className="empty">{t(lang, 'emptyFeed')}</p>}
            {state.feed.map(o => (
              <TalkingPoint key={o.id} o={o} color={(o.team_id && colors[o.team_id]) || 'var(--pl-green)'} names={names} lang={lang} />
            ))}
          </section>

          <section className="desk-col centre">
            <div className="on-air" data-testid="on-air"
              style={{ '--wash': possessionClub ? possessionClub.colors[0] : '#37003c' } as React.CSSProperties}>
              <span className="on-air-tag">● {t(lang, 'onAir')}</span>
              {state.screen.map(o => (
                <div key={o.id} className={`air-gfx ${o.slot}`} dir={o.direction}
                  style={{ '--team': (o.team_id && colors[o.team_id]) || 'var(--pl-green)' } as React.CSSProperties}
                  data-testid={`overlay-${o.slot}`}>
                  <span className="k">{KIND_LABELS[lang][o.kind] ?? o.kind}</span>
                  <strong>{o.headline}</strong>
                  <span className="b">{o.body}</span>
                </div>
              ))}
            </div>
            <div className="desk-pair">
              <ZoneMap state={state} colors={colors} lang={lang} compact />
              <Momentum state={state} hello={h} colors={colors} lang={lang} />
            </div>
          </section>

          <section className="desk-col side">
            <div className="tabs" role="tablist">
              {(['stats', 'agents', 'recap'] as const).map(id => (
                <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)}>
                  {t(lang, id)}{id === 'agents' && state.counts.published ? ` · ${state.counts.published}` : ''}
                </button>
              ))}
            </div>
            <div className="tab-body">
              {tab === 'stats' && <Stats state={state} colors={colors} lang={lang} names={names} />}
              {tab === 'agents' && <Agents state={state} lang={lang} />}
              {tab === 'recap' && <Recaps state={state} lang={lang} />}
            </div>
          </section>
        </main>
      )}
      <footer className="desk-foot">{t(lang, 'fictional')}</footer>
    </div>
  )
}
