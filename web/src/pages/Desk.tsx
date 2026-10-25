// Commentator desk (CD-1..CD-18): a neutral broadcast console. Everything except talking points
// and recaps is built from match data, so it keeps working with the AI off or down.
import { useEffect, useMemo, useRef, useState } from 'react'
import { askQuestion, startMatch, useMatch } from '../api'
import { teamColors } from '../colors'
import { AttackMomentumChart, Agents, forPeriod, HalfSwitch, Recaps, type Period } from '../components/Panels'
import { Evidence, KindIcon, ZoneMap } from '../components/Shared'
import { PatternPitch } from '../components/PatternPitch'
import {
  boardName, formation, formationLines, incidentInvolves, involves, playerMarkers, scorers, subsUsed, timeline, topPerformers,
  type Markers, type PerformerMetric,
} from '../desk'
import { dt, type DeskKey } from '../deskText'
import { groupKey, subGroups } from '../subs'
import { cardReasonText } from '../cardReasons'
import { cueText, onAirMs, shownState, type LastOnAir } from '../cue'
import { formatClock, useMatchClock } from '../clock'
import { whyLines } from '../why'
import { startListening, type ListenStatus } from '../listen'
import { localDigits } from '../digits'
import { KIND_LABELS, t } from '../i18n'
import { LanguageSelect } from '../components/LanguageSelect'
import type { Action, State } from '../state'
import type {
  AskResult, BriefSide, ClubInfo, SubCard, ClubSeason, ContextCard, Hello, Incident, Language, Overlay, PatternNote, PlayerInfo, PlayerLine, Profile, SourceLink,
  TeamStats,
} from '../types'

const TABS = ['prep', 'stats', 'patterns', 'timeline', 'ask', 'production'] as const  // DK-5
type Tab = typeof TABS[number]
type Side = 'home' | 'away'

interface Ctx {
  lang: Language
  hello: Hello
  colors: Record<string, string>
  names: Record<string, string>
  num: (v: string | number) => string
  focus: string | null                       // DK-4: the player in focus
  setFocus: (id: string | null) => void
}

const Bar = ({ color }: { color: string }) => <i className="cd-bar" style={{ background: color }} aria-hidden />
function Sources({ sources }: { sources: SourceLink[] }) {
  const host = (url: string) => { try { return new URL(url).hostname.replace(/^www\./, '') } catch { return url } }
  return (
    <span className="cd-sources">
      {sources.map(s => <a key={s.url} href={s.url} target="_blank" rel="noopener noreferrer" title={s.title} dir="ltr">{host(s.url)}</a>)}
    </span>
  )
}

function ContextBlock({ c, lang }: { c: ContextCard; lang: Language }) {
  return (
    <div className="cd-context" data-testid="context-card" dir={lang === 'ar' ? 'rtl' : 'ltr'}>
      <span className="cd-context-tag">{dt(lang, 'realWorld')} · {c.topic}</span>
      <p>{localDigits(c.text, lang)}</p>
      <Sources sources={c.sources} />
    </div>
  )
}

const Card = ({ kind }: { kind: 'yellow' | 'red' }) => <i className={`cd-card ${kind}`} data-testid={`card-${kind}`} aria-hidden />

// ---------- header (CD-4) ----------

function TeamHead({ club, side, incidents, ctx, possession }: {
  club: ClubInfo; side: Side; incidents: Incident[]; ctx: Ctx; possession: boolean
}) {
  const reds = incidents.filter(i => (i.kind === 'red' || i.kind === 'second_yellow') && i.team_id === club.id)
  return (
    <div className={`cd-team ${side}`}>
      <div className="cd-team-name"><Bar color={ctx.colors[club.id]} /><span>{club.name}</span>
        {possession && (  /* DK-3: a small ball beside the team on the ball */
          <svg className="cd-poss" data-testid="possession-ball" viewBox="0 0 16 16" width="13" height="13" role="img"
            aria-label={t(ctx.lang, 'inPossession')}>
            <circle cx="8" cy="8" r="7" />
            <path d="M8 4.2l2.6 1.9-1 3H6.4l-1-3z M8 1v3.2 M10.6 6.1l3.6-1 M9.6 9.1l2 2.9 M6.4 9.1l-2 2.9 M5.4 6.1l-3.6-1" />
          </svg>
        )}
      </div>
      <ul className="cd-scorers" data-testid={`scorers-${side}`}>
        {scorers(incidents, club.id).map(s => (
          <li key={s.player_id}>
            <span className="ball" aria-hidden>●</span> {ctx.names[s.player_id] ?? s.player_id}{' '}
            {s.minutes.map((m, i) => <span key={i} className="mins" data-testid="goal-minute">{ctx.num(m)}'</span>)}
          </li>
        ))}
        {reds.map(r => (
          <li key={r.id}><Card kind="red" /> {ctx.names[r.player_id ?? ''] ?? ''} <span className="mins">{ctx.num(r.minute)}'</span></li>
        ))}
      </ul>
    </div>
  )
}

function Header({ state, ctx, setLang }: { state: State; ctx: Ctx; setLang: (l: Language) => void }) {
  const { hello: h, lang } = ctx
  // DK-3: minutes and seconds ticking between events; stoppage time in red, as on broadcast scorebugs.
  const inPlay = state.status === 'live' && state.lastEvent?.kind !== 'period_end'
  const clockMs = useMatchClock(state.clockMs, h.speed ?? 1, inPlay)
  const { main, added } = formatClock(clockMs, state.period)
  const halfTime = state.status === 'live' && state.lastEvent?.kind === 'period_end' && state.period === 1
  const clock = state.status === 'finished' ? t(lang, 'fullTime') : halfTime ? t(lang, 'halfTime')
    : state.status === 'live' && state.lastEvent
      ? <>{ctx.num(main)}{added && <b className="cd-added" data-testid="added-time">{ctx.num(added)}</b>}</>
      : state.status === 'live' ? '0:00' : t(lang, 'kickOffSoon')
  const period = state.status === 'live' ? dt(lang, state.period === 1 ? 'period1' : 'period2') : ''
  const wx = `w_${h.weather.condition}` as DeskKey
  return (
    <header className="cd-head">
      <div className="cd-top">
        <span className="cd-title">{t(lang, 'deskTitle')}</span>
        <div className="cd-scorebox" dir="ltr">
          <TeamHead club={h.home} side="home" incidents={state.incidents} ctx={ctx} possession={state.status === 'live' && state.possession === h.home.id} />
          <div className="cd-scoreline">
            <span className="cd-score" data-testid="score">{ctx.num(state.score[0])} – {ctx.num(state.score[1])}</span>
            <span className="cd-clock-row">
              {state.status === 'live' && <span className="cd-live" aria-hidden />}
              <span className="cd-clock" data-testid="clock">{clock}</span>
              {period && <span className="cd-period">{period}</span>}
            </span>
          </div>
          <TeamHead club={h.away} side="away" incidents={state.incidents} ctx={ctx} possession={state.status === 'live' && state.possession === h.away.id} />
        </div>
        <LanguageSelect className="cd-lang" lang={lang} setLang={setLang} />
      </div>
      <div className="cd-details">
        <span><b>{t(lang, 'venue')}</b> {h.venue}</span>
        <span><b>{dt(lang, 'referee')}</b> {h.referee}</span>
        <span><b>{dt(lang, 'kickoff')}</b> {ctx.num(h.kickoff)}</span>
        <span><b>{dt(lang, 'weather')}</b> {dt(lang, wx) ?? h.weather.condition}, {ctx.num(Math.round(h.weather.temp_c))}°C</span>
        <span className="cd-fictional">{t(lang, 'fictional')}</span>
      </div>
    </header>
  )
}

// ---------- line-ups (CD-5, CD-6, CD-7) ----------

function MarkerIcons({ m, ctx }: { m: Markers | undefined; ctx: Ctx }) {
  if (!m) return null
  return (
    <span className="cd-marks">
      {m.goals.map((g, i) => <span key={i} className="mk goal" title={`${dt(ctx.lang, 'inc_goal')} ${g}'`}>●</span>)}
      {m.assists > 0 && <span className="mk assist">{dt(ctx.lang, 'assistBy')[0].toUpperCase()}{m.assists > 1 ? ctx.num(m.assists) : ''}</span>}
      {m.yellow && <Card kind="yellow" />}
      {m.red && <Card kind="red" />}
      {m.off && <span className="mk off" data-testid="sub-off" title={dt(ctx.lang, 'off')}>▼{ctx.num(m.off)}'</span>}
      {m.on && <span className="mk on" data-testid="sub-on" title={dt(ctx.lang, 'on')}>▲{ctx.num(m.on)}'</span>}
    </span>
  )
}

function PlayerLineView({ line, season, ctx }: { line?: PlayerLine; season?: { goals: number; assists: number }; ctx: Ctx }) {
  const l = line ?? { passes: 0, passes_completed: 0, shots: 0, goals: 0, assists: 0, xg: 0, tackles_won: 0, interceptions: 0, fouls: 0, yellow_cards: 0, red_cards: 0 }
  const acc = l.passes ? Math.round(100 * l.passes_completed / l.passes) : 0
  const rows: [DeskKey, string][] = [
    ['passes', `${ctx.num(l.passes_completed)}/${ctx.num(l.passes)} (${ctx.num(acc)}%)`],
    ['shots', ctx.num(l.shots)], ['xg', ctx.num(l.xg.toFixed(2))], ['goals', ctx.num(l.goals)], ['assists', ctx.num(l.assists)],
    ['tacklesWon', ctx.num(l.tackles_won)], ['interceptions', ctx.num(l.interceptions)], ['fouls', ctx.num(l.fouls)],
  ]
  return (
    <div className="cd-player-line" data-testid="player-line">
      <dl>{rows.map(([k, v]) => <div key={k}><dt>{dt(ctx.lang, k)}</dt><dd>{v}</dd></div>)}</dl>
      {season && (
        <p className="cd-season-line">
          <b>{dt(ctx.lang, 'goalsSeason')}</b> {ctx.num(season.goals)} {dt(ctx.lang, 'goals').toLowerCase()} · {ctx.num(season.assists)} {dt(ctx.lang, 'assists').toLowerCase()}
        </p>
      )}
    </div>
  )
}

function Lineup({ club, side, state, ctx, season }: { club: ClubInfo; side: Side; state: State; ctx: Ctx; season?: ClubSeason }) {
  const [selected, setSelected] = useState<string | null>(null)
  const markers = useMemo(() => playerMarkers(state.incidents), [state.incidents])
  const used = subsUsed(state.incidents, club.id)
  const row = (p: PlayerInfo, testid: string) => {
    const m = markers[p.id]
    const open = selected === p.id
    return (
      <li key={p.id}>
        <button className={`cd-row${m?.booked ? ' booked' : ''}${m?.red ? ' sent-off' : ''}${m?.off ? ' subbed' : ''}${ctx.focus === p.id ? ' focus' : ''}`}
          data-testid={testid} data-booked={m?.booked ? 'true' : 'false'} aria-expanded={open}
          onClick={() => setSelected(open ? null : p.id)} title={m?.booked ? dt(ctx.lang, 'booked') : undefined}>
          <span className="no">{ctx.num(p.number)}</span>
          <span className="nm" title={p.name} dir="auto">{boardName(p.name)}</span>
          <span className="pos">{p.position}</span>
          <MarkerIcons m={m} ctx={ctx} />
        </button>
        {open && <>
          <PlayerLineView line={state.players[p.id]} season={season?.players[p.id]} ctx={ctx} />
          <button className="cd-used cd-focus-btn" data-testid="focus-player" aria-pressed={ctx.focus === p.id}
            onClick={() => ctx.setFocus(ctx.focus === p.id ? null : p.id)}>
            {ctx.focus === p.id ? dt(ctx.lang, 'clearFocus') : `◎ ${dt(ctx.lang, 'focusOn')}`}
          </button>
        </>}
      </li>
    )
  }
  return (
    <section className={`cd-panel cd-lineup ${side}`} data-testid={`lineup-${side}`} dir={ctx.lang === 'ar' ? 'rtl' : 'ltr'}>
      <header className="cd-panel-head">
        <Bar color={ctx.colors[club.id]} />
        <h2 dir="auto">{club.short_name}</h2>
        <span className="cd-formation" data-testid="formation">{formation(club.lineup)}</span>
        <span className="cd-subs">{dt(ctx.lang, 'subs')} <b data-testid="subs-used" dir="ltr">{ctx.num(used)}/{ctx.num(ctx.hello.subs_allowed ?? 5)}</b></span>
      </header>
      <div className="cd-scroll">
        {formationLines(club.lineup).map((line, i) => <ul key={i} className="cd-line">{line.map(p => row(p, 'starter'))}</ul>)}
        <h3 className="cd-sub">{dt(ctx.lang, 'bench')}</h3>
        <ul className="cd-line">{club.bench.map(p => row(p, 'bench-player'))}</ul>
        <p className="cd-hint">{dt(ctx.lang, 'selectPlayer')}</p>
      </div>
    </section>
  )
}

// ---------- how this desk works (DK-7) ----------

const HELP_KEY = 'pa.deskHelp'

function DeskHelp({ lang }: { lang: Language }) {
  const [open, setOpen] = useState(() => {
    try { return localStorage.getItem(HELP_KEY) !== 'closed' } catch { return true }
  })
  const set = (v: boolean) => {
    setOpen(v)
    try { localStorage.setItem(HELP_KEY, v ? 'open' : 'closed') } catch { /* not remembered */ }
  }
  return (
    <div className={`cd-help${open ? ' open' : ''}`} data-testid="desk-help" data-open={open ? 'true' : 'false'}>
      <button className="cd-link cd-help-toggle" onClick={() => set(!open)} aria-expanded={open}>
        ⓘ {dt(lang, 'helpTitle')}
      </button>
      {open && <>
        <ol>
          <li>{dt(lang, 'help1')}</li><li>{dt(lang, 'help2')}</li><li>{dt(lang, 'help3')}</li>
          <li>{dt(lang, 'help4')}</li><li>{dt(lang, 'help5')}</li>
        </ol>
        <button className="cd-used" onClick={() => set(false)} data-testid="help-close">{dt(lang, 'helpClose')}</button>
      </>}
    </div>
  )
}

// ---------- talking points (CD-9, CD-10) ----------

function TalkingPoint({ o, used, next, toggle, ctx, contexts }: {
  o: Overlay; used: boolean; next: boolean; toggle: () => void; ctx: Ctx; contexts: ContextCard[]
}) {
  const [open, setOpen] = useState(false)
  const [simple, setSimple] = useState(false)
  const focused = involves(o, ctx.focus)
  const plain = simple ? whyLines(o, ctx.names, ctx.hello.home.id, ctx.hello.away.id, ctx.lang) : []
  const team = o.team_id ? ctx.hello[o.team_id === ctx.hello.home.id ? 'home' : 'away'] : null
  return (
    <article className={`cd-point${used ? ' used' : ''}${next ? ' next' : ''}${focused ? ' focus' : ''}`} dir={o.direction}
      data-testid="feed-item" data-id={o.id} data-used={used ? 'true' : 'false'} data-focus={focused ? 'true' : undefined}>
      <header>
        <span className="cd-min">{ctx.num(o.minute)}'</span>
        <span className="cd-kind"><KindIcon kind={o.kind} size={13} /> {KIND_LABELS[ctx.lang][o.kind] ?? o.kind}</span>
        {team && <span className="cd-teamtag"><Bar color={ctx.colors[team.id]} />{team.short_name}</span>}
        {o.source === 'ai' ? <span className="ai-tag">AI</span> : <span className="instant-tag">{t(ctx.lang, 'instant')}</span>}
        {next && <span className="cd-next">{dt(ctx.lang, 'sayNext')}</span>}
      </header>
      <h3>{ctx.num(o.headline)}</h3>
      <p>{ctx.num(o.body)}</p>
      {contexts.map(c => <ContextBlock key={c.entry_id} c={c} lang={ctx.lang} />)}
      <footer>
        <button className="cd-link" onClick={() => setOpen(v => !v)} aria-expanded={open}>{t(ctx.lang, 'why')}</button>
        <button className="cd-link" onClick={() => setSimple(v => !v)} aria-expanded={simple} data-testid="say-simply">{dt(ctx.lang, 'sayItSimply')}</button>
        <button className="cd-used" onClick={toggle} aria-pressed={used} aria-label={dt(ctx.lang, 'markUsed')}>
          <span aria-hidden>{used ? '✓' : '○'}</span> {used ? dt(ctx.lang, 'used') : dt(ctx.lang, 'markUsed')}
        </button>
      </footer>
      {simple && (plain.length
        ? <ul className="cd-simple" data-testid="simple-lines">{plain.map((l, i) => <li key={i} dir="auto">{ctx.num(l)}</li>)}</ul>
        : <p className="cd-note">{ctx.num(o.body)}</p>)}
      {open && <Evidence overlay={o} names={ctx.names} lang={ctx.lang} />}
    </article>
  )
}

function TalkingPoints({ state, ctx, toggle, send, dispatch }: {
  state: State; ctx: Ctx; toggle: (ref: string) => void; send: (msg: object) => void; dispatch: (a: Action) => void
}) {
  const [team, setTeam] = useState<string | null>(null)
  const used = state.used
  const feed = team ? state.feed.filter(o => o.team_id === team) : state.feed
  const next = state.cue?.ref ?? null
  const openCount = feed.filter(o => !used.has(o.moment_id)).length
  // PA-6: pattern alerts sit among the talking points at the minute they were spotted.
  const alerts = state.patternAlerts.filter(a => !team || a.team_id === team)
  const items: ({ type: 'alert'; a: (typeof alerts)[number]; at: number } | { type: 'point'; o: Overlay; at: number })[] = [
    ...alerts.map(a => ({ type: 'alert' as const, a, at: a.elapsed_ms })),
    ...feed.map(o => ({ type: 'point' as const, o, at: o.elapsed_in_ms })),
  ].sort((x, y) => y.at - x.at)
  const { home, away } = ctx.hello
  const lang = ctx.lang
  return (
    <section className="cd-panel cd-points" aria-labelledby="tp-title">
      {ctx.focus && (
        <p className="cd-focus-chip" data-testid="focus-chip">
          ◎ {dt(lang, 'focusLabel')}: <b dir="auto">{ctx.names[ctx.focus]}</b>
          <button className="cd-link" onClick={() => ctx.setFocus(null)} aria-label={dt(lang, 'clearFocus')}>×</button>
        </p>
      )}
      <div className="cd-block" data-testid="block-cue">
        <div className="cd-block-row">
          <h2 className="cd-block-title">{dt(lang, 'cueTitle')} <span className="cd-block-hint">{dt(lang, 'cueHint')}</span></h2>
          <DeskHelp lang={lang} />
        </div>
        <OnAirCard state={state} ctx={ctx} toggle={toggle} />
      </div>
      <div className="cd-block" data-testid="block-factcheck">
        <FactCheckPanel state={state} ctx={ctx} send={send} dispatch={dispatch} />
      </div>
      <header className="cd-panel-head" data-testid="block-points">
        <h2 id="tp-title">{t(lang, 'talkingPoints')}</h2>
        <span className="cd-count">{ctx.num(openCount)} {dt(lang, 'open')}</span>
        <div className="cd-chips" role="group">
          {[[null, dt(lang, 'bothTeams')], [home.id, home.short_name], [away.id, away.short_name]].map(([id, label]) => (
            <button key={id ?? 'all'} aria-pressed={team === id} onClick={() => setTeam(id)}>{label}</button>
          ))}
        </div>
      </header>
      <div className="cd-scroll">
        {!feed.length && !alerts.length && <p className="empty">{t(ctx.lang, 'emptyFeed')}</p>}
        {items.map(item => item.type === 'alert' ? <PatternAlert key={item.a.pattern_id} a={item.a} ctx={ctx} /> : (
          <TalkingPoint key={item.o.id} o={item.o} used={used.has(item.o.moment_id)} next={item.o.moment_id === next} toggle={() => toggle(item.o.moment_id)} ctx={ctx}
            contexts={state.contexts.filter(c => c.moment_id === item.o.moment_id && c.language === ctx.lang)} />
        ))}
      </div>
    </section>
  )
}

/** FC-1..FC-3: listen to (or type) what the commentator says; flag only clear errors, with the right number. */
function FactCheckPanel({ state, ctx, send, dispatch }: { state: State; ctx: Ctx; send: (msg: object) => void; dispatch: (a: Action) => void }) {
  const [status, setStatus] = useState<ListenStatus>('off')
  const [heard, setHeard] = useState('')
  const [text, setText] = useState('')
  const [dismissed, setDismissed] = useState<Set<string>>(new Set())
  const stop = useRef<(() => void) | null>(null)
  useEffect(() => () => stop.current?.(), [])
  const lang = ctx.lang
  const [hearing, setHearing] = useState('')
  const said = useRef(0)
  // Each line shows at once as "checking…" and fills in when its check returns (10-25).
  const say = (line: string) => {
    const id = `l${++said.current}`
    dispatch({ type: 'said_local', id, line })
    send({ type: 'said', text: line, id })
  }
  const toggle = async () => {
    if (stop.current) {
      stop.current()
      stop.current = null
      return
    }
    setStatus('listening')
    stop.current = await startListening(ctx.hello, lang, line => { setHeard(line); setHearing(''); say(line) }, setStatus, setHearing)
  }
  const flags = state.factFlags.filter(f => !dismissed.has(`${f.subject}|${f.metric}|${f.claimed}|${f.quote}`))
  return (
    <section className="cd-factcheck" data-testid="fact-check" dir={lang === 'ar' ? 'rtl' : 'ltr'}>
      <div className="fc-head">
        <h2 className="cd-block-title">{dt(lang, 'factCheck')}</h2>
        <button className={`cd-used${status === 'listening' ? ' on' : ''}`} onClick={() => void toggle()} data-testid="listen"
          aria-pressed={status === 'listening'}>
          {status === 'listening' ? `■ ${dt(lang, 'stopListening')}` : `● ${dt(lang, 'listen')}`}
        </button>
        <span className="fc-status">
          {status === 'listening' ? dt(lang, 'listening') : status === 'mic_error' ? dt(lang, 'micError')
            : status === 'unavailable' || state.factStatus === 'unavailable' ? dt(lang, 'speechUnavailable') : ''}
        </span>
        <form className="cd-ask fc-form" onSubmit={e => { e.preventDefault(); if (text.trim()) { say(text.trim()); setText('') } }}>
          <input data-testid="say-input" value={text} onChange={e => setText(e.target.value)} maxLength={500}
            placeholder={dt(lang, 'sayPlaceholder')} aria-label={dt(lang, 'sayPlaceholder')} />
          <button type="submit" disabled={!text.trim()}>{dt(lang, 'check')}</button>
        </form>
      </div>
      {hearing && <p className="fc-heard fc-live" data-testid="hearing"><span>{dt(lang, 'hearing')}:</span> <i dir="auto">{hearing}</i></p>}
      {!hearing && heard && <p className="fc-heard"><span>{dt(lang, 'heard')}:</span> <i dir="auto">{heard}</i></p>}
      {state.factLog.length > 0 && (
        <ul className="fc-log" data-testid="fact-log">
          {state.factLog.slice(0, 3).map(l => (
            <li key={l.id} data-status={l.status}>
              <span className="fc-line" dir="auto">“{l.line}”</span>
              {l.status === 'checking' && <span className="fc-state">{dt(lang, 'checking')}</span>}
              {l.status === 'done' && !l.results.length && <span className="fc-state">{dt(lang, 'noStatToCheck')}</span>}
              {(l.status === 'error' || l.status === 'unavailable') && <span className="fc-state">{dt(lang, 'couldNotCheck')}</span>}
              {l.results.map((r, i) => (
                <span key={i} className={`fc-result ${r.verdict}`} data-testid={`fact-${r.verdict}`}>
                  {r.verdict === 'correct' ? '✓' : '⚑'} {ctx.num(r.text[lang] ?? r.text.en)}
                </span>
              ))}
            </li>
          ))}
        </ul>
      )}
      {flags.slice(0, 3).map(f => {
        const key = `${f.subject}|${f.metric}|${f.claimed}|${f.quote}`
        return (
          <div key={key} className="fc-flag" data-testid="fact-flag" role="status">
            <div><b>⚑ {ctx.num(f.text[lang] ?? f.text.en)}</b>
              <button className="cd-link" onClick={() => setDismissed(d => new Set(d).add(key))} aria-label={dt(lang, 'dismiss')}>×</button></div>
            <small dir="auto">{dt(lang, 'youSaid')}: “{f.quote}”</small>
            <small className="fc-evidence" dir="ltr"><code>{f.evidence}</code></small>
          </div>
        )
      })}
      <p className="fc-note">
        <span className="cd-count" data-testid="fact-count">
          {ctx.num(dt(lang, 'checkedCount').replace('{n}', String(state.factChecked)))} · {ctx.num(dt(lang, 'flaggedCount').replace('{n}', String(state.factFlags.length)))}
        </span>{' '}
        <span title={dt(lang, 'factNote')}>{dt(lang, 'factHint')} {dt(lang, 'factNote')}</span>
      </p>
    </section>
  )
}

/** GP-1..GP-5: the Producer's cue, pinned above the talking points. */
function OnAirCard({ state, ctx, toggle }: { state: State; ctx: Ctx; toggle: (ref: string) => void }) {
  const cue = state.cue
  const speed = ctx.hello.speed ?? 1
  const [last, setLast] = useState<LastOnAir | null>(null)
  const [, setTick] = useState(0)
  useEffect(() => {
    if (cue?.state === 'on_air') {
      setLast({ ref: cue.ref, until: Date.now() + onAirMs(cue.window_s, speed), break_kind: cue.break_kind, window_s: cue.window_s })
    }
  }, [cue?.id]) // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {  // re-render when the on-air display time runs out
    if (!last || last.until === Infinity) return
    const timer = window.setTimeout(() => setTick(n => n + 1), Math.max(0, last.until - Date.now()) + 50)
    return () => window.clearTimeout(timer)
  }, [last])
  const lang = ctx.lang
  if (!cue) {
    return <section className="cd-onair-card none" data-testid="cue-card" data-state="none"><p className="empty">{dt(lang, 'noCue')}</p></section>
  }
  const shown = shownState(cue, last, Date.now())
  const text = cueText(cue, state, lang)
  const team = cue.team_id ? (cue.team_id === ctx.hello.home.id ? ctx.hello.home : ctx.hello.away) : null
  const note = state.cueNote?.ref === cue.ref ? state.cueNote.text : null
  const cueOverlay = cue.kind === 'moment' ? state.feed.find(x => x.moment_id === cue.ref) : undefined
  const cueIncident = cue.kind === 'sub' ? state.incidents.find(i => i.id === cue.ref) : undefined
  const focused = (cueOverlay && involves(cueOverlay, ctx.focus)) || (cueIncident && incidentInvolves(cueIncident, ctx.focus))
  const word = (key: string, fallback: string) => (dt(lang, key as DeskKey) as string | undefined) ?? fallback
  return (
    <section className={`cd-onair-card ${shown.state}${focused ? ' focus' : ''}`} data-testid="cue-card" data-state={shown.state} data-ref={cue.ref}
      dir={lang === 'ar' ? 'rtl' : 'ltr'} aria-live="polite">
      <div className="oa-status">
        {shown.state === 'on_air'
          ? <><i className="oa-dot" aria-hidden /><b>{dt(lang, 'onAir')}</b>
              {shown.break_kind && <> · {word(`br_${shown.break_kind}`, shown.break_kind)}</>}
              {shown.window_s ? <> · <span className="oa-window">{ctx.num(dt(lang, 'aboutSeconds').replace('{n}', String(shown.window_s)))}</span></> : null}</>
          : <><b>{dt(lang, 'upNext')}</b> · {dt(lang, 'openPlay')}</>}
        <span className="oa-min">{ctx.num(cue.minute)}'</span>
        {team && <span className="cd-teamtag"><Bar color={ctx.colors[team.id]} />{team.short_name}</span>}
      </div>
      <h3>{ctx.num(text?.headline ?? (KIND_LABELS[lang][cue.label] ?? cue.label))}</h3>
      {text?.body && <p>{ctx.num(text.body)}</p>}
      {cue.storyline && (
        <p className="oa-story" data-testid="cue-storyline"><b>{dt(lang, 'storylineLabel')}:</b>{' '}
          {state.storylines.find(s => s.text.en === cue.storyline)?.text[lang] ?? cue.storyline}</p>
      )}
      {note && <p className="oa-note" data-testid="cue-note"><span className="ai-tag">AI</span> <b>{dt(lang, 'producerNote')}:</b> {ctx.num(note)}</p>}
      <footer>
        <span className="oa-source" data-testid="cue-source">{word(`src_${cue.source}`, cue.source)} → {dt(lang, 'src_producer')}</span>
        {cue.reasons.map(r => <span key={r} className="oa-reason">{word(`r_${r}`, r)}</span>)}
        <button className="cd-used" data-testid="cue-used" onClick={() => toggle(cue.ref)} aria-label={dt(lang, 'markUsed')}>
          <span aria-hidden>✓</span> {dt(lang, 'markUsed')}
        </button>
      </footer>
    </section>
  )
}

function PatternAlert({ a, ctx }: { a: PatternNote & { minute: string }; ctx: Ctx }) {
  const team = ctx.hello[a.team_id === ctx.hello.home.id ? 'home' : 'away']
  return (
    <article className="cd-point cd-pattern-alert" data-testid="pattern-alert" dir={ctx.lang === 'ar' ? 'rtl' : 'ltr'}>
      <header>
        <span className="cd-min">{ctx.num(a.minute)}'</span>
        <span className="cd-kind cd-pattern-tag">{dt(ctx.lang, 'newPattern')}</span>
        <span className="cd-teamtag"><Bar color={ctx.colors[team.id]} />{team.short_name}</span>
        {a.source === 'ai' && <span className="ai-tag">AI</span>}
      </header>
      <h3>{ctx.num(a.text)}</h3>
    </article>
  )
}

// ---------- patterns (PA-5) ----------

function PatternsTab({ state, ctx }: { state: State; ctx: Ctx }) {
  const notes = state.patterns?.notes ?? []
  const [picked, setPicked] = useState<string | null>(null)
  const current = notes.find(n => n.pattern_id === picked) ?? notes[0]
  if (!notes.length) return <p className="empty">{dt(ctx.lang, 'noPatterns')}</p>
  const side = (id: string) => (id === ctx.hello.home.id ? 'home' : 'away') as 'home' | 'away'
  return (
    <div className="cd-patterns">
      {current && state.shape && (
        <figure className="cd-pattern-figure">
          <PatternPitch note={current} shape={state.shape[side(current.team_id)]} color={ctx.colors[current.team_id]} lang={ctx.lang} />
          <figcaption>{dt(ctx.lang, 'patternHint')}</figcaption>
        </figure>
      )}
      {(['home', 'away'] as const).map(s => {
        const club = ctx.hello[s]
        const mine = notes.filter(n => n.team_id === club.id)
        return (
          <section key={s} className="cd-pattern-team">
            <h4><Bar color={ctx.colors[club.id]} />{club.short_name}</h4>
            {!mine.length && <p className="cd-note">–</p>}
            {mine.map(n => (
              <button key={n.pattern_id} className={`cd-pattern-note${current?.pattern_id === n.pattern_id ? ' on' : ''}`}
                data-testid="pattern-note" data-kind={n.kind} data-scope={n.scope === 'season' ? 'season' : 'match'}
                aria-pressed={current?.pattern_id === n.pattern_id} onClick={() => setPicked(n.pattern_id)}>
                <span className={`cd-pattern-scope ${n.scope === 'season' ? 'season' : 'today'}`}>
                  {n.scope === 'season' ? dt(ctx.lang, 'knownFor') : dt(ctx.lang, 'today')}
                </span>
                <span dir="auto">{ctx.num(n.text)}</span>
                {n.source === 'ai' && <span className="ai-tag">AI</span>}
              </button>
            ))}
          </section>
        )
      })}
      <p className="cd-note">{dt(ctx.lang, 'patternMethod')}</p>
    </div>
  )
}

// ---------- stats (CD-11, CD-13) ----------

const STAT_ROWS: [DeskKey, (s: TeamStats | NonNullable<TeamStats['last10']>) => number, 'int' | 'xg' | 'pct'][] = [
  ['stat_goals', s => s.goals, 'int'],
  ['stat_xg', s => s.xg, 'xg'],
  ['stat_shots', s => s.shots, 'int'],
  ['stat_on_target', s => s.shots_on_target, 'int'],
  ['stat_big_chances', s => s.big_chances, 'int'],
  ['stat_possession', s => s.possession_pct, 'pct'],
  ['stat_passes', s => s.passes, 'int'],
  ['stat_pass_accuracy', s => 100 * s.pass_accuracy, 'pct'],
  ['stat_final_third', s => s.final_third_passes, 'int'],
  ['stat_tackles_won', s => s.tackles_won, 'int'],
  ['stat_interceptions', s => s.interceptions, 'int'],
  ['stat_fouls', s => s.fouls, 'int'],
  ['stat_yellow', s => s.yellow_cards, 'int'],
  ['stat_red', s => s.red_cards, 'int'],
  ['stat_corners', s => s.corners ?? 0, 'int'],
]

const EXPLAINED: Partial<Record<DeskKey, string>> = {
  stat_xg: 'xg', stat_big_chances: 'big_chances', stat_pass_accuracy: 'pass_accuracy', stat_final_third: 'final_third',
}

function StatsTab({ state, ctx }: { state: State; ctx: Ctx }) {
  const [open, setOpen] = useState<string | null>(null)
  const [period, setPeriod] = useState<Period>('match')
  if (!state.stats) return <p className="empty">{t(ctx.lang, 'waiting')}</p>
  const explainers = ctx.hello.explainers ?? {}
  const shown = period === 'second_half' && !state.stats.home.second_half ? 'match' : period
  const home = forPeriod(state.stats.home, shown)
  const away = forPeriod(state.stats.away, shown)
  const periodLabel = shown === 'match' ? dt(ctx.lang, 'match') : dt(ctx.lang, shown === 'first_half' ? 'period1' : 'period2')
  const fmt = (v: number, kind: 'int' | 'xg' | 'pct') => ctx.num(kind === 'xg' ? v.toFixed(2) : kind === 'pct' ? `${Math.round(v)}%` : String(v))
  const performers: [PerformerMetric, DeskKey][] = [['xg', 'leadersXg'], ['passes_completed', 'leadersPasses'], ['defensive', 'leadersDefence']]
  const teamOf = (pid: string) => [...ctx.hello.home.lineup, ...ctx.hello.home.bench].some(p => p.id === pid) ? ctx.hello.home.id : ctx.hello.away.id
  return (
    <div data-testid="desk-stats" data-period={shown}>
      <HalfSwitch period={shown} setPeriod={setPeriod} state={state} className="cd-half-switch"
        labels={[dt(ctx.lang, 'match'), dt(ctx.lang, 'period1'), dt(ctx.lang, 'period2')]} />
      <table className="cd-stats" dir="ltr">
        <thead>
          <tr><th colSpan={2} className="h"><Bar color={ctx.colors[ctx.hello.home.id]} />{ctx.hello.home.short_name}</th><th />
            <th colSpan={2} className="a">{ctx.hello.away.short_name}<Bar color={ctx.colors[ctx.hello.away.id]} /></th></tr>
          <tr className="sub"><th>{periodLabel}</th><th>{dt(ctx.lang, 'last10')}</th><th />
            <th>{dt(ctx.lang, 'last10')}</th><th>{periodLabel}</th></tr>
        </thead>
        <tbody>
          {STAT_ROWS.map(([k, get, kind]) => {
            const [h, a] = [get(home), get(away)]
            const ex = EXPLAINED[k] ? explainers[EXPLAINED[k]!] : undefined
            return [
              <tr key={k}>
                <td className={h > a ? 'lead' : ''}>{fmt(h, kind)}</td>
                <td className="w">{home.last10 ? fmt(get(home.last10), kind) : '–'}</td>
                <th scope="row" dir={ctx.lang === 'ar' ? 'rtl' : 'ltr'}>
                  {ex ? <button className="cd-explain" aria-expanded={open === k} title={dt(ctx.lang, 'explain')}
                    onClick={() => setOpen(open === k ? null : k)}>{dt(ctx.lang, k)} <span aria-hidden>ⓘ</span></button> : dt(ctx.lang, k)}
                </th>
                <td className="w">{away.last10 ? fmt(get(away.last10), kind) : '–'}</td>
                <td className={a > h ? 'lead' : ''}>{fmt(a, kind)}</td>
              </tr>,
              ex && open === k && (
                <tr key={`${k}-x`} className="cd-explainer-row">
                  <td colSpan={5} data-testid="explainer" dir={ctx.lang === 'ar' ? 'rtl' : 'ltr'}>
                    <b>{ex.topic}</b> {ex.text} <Sources sources={ex.sources} />
                  </td>
                </tr>
              ),
            ]
          })}
        </tbody>
      </table>
      <p className="cd-note">{dt(ctx.lang, 'notInFeed')}</p>
      <h3 className="cd-sub">{dt(ctx.lang, 'topPerformers')}</h3>
      <div className="cd-leaders">
        {performers.map(([metric, label]) => (
          <div key={metric}>
            <h4>{dt(ctx.lang, label)}</h4>
            <ol>
              {topPerformers(state.players, metric).map(p => (
                <li key={p.player_id}><Bar color={ctx.colors[teamOf(p.player_id)]} />
                  <span dir="auto">{ctx.names[p.player_id] ?? p.player_id}</span>
                  <b>{ctx.num(metric === 'xg' ? p.value.toFixed(2) : p.value)}</b></li>
              ))}
            </ol>
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------- timeline (CD-8) ----------

function incidentText(i: Incident, ctx: Ctx): string {
  const n = (id?: string | null) => (id ? ctx.names[id] ?? id : '')
  switch (i.kind) {
    case 'goal': return `${n(i.player_id)}${i.set_piece ? ` (${dt(ctx.lang, i.set_piece === 'penalty' ? 'sp_penalty' : 'sp_corner')})` : ''}${i.assist_id ? ` (${dt(ctx.lang, 'assistBy')} ${n(i.assist_id)})` : ''} · ${ctx.num(`${i.score_home}–${i.score_away}`)}`
    case 'penalty': return n(i.player_id)
    case 'sub': return `▲ ${n(i.player_in_id)}  ▼ ${n(i.player_out_id)}`
    case 'big_chance': return `${n(i.player_id)}${i.set_piece === 'penalty' ? ` (${dt(ctx.lang, 'sp_penalty')})` : ''} · xG ${ctx.num((i.xg ?? 0).toFixed(2))}`
    case 'woodwork': return `${n(i.player_id)} · xG ${ctx.num((i.xg ?? 0).toFixed(2))}`
    case 'yellow':
    case 'second_yellow':
    case 'red': {
      const why = cardReasonText(i.card_reason, i.fouled_player_id ? n(i.fouled_player_id) : null, ctx.lang)
      return why ? `${n(i.player_id)} · ${why}` : n(i.player_id)
    }
    default: return n(i.player_id)
  }
}

function TimelineTab({ state, ctx, onOpenSub }: { state: State; ctx: Ctx; onOpenSub: (incidentId: string) => void }) {
  const items = timeline(state.incidents)
  if (!items.length) return <p className="empty">{dt(ctx.lang, 'noIncidents')}</p>
  return (
    <ol className="cd-timeline">
      {items.map(i => {
        const team = i.team_id === ctx.hello.home.id ? ctx.hello.home : ctx.hello.away
        return (
          <li key={i.id} data-testid="timeline-item" data-kind={i.kind} className={`k-${i.kind}${incidentInvolves(i, ctx.focus) ? ' focus' : ''}`}
            data-focus={incidentInvolves(i, ctx.focus) ? 'true' : undefined}>
            <span className="tl-minute">{ctx.num(i.minute)}'</span>
            <span className="tl-icon">
              {i.kind === 'yellow' ? <Card kind="yellow" /> : i.kind === 'red' || i.kind === 'second_yellow' ? <Card kind="red" />
                : i.kind === 'goal' ? '●' : i.kind === 'sub' ? '⇅' : i.kind === 'penalty' ? '◉' : '○'}
            </span>
            <span className="tl-body">
              <b>{dt(ctx.lang, `inc_${i.kind}` as DeskKey)}</b> <span className="tl-team"><Bar color={ctx.colors[team.id]} />{team.short_name}</span>
              <span className="tl-text">{incidentText(i, ctx)}</span>
            </span>
            {i.kind === 'sub' && i.card && (
              <button className="cd-link tl-open" data-testid="open-sub-card" onClick={() => onOpenSub(i.id)}
                title={dt(ctx.lang, 'sub_reopen')} aria-label={dt(ctx.lang, 'sub_reopen')}>⇅</button>
            )}
          </li>
        )
      })}
    </ol>
  )
}

// ---------- substitution card (SB-1..SB-3) ----------

function SubChange({ c, ctx }: { c: SubCard; ctx: Ctx }) {
  const team = c.team_id === ctx.hello.home.id ? ctx.hello.home : ctx.hello.away
  const l = c.off.line
  const acc = l.passes ? Math.round(100 * l.passes_completed / l.passes) : 0
  const rows: [DeskKey, string][] = [
    ['passes', `${ctx.num(l.passes_completed)}/${ctx.num(l.passes)} (${ctx.num(acc)}%)`],
    ['shots', ctx.num(l.shots)], ['xg', ctx.num(l.xg.toFixed(2))], ['goals', ctx.num(l.goals)], ['assists', ctx.num(l.assists)],
    ['leadersDefence', ctx.num(l.tackles_won + l.interceptions)], ['fouls', ctx.num(l.fouls)],
  ]
  const season = (s: { goals: number; assists: number } | null) => s && (
    <p className="sc-season"><b>{dt(ctx.lang, 'sub_season')}</b> {ctx.num(s.goals)} {dt(ctx.lang, 'goals').toLowerCase()} · {ctx.num(s.assists)} {dt(ctx.lang, 'assists').toLowerCase()}</p>
  )
  const person = (p: { player_id: string; number: number; position: string }) => (
    <p className="sc-name"><span className="sc-num">{ctx.num(p.number)}</span> {ctx.names[p.player_id] ?? p.player_id} <small>{p.position}</small></p>
  )
  return (
    <section className="sc-change-block" data-testid="sub-change" data-change={c.change}>
      <div className="sc-meta">
        <span><Bar color={ctx.colors[team.id]} />{team.short_name} · {ctx.num(c.minute)}'</span>
        <span className={`sc-tag ${c.change}`} data-testid="sub-change-type">{dt(ctx.lang, `change_${c.change}` as DeskKey)}</span>
      </div>
      <div className="sc-cols">
        <div className="sc-off">
          <h4>▼ {dt(ctx.lang, 'sub_going_off')}</h4>
          {person(c.off)}
          <p className="sc-mins">{ctx.num(c.off.minutes)} {dt(ctx.lang, 'sub_minutes')}
            {c.off.booked && <span className="sc-booked" data-testid="sub-booked"><Card kind="yellow" /> {dt(ctx.lang, 'sub_booked')}</span>}
          </p>
          <dl>{rows.map(([k, v]) => <div key={k}><dt>{dt(ctx.lang, k)}</dt><dd>{v}</dd></div>)}</dl>
          {season(c.off.season)}
        </div>
        <div className="sc-on">
          <h4>▲ {dt(ctx.lang, 'sub_coming_on')}</h4>
          {person(c.on)}
          {season(c.on.season)}
        </div>
      </div>
      <p className="sc-foot">
        {dt(ctx.lang, 'sub_score')} <b dir="ltr">{ctx.num(`${c.score_home}–${c.score_away}`)}</b> · {dt(ctx.lang, 'sub_used')} <b dir="ltr">{ctx.num(c.subs_used)}/{ctx.num(c.subs_allowed)}</b>
      </p>
    </section>
  )
}

function SubCardPanel({ group, ctx, onClose }: { group: Incident[]; ctx: Ctx; onClose: () => void }) {
  return (
    <aside className="cd-subcard" data-testid="sub-card" aria-label={dt(ctx.lang, 'sub_title')} dir={ctx.lang === 'ar' ? 'rtl' : 'ltr'}>
      <header>
        <span>⇅ {dt(ctx.lang, 'sub_title')}</span>
        <button data-testid="sub-card-close" onClick={onClose} aria-label={dt(ctx.lang, 'sub_close')} title={dt(ctx.lang, 'sub_close')}>×</button>
      </header>
      {group.map(i => i.card && <SubChange key={i.id} c={i.card} ctx={ctx} />)}
    </aside>
  )
}

// ---------- prep and storylines (PS-1..PS-3) ----------

function styleLine(s: BriefSide['styles'][number], lang: Language): string {
  const pct = String(Math.round(100 * s.share))
  const lg = s.league === null ? '' : String(Math.round(100 * s.league))
  const side = s.value === 'left' || s.value === 'right' ? dt(lang, `side_${s.value}` as DeskKey) : s.value
  const key = `st_${s.kind}` as DeskKey
  return (dt(lang, key) ?? s.kind).replace('{side}', side).replace('{pct}', pct).replace('{lg}', lg)
}

function PrepTab({ state, ctx, send }: { state: State; ctx: Ctx; send: (msg: object) => void }) {
  const [text, setText] = useState('')
  const brief = state.brief
  const season = ctx.hello.season
  const lang = ctx.lang
  const active = state.storylines
  const full = active.length >= 4
  return (
    <div className="cd-prep" data-testid="prep">
      <div className="cd-prep-head">
        <h3 className="cd-sub">{dt(lang, 'briefTitle')}</h3>
        <span className="no-print">
          {state.status === 'waiting' && (
            <button className="cd-used" data-testid="kick-off" onClick={() => void startMatch(ctx.hello.match_id)}>{dt(lang, 'kickOff')}</button>
          )}{' '}
          <button className="cd-link" onClick={() => window.print()}>{dt(lang, 'print')}</button>
        </span>
      </div>
      {!brief ? <p className="empty">{t(lang, 'waiting')}</p> : (
        <>
          <div className="cd-season-cards">
            {(['home', 'away'] as const).map(side => {
              const c = ctx.hello[side]
              const s = season?.[side]
              return (
                <div key={side} className="cd-season-card" data-testid={`brief-${side}`}>
                  <h4><Bar color={ctx.colors[c.id]} />{c.short_name}
                    {s && <span className="cd-brief-pos"> · {ctx.num(s.position)} · {ctx.num(s.points)} {dt(lang, 'pts')}</span>}</h4>
                  {s && <div className="cd-form" dir="ltr">{s.form.map((r, i) => <span key={i} className={`f-${r}`}>{r}</span>)}</div>}
                  <h5>{dt(lang, 'playersToWatch')}</h5>
                  <ul className="cd-watch">
                    {brief[side].players_to_watch.map(w => (
                      <li key={w.why}><b>{ctx.names[w.player_id] ?? w.player_id}</b> <span>{ctx.num(dt(lang, `w_${w.why}` as DeskKey).replace('{n}', String(w.value)))}</span></li>
                    ))}
                  </ul>
                  {brief[side].styles.length > 0 && <>
                    <h5>{dt(lang, 'knownFor')}</h5>
                    <ul className="cd-watch">{brief[side].styles.map(st => <li key={st.kind}>{ctx.num(styleLine(st, lang))}</li>)}</ul>
                  </>}
                </div>
              )
            })}
          </div>
          {brief.meetings.length > 0 && <>
            <h5 className="cd-sub">{dt(lang, 'meetingsTitle')}</h5>
            <ul className="cd-watch" dir="ltr">
              {brief.meetings.map(m => (
                <li key={m.matchday}>{dt(lang, 'matchday')} {ctx.num(m.matchday)}: {ctx.names[m.home]} <b>{ctx.num(`${m.home_goals}-${m.away_goals}`)}</b> {ctx.names[m.away]}</li>
              ))}
            </ul>
          </>}
        </>
      )}

      <h3 className="cd-sub">{dt(lang, 'storylinesTitle')} <span className="cd-count">{ctx.num(active.length)}/{ctx.num(4)}</span></h3>
      {state.storylineError && <p className="cd-note cd-error" data-testid="storyline-error">{state.storylineError}</p>}
      {!active.length && <p className="cd-note">{dt(lang, 'noStorylines')}</p>}
      {active.map(s => (
        <article key={s.id} className="cd-story" data-testid="storyline">
          <header>
            <h4 dir="auto">{s.text[lang] ?? s.text.en}</h4>
            <button className="cd-link no-print" onClick={() => send({ type: 'storyline_remove', id: s.id })}
              aria-label={dt(lang, 'removeStoryline')} title={dt(lang, 'removeStoryline')}>×</button>
          </header>
          {!s.updates.length ? <p className="cd-note">{dt(lang, 'noUpdates')}</p> : (
            <ol className="cd-story-updates">
              {[...s.updates].reverse().map((u, i) => (
                <li key={`${u.ref}-${i}`} data-testid="storyline-update">
                  <span className="cd-min">{ctx.num(u.minute)}'</span> <span dir="auto">{ctx.num(u.text[lang] ?? u.text.en)}</span>
                  {u.source === 'ai' && lang === 'en' && <span className="ai-tag">AI</span>}
                </li>
              ))}
            </ol>
          )}
        </article>
      ))}
      <form className="cd-ask no-print" onSubmit={e => { e.preventDefault(); if (text.trim() && !full) { send({ type: 'storyline_add', text: text.trim() }); setText('') } }}>
        <input data-testid="storyline-input" value={text} onChange={e => setText(e.target.value)} maxLength={120}
          placeholder={dt(lang, 'customStoryline')} aria-label={dt(lang, 'customStoryline')} disabled={full} />
        <button type="submit" disabled={full || !text.trim()}>{dt(lang, 'addStoryline')}</button>
      </form>
      {brief && brief.suggestions.length > 0 && <>
        <h5 className="cd-sub">{dt(lang, 'suggestedStorylines')}</h5>
        <ul className="cd-suggestions no-print">
          {brief.suggestions.map(sg => {
            const added = active.some(s => s.seed_id === sg.seed_id)
            return (
              <li key={sg.seed_id} data-testid="storyline-suggestion">
                <span dir="auto">{ctx.num(sg.text[lang] ?? sg.text.en)}</span>
                {sg.source === 'ai' && lang === 'en' && <span className="ai-tag">AI</span>}
                <button className="cd-used" disabled={added || full} onClick={() => send({ type: 'storyline_add', suggestion_id: sg.seed_id })}>
                  {added ? '✓' : `+ ${dt(lang, 'addStoryline')}`}
                </button>
              </li>
            )
          })}
        </ul>
      </>}
    </div>
  )
}

// ---------- season (CD-14) ----------

function SeasonTab({ ctx }: { ctx: Ctx }) {
  const season = ctx.hello.season
  if (!season) return <p className="empty">{t(ctx.lang, 'waiting')}</p>
  const club = (id: string) => (id === ctx.hello.home.id ? ctx.hello.home : id === ctx.hello.away.id ? ctx.hello.away : null)
  return (
    <div className="cd-season">
      <p className="cd-note">{dt(ctx.lang, 'seasonNote')} · {ctx.num(season.matches)} {dt(ctx.lang, 'matches')}</p>
      <div className="cd-season-cards">
        {(['home', 'away'] as const).map(side => {
          const c = ctx.hello[side]
          const s = season[side]
          return (
            <div key={side} className="cd-season-card" data-testid={`season-${side}`}>
              <h4><Bar color={ctx.colors[c.id]} />{c.short_name}</h4>
              <dl>
                <div><dt>{dt(ctx.lang, 'pos')}</dt><dd>{ctx.num(s.position)}</dd></div>
                <div><dt>{dt(ctx.lang, 'pts')}</dt><dd>{ctx.num(s.points)}</dd></div>
                <div><dt>{dt(ctx.lang, 'record')}</dt><dd dir="ltr">{ctx.num(`${s.won}-${s.drawn}-${s.lost}`)}</dd></div>
                <div><dt>{dt(ctx.lang, 'goalsForAgainst')}</dt><dd dir="ltr">{ctx.num(`${s.goals_for}-${s.goals_against}`)}</dd></div>
              </dl>
              <div className="cd-form" aria-label={dt(ctx.lang, 'form')} dir="ltr">
                {s.form.map((r, i) => <span key={i} className={`f-${r}`}>{r}</span>)}
              </div>
              <h5>{dt(ctx.lang, 'topScorers')}</h5>
              <ol>{s.top_scorers.map(p => <li key={p.player_id}>{ctx.names[p.player_id] ?? p.player_id} <b>{ctx.num(p.goals)}</b></li>)}</ol>
            </div>
          )
        })}
      </div>
      <h3 className="cd-sub">{dt(ctx.lang, 'table')}</h3>
      <table className="cd-table">
        <thead><tr><th>{dt(ctx.lang, 'pos')}</th><th /><th>{dt(ctx.lang, 'played')}</th><th>{dt(ctx.lang, 'gd')}</th><th>{dt(ctx.lang, 'pts')}</th></tr></thead>
        <tbody>
          {season.table.map(r => {
            const c = club(r.club_id)
            return (
              <tr key={r.club_id} className={c ? 'here' : ''}>
                <td>{ctx.num(r.position)}</td>
                <td>{c && <Bar color={ctx.colors[c.id]} />}{r.short_name}</td>
                <td>{ctx.num(r.played)}</td>
                <td dir="ltr">{ctx.num(r.goal_difference > 0 ? `+${r.goal_difference}` : r.goal_difference)}</td>
                <td><b>{ctx.num(r.points)}</b></td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ---------- research (CX-3, CX-8) ----------

interface Asked { question: string; result: AskResult | null }

/** AM-1..AM-3: an answer from this match's data, with the tool calls behind it. */
function MatchAnswer({ r, ctx }: { r: AskResult; ctx: Ctx }) {
  const [open, setOpen] = useState(r.status === 'facts_only')
  const evidence = r.evidence ?? []
  return (
    <div className="cd-match-answer" data-testid="match-answer" data-status={r.status}>
      {r.status === 'ok' && <p dir="auto">{ctx.num(r.text)}</p>}
      {r.status === 'not_in_data' && <p dir="auto">{ctx.num(r.text || dt(ctx.lang, 'ask_not_in_data'))}</p>}
      {r.status === 'facts_only' && <p className="cd-note">{dt(ctx.lang, 'ask_facts_only')}</p>}
      {!['ok', 'not_in_data', 'facts_only'].includes(r.status) && <p className="cd-note">{dt(ctx.lang, `ask_${r.status}` as DeskKey)}</p>}
      {evidence.length > 0 && (
        <>
          <button className="cd-link" onClick={() => setOpen(v => !v)} aria-expanded={open} data-testid="how-i-know">{dt(ctx.lang, 'howIKnow')}</button>
          {open && <ul className="cd-evidence" dir="ltr">{evidence.map((e, i) => <li key={i}><code>{e.summary}</code></li>)}</ul>}
        </>
      )}
      {(r.status === 'ok' || r.status === 'facts_only') && r.as_of && (
        <p className="cd-note">{dt(ctx.lang, 'fromMatch').replace('{m}', `${ctx.num(r.as_of)}'`)}</p>
      )}
    </div>
  )
}

function ResearchTab({ state, ctx, asked, onAsk }: { state: State; ctx: Ctx; asked: Asked[]; onAsk: (q: string) => void }) {
  const [q, setQ] = useState('')
  const remaining = [...asked].reverse().find(a => a.result && a.result.source !== 'match')?.result?.remaining
  const pending = asked.some(a => !a.result)
  const cards = state.contexts.filter(c => c.language === ctx.lang)
  const explainers = Object.values(ctx.hello.explainers ?? {})
  return (
    <div className="cd-research">
      <form className="cd-ask" onSubmit={e => { e.preventDefault(); if (q.trim() && !pending) { onAsk(q.trim()); setQ('') } }}>
        <input data-testid="ask-input" value={q} onChange={e => setQ(e.target.value)} maxLength={300}
          placeholder={dt(ctx.lang, 'askPlaceholder')} aria-label={dt(ctx.lang, 'askPlaceholder')} />
        <button type="submit" disabled={pending || !q.trim()}>{dt(ctx.lang, 'ask')}</button>
      </form>
      {remaining !== undefined && <p className="cd-note" data-testid="ask-remaining">{ctx.num(remaining)} {dt(ctx.lang, 'searchesLeft')}</p>}
      {[...asked].reverse().map((a, i) => (
        <article key={asked.length - i} className="cd-answer" data-testid="ask-answer">
          <h4 dir="auto">{a.question}</h4>
          {!a.result ? <p className="cd-note">{dt(ctx.lang, 'asking')}</p>
            : a.result.source === 'match' ? <MatchAnswer r={a.result} ctx={ctx} />
            : a.result.status === 'ok' || a.result.status === 'cached' ? (
              <>
                <p dir="auto">{ctx.num(a.result.text)}</p>
                <Sources sources={a.result.sources} />
                <p className="cd-note">{dt(ctx.lang, 'fromWeb')}</p>
              </>
            ) : <p className="cd-note">{dt(ctx.lang, `ask_${a.result.status}` as DeskKey)}</p>}
        </article>
      ))}
      <h3 className="cd-sub">{dt(ctx.lang, 'contextCards')}</h3>
      {!cards.length && <p className="cd-note">{dt(ctx.lang, 'noContext')}</p>}
      {[...cards].reverse().map(c => (
        <div key={`${c.moment_id}-${c.entry_id}`} className="cd-research-card"><span className="cd-min">{ctx.num(c.minute)}'</span><ContextBlock c={c} lang={ctx.lang} /></div>
      ))}
      <h3 className="cd-sub">{dt(ctx.lang, 'explainers')}</h3>
      {explainers.map(x => (
        <div key={x.topic} className="cd-explainer"><b>{x.topic}</b> <span dir="auto">{x.text}</span> <Sources sources={x.sources} /></div>
      ))}
    </div>
  )
}

// ---------- production (CD-15, CD-16) ----------

function ProductionTab({ state, ctx }: { state: State; ctx: Ctx }) {
  return (
    <div className="cd-production">
      <a className="cd-overlay-link" href={`/overlay?match=${ctx.hello.match_id}&lang=${ctx.lang}`} target="_blank" rel="noopener">
        {dt(ctx.lang, 'openOverlay')} ↗
      </a>
      <div className="cd-onair" data-testid="on-air">
        <span className="cd-onair-tag">● {t(ctx.lang, 'onAir')}</span>
        {state.screen.map(o => (
          <div key={o.id} className={`cd-gfx ${o.slot}`} dir={o.direction} data-testid={`overlay-${o.slot}`}>
            <span className="k">{KIND_LABELS[ctx.lang][o.kind] ?? o.kind}</span>
            <strong>{ctx.num(o.headline)}</strong>
            <span className="b">{ctx.num(o.body)}</span>
          </div>
        ))}
      </div>
      <Agents state={state} lang={ctx.lang} />
    </div>
  )
}

// ---------- page ----------

export function Desk({ matchId, lang, setLang }: { matchId: string; lang: Language; setLang: (l: Language) => void }) {
  const profile: Profile = { mode: 'analyst', language: lang, club_id: null, player_id: null }
  const { state, send, dispatch } = useMatch(matchId, profile)
  const [chosenTab, setTab] = useState<Tab | null>(null)
  const [focus, setFocus] = useState<string | null>(null)  // DK-4
  const [asked, setAsked] = useState<Asked[]>([])
  const ask = (question: string) => {
    setAsked(prev => [...prev, { question, result: null }])
    askQuestion(matchId, question, lang).then(result =>
      setAsked(prev => prev.map(a => (a.question === question && !a.result ? { ...a, result } : a))))
  }
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

  // SB-3: a new substitution opens its card (replacing any other); changes made before joining don't pop up.
  const groups = useMemo(() => subGroups(state.incidents), [state.incidents])
  const [openSub, setOpenSub] = useState<string | null>(null)
  const lastSub = groups.at(-1)?.at(-1)?.id ?? null
  const seenSub = useRef<string | null | undefined>(undefined)
  useEffect(() => {
    if (!h) return
    if (seenSub.current !== undefined && lastSub !== seenSub.current && lastSub) setOpenSub(groupKey(groups, lastSub))
    seenSub.current = lastSub
  }, [h, lastSub, groups])
  const openGroup = groups.find(g => g[0].id === openSub) ?? null

  // GP-4: used is shared match state on the server; it echoes back to every desk.
  const toggleUsed = (ref: string) => send({ type: 'used', ref, used: !state.used.has(ref) })


  // CD-18: 1-6 switch panels, U marks the next talking point as used.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || (e.target as HTMLElement)?.closest('input, textarea, select')) return
      if (e.key === 'Escape') return setOpenSub(null)
      const n = Number(e.key)
      if (n >= 1 && n <= TABS.length) setTab(TABS[n - 1])
      else if (e.key.toLowerCase() === 'u') {
        if (state.cue) toggleUsed(state.cue.ref)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (!h) return <div className="cd" data-testid="desk"><p className="empty">{t(lang, 'kickOffSoon')}</p></div>
  const tab: Tab = chosenTab ?? (state.status === 'waiting' ? 'prep' : 'stats')  // PS-1: prep first until kick-off
  const ctx: Ctx = { lang, hello: h, colors, names, num: v => localDigits(v, lang), focus, setFocus }
  const tabLabel = (id: Tab) => ({
    prep: dt(lang, 'prep'), stats: t(lang, 'stats'), patterns: dt(lang, 'patterns'), timeline: dt(lang, 'timeline'),
    ask: dt(lang, 'askTab'), production: dt(lang, 'production'),
  })[id]

  return (
    <div className="cd" dir={lang === 'ar' ? 'rtl' : 'ltr'} data-testid="desk">
      <Header state={state} ctx={ctx} setLang={setLang} />
      <main className="cd-main">
        <Lineup club={h.home} side="home" state={state} ctx={ctx} season={h.season?.home} />
        <TalkingPoints state={state} ctx={ctx} toggle={toggleUsed} send={send} dispatch={dispatch} />
        <section className="cd-panel cd-tabs" dir={lang === 'ar' ? 'rtl' : 'ltr'}>
          <div className="cd-tablist" role="tablist">
            {TABS.map((id, i) => (
              <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)} title={`${i + 1}`}>{tabLabel(id)}</button>
            ))}
          </div>
          <div className="cd-scroll" role="tabpanel">
            {tab === 'prep' && <><PrepTab state={state} ctx={ctx} send={send} /><SeasonTab ctx={ctx} /></>}
            {tab === 'stats' && <>
              <StatsTab state={state} ctx={ctx} />
              <h3 className="cd-sub">{t(lang, 'momentumChart')}</h3>
              <div className="cd-momentum">
                <AttackMomentumChart state={state} colors={colors} names={names} lang={lang} topTeam={null} />
                <ZoneMap state={state} colors={colors} lang={lang} compact />
              </div>
            </>}
            {tab === 'timeline' && <TimelineTab state={state} ctx={ctx} onOpenSub={id => setOpenSub(groupKey(groups, id))} />}
            {tab === 'patterns' && <PatternsTab state={state} ctx={ctx} />}
            {tab === 'ask' && <ResearchTab state={state} ctx={ctx} asked={asked} onAsk={ask} />}
            {tab === 'production' && <>
              <h3 className="cd-sub">{dt(lang, 'recapsTitle')}</h3>
              <Recaps state={state} lang={lang} />
              <ProductionTab state={state} ctx={ctx} />
            </>}
          </div>
        </section>
        <Lineup club={h.away} side="away" state={state} ctx={ctx} season={h.season?.away} />
      </main>
      {openGroup && <SubCardPanel group={openGroup} ctx={ctx} onClose={() => setOpenSub(null)} />}
    </div>
  )
}
