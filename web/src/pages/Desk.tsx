// Commentator desk (CD-1..CD-18): a neutral broadcast console. Everything except talking points
// and recaps is built from match data, so it keeps working with the AI off or down.
import { useEffect, useMemo, useState } from 'react'
import { useMatch } from '../api'
import { teamColors } from '../colors'
import { AttackMomentumChart, Agents, Recaps } from '../components/Panels'
import { Evidence, KindIcon, ZoneMap } from '../components/Shared'
import {
  boardName, formation, formationLines, loadUsed, playerMarkers, saveUsed, scorers, subsUsed, timeline, topOpenPoint, topPerformers,
  type Markers, type PerformerMetric,
} from '../desk'
import { dt, type DeskKey } from '../deskText'
import { localDigits } from '../digits'
import { KIND_LABELS, LANGUAGE_NAMES, t } from '../i18n'
import type { State } from '../state'
import type { ClubInfo, ClubSeason, Hello, Incident, Language, Overlay, PlayerInfo, PlayerLine, Profile, TeamStats } from '../types'

const TABS = ['stats', 'timeline', 'momentum', 'season', 'production', 'recap'] as const
type Tab = typeof TABS[number]
type Side = 'home' | 'away'

interface Ctx {
  lang: Language
  hello: Hello
  colors: Record<string, string>
  names: Record<string, string>
  num: (v: string | number) => string
}

const Bar = ({ color }: { color: string }) => <i className="cd-bar" style={{ background: color }} aria-hidden />
const Card = ({ kind }: { kind: 'yellow' | 'red' }) => <i className={`cd-card ${kind}`} data-testid={`card-${kind}`} aria-hidden />

// ---------- header (CD-4) ----------

function TeamHead({ club, side, incidents, ctx }: { club: ClubInfo; side: Side; incidents: Incident[]; ctx: Ctx }) {
  const reds = incidents.filter(i => (i.kind === 'red' || i.kind === 'second_yellow') && i.team_id === club.id)
  return (
    <div className={`cd-team ${side}`}>
      <div className="cd-team-name"><Bar color={ctx.colors[club.id]} /><span>{club.name}</span></div>
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
  const clock = state.status === 'finished' ? t(lang, 'fullTime')
    : state.status === 'live' ? `${ctx.num(state.minute)}'` : t(lang, 'kickOffSoon')
  const period = state.status === 'live' ? dt(lang, state.period === 1 ? 'period1' : 'period2') : ''
  const wx = `w_${h.weather.condition}` as DeskKey
  return (
    <header className="cd-head">
      <div className="cd-top">
        <span className="cd-title">{t(lang, 'deskTitle')}</span>
        <div className="cd-scorebox" dir="ltr">
          <TeamHead club={h.home} side="home" incidents={state.incidents} ctx={ctx} />
          <div className="cd-scoreline">
            <span className="cd-score" data-testid="score">{ctx.num(state.score[0])} – {ctx.num(state.score[1])}</span>
            <span className="cd-clock-row">
              {state.status === 'live' && <span className="cd-live" aria-hidden />}
              <span className="cd-clock" data-testid="clock">{clock}</span>
              {period && <span className="cd-period">{period}</span>}
            </span>
          </div>
          <TeamHead club={h.away} side="away" incidents={state.incidents} ctx={ctx} />
        </div>
        <div className="cd-lang" role="group" aria-label={t(lang, 'language')}>
          {(['en', 'es', 'ar'] as const).map(l => (
            <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{LANGUAGE_NAMES[l]}</button>
          ))}
        </div>
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
        <button className={`cd-row${m?.booked ? ' booked' : ''}${m?.red ? ' sent-off' : ''}${m?.off ? ' subbed' : ''}`}
          data-testid={testid} data-booked={m?.booked ? 'true' : 'false'} aria-expanded={open}
          onClick={() => setSelected(open ? null : p.id)} title={m?.booked ? dt(ctx.lang, 'booked') : undefined}>
          <span className="no">{ctx.num(p.number)}</span>
          <span className="nm" title={p.name} dir="auto">{boardName(p.name)}</span>
          <span className="pos">{p.position}</span>
          <MarkerIcons m={m} ctx={ctx} />
        </button>
        {open && <PlayerLineView line={state.players[p.id]} season={season?.players[p.id]} ctx={ctx} />}
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

// ---------- talking points (CD-9, CD-10) ----------

function TalkingPoint({ o, used, next, toggle, ctx }: { o: Overlay; used: boolean; next: boolean; toggle: () => void; ctx: Ctx }) {
  const [open, setOpen] = useState(false)
  const team = o.team_id ? ctx.hello[o.team_id === ctx.hello.home.id ? 'home' : 'away'] : null
  return (
    <article className={`cd-point${used ? ' used' : ''}${next ? ' next' : ''}`} dir={o.direction}
      data-testid="feed-item" data-id={o.id} data-used={used ? 'true' : 'false'}>
      <header>
        <span className="cd-min">{ctx.num(o.minute)}'</span>
        <span className="cd-kind"><KindIcon kind={o.kind} size={13} /> {KIND_LABELS[ctx.lang][o.kind] ?? o.kind}</span>
        {team && <span className="cd-teamtag"><Bar color={ctx.colors[team.id]} />{team.short_name}</span>}
        {o.source === 'ai' ? <span className="ai-tag">AI</span> : <span className="instant-tag">{t(ctx.lang, 'instant')}</span>}
        {next && <span className="cd-next">{dt(ctx.lang, 'sayNext')}</span>}
      </header>
      <h3>{ctx.num(o.headline)}</h3>
      <p>{ctx.num(o.body)}</p>
      <footer>
        <button className="cd-link" onClick={() => setOpen(v => !v)} aria-expanded={open}>{t(ctx.lang, 'why')}</button>
        <button className="cd-used" onClick={toggle} aria-pressed={used} aria-label={dt(ctx.lang, 'markUsed')}>
          <span aria-hidden>{used ? '✓' : '○'}</span> {used ? dt(ctx.lang, 'used') : dt(ctx.lang, 'markUsed')}
        </button>
      </footer>
      {open && <Evidence overlay={o} names={ctx.names} lang={ctx.lang} />}
    </article>
  )
}

function TalkingPoints({ state, ctx, used, toggle }: { state: State; ctx: Ctx; used: Set<string>; toggle: (id: string) => void }) {
  const [team, setTeam] = useState<string | null>(null)
  const feed = team ? state.feed.filter(o => o.team_id === team) : state.feed
  const next = topOpenPoint(feed, used)
  const openCount = feed.filter(o => !used.has(o.id)).length
  const { home, away } = ctx.hello
  return (
    <section className="cd-panel cd-points" aria-labelledby="tp-title">
      <header className="cd-panel-head">
        <h2 id="tp-title">{t(ctx.lang, 'talkingPoints')}</h2>
        <span className="cd-count">{ctx.num(openCount)} {dt(ctx.lang, 'open')}</span>
        <div className="cd-chips" role="group">
          {[[null, dt(ctx.lang, 'bothTeams')], [home.id, home.short_name], [away.id, away.short_name]].map(([id, label]) => (
            <button key={id ?? 'all'} aria-pressed={team === id} onClick={() => setTeam(id)}>{label}</button>
          ))}
        </div>
      </header>
      <div className="cd-scroll">
        {!feed.length && <p className="empty">{t(ctx.lang, 'emptyFeed')}</p>}
        {feed.map(o => <TalkingPoint key={o.id} o={o} used={used.has(o.id)} next={o.id === next} toggle={() => toggle(o.id)} ctx={ctx} />)}
      </div>
    </section>
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
]

function StatsTab({ state, ctx }: { state: State; ctx: Ctx }) {
  if (!state.stats) return <p className="empty">{t(ctx.lang, 'waiting')}</p>
  const { home, away } = state.stats
  const fmt = (v: number, kind: 'int' | 'xg' | 'pct') => ctx.num(kind === 'xg' ? v.toFixed(2) : kind === 'pct' ? `${Math.round(v)}%` : String(v))
  const performers: [PerformerMetric, DeskKey][] = [['xg', 'leadersXg'], ['passes_completed', 'leadersPasses'], ['defensive', 'leadersDefence']]
  const teamOf = (pid: string) => [...ctx.hello.home.lineup, ...ctx.hello.home.bench].some(p => p.id === pid) ? ctx.hello.home.id : ctx.hello.away.id
  return (
    <div data-testid="desk-stats">
      <table className="cd-stats" dir="ltr">
        <thead>
          <tr><th colSpan={2} className="h"><Bar color={ctx.colors[ctx.hello.home.id]} />{ctx.hello.home.short_name}</th><th />
            <th colSpan={2} className="a">{ctx.hello.away.short_name}<Bar color={ctx.colors[ctx.hello.away.id]} /></th></tr>
          <tr className="sub"><th>{dt(ctx.lang, 'match')}</th><th>{dt(ctx.lang, 'last10')}</th><th />
            <th>{dt(ctx.lang, 'last10')}</th><th>{dt(ctx.lang, 'match')}</th></tr>
        </thead>
        <tbody>
          {STAT_ROWS.map(([k, get, kind]) => {
            const [h, a] = [get(home), get(away)]
            return (
              <tr key={k}>
                <td className={h > a ? 'lead' : ''}>{fmt(h, kind)}</td>
                <td className="w">{home.last10 ? fmt(get(home.last10), kind) : '–'}</td>
                <th scope="row" dir={ctx.lang === 'ar' ? 'rtl' : 'ltr'}>{dt(ctx.lang, k)}</th>
                <td className="w">{away.last10 ? fmt(get(away.last10), kind) : '–'}</td>
                <td className={a > h ? 'lead' : ''}>{fmt(a, kind)}</td>
              </tr>
            )
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
    case 'goal': return `${n(i.player_id)}${i.assist_id ? ` (${dt(ctx.lang, 'assistBy')} ${n(i.assist_id)})` : ''} · ${ctx.num(`${i.score_home}–${i.score_away}`)}`
    case 'sub': return `▲ ${n(i.player_in_id)}  ▼ ${n(i.player_out_id)}`
    case 'big_chance': return `${n(i.player_id)} · xG ${ctx.num((i.xg ?? 0).toFixed(2))}`
    case 'woodwork': return `${n(i.player_id)} · xG ${ctx.num((i.xg ?? 0).toFixed(2))}`
    default: return n(i.player_id)
  }
}

function TimelineTab({ state, ctx }: { state: State; ctx: Ctx }) {
  const items = timeline(state.incidents)
  if (!items.length) return <p className="empty">{dt(ctx.lang, 'noIncidents')}</p>
  return (
    <ol className="cd-timeline">
      {items.map(i => {
        const team = i.team_id === ctx.hello.home.id ? ctx.hello.home : ctx.hello.away
        return (
          <li key={i.id} data-testid="timeline-item" data-kind={i.kind} className={`k-${i.kind}`}>
            <span className="tl-minute">{ctx.num(i.minute)}'</span>
            <span className="tl-icon">
              {i.kind === 'yellow' ? <Card kind="yellow" /> : i.kind === 'red' || i.kind === 'second_yellow' ? <Card kind="red" />
                : i.kind === 'goal' ? '●' : i.kind === 'sub' ? '⇅' : '○'}
            </span>
            <span className="tl-body">
              <b>{dt(ctx.lang, `inc_${i.kind}` as DeskKey)}</b> <span className="tl-team"><Bar color={ctx.colors[team.id]} />{team.short_name}</span>
              <span className="tl-text">{incidentText(i, ctx)}</span>
            </span>
          </li>
        )
      })}
    </ol>
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

// ---------- production (CD-15, CD-16) ----------

function ProductionTab({ state, ctx }: { state: State; ctx: Ctx }) {
  return (
    <div className="cd-production">
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
  const { state } = useMatch(matchId, profile)
  const [tab, setTab] = useState<Tab>('stats')
  const [used, setUsed] = useState<Set<string>>(() => loadUsed(matchId))
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

  const toggleUsed = (id: string) => setUsed(prev => {
    const next = new Set(prev)
    if (next.has(id)) next.delete(id)
    else next.add(id)
    saveUsed(matchId, next)
    return next
  })

  // CD-18: 1-6 switch panels, U marks the next talking point as used.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || (e.target as HTMLElement)?.closest('input, textarea, select')) return
      const n = Number(e.key)
      if (n >= 1 && n <= TABS.length) setTab(TABS[n - 1])
      else if (e.key.toLowerCase() === 'u') {
        const id = topOpenPoint(state.feed, used)
        if (id) toggleUsed(id)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  })

  if (!h) return <div className="cd" data-testid="desk"><p className="empty">{t(lang, 'kickOffSoon')}</p></div>
  const ctx: Ctx = { lang, hello: h, colors, names, num: v => localDigits(v, lang) }
  const tabLabel = (id: Tab) => id === 'timeline' ? dt(lang, 'timeline') : id === 'season' ? dt(lang, 'season')
    : id === 'production' ? dt(lang, 'production') : id === 'momentum' ? t(lang, 'momentumChart') : t(lang, id)

  return (
    <div className="cd" dir={lang === 'ar' ? 'rtl' : 'ltr'} data-testid="desk">
      <Header state={state} ctx={ctx} setLang={setLang} />
      <main className="cd-main">
        <Lineup club={h.home} side="home" state={state} ctx={ctx} season={h.season?.home} />
        <TalkingPoints state={state} ctx={ctx} used={used} toggle={toggleUsed} />
        <section className="cd-panel cd-tabs" dir={lang === 'ar' ? 'rtl' : 'ltr'}>
          <div className="cd-tablist" role="tablist">
            {TABS.map((id, i) => (
              <button key={id} role="tab" aria-selected={tab === id} onClick={() => setTab(id)} title={`${i + 1}`}>{tabLabel(id)}</button>
            ))}
          </div>
          <div className="cd-scroll" role="tabpanel">
            {tab === 'stats' && <StatsTab state={state} ctx={ctx} />}
            {tab === 'timeline' && <TimelineTab state={state} ctx={ctx} />}
            {tab === 'momentum' && (
              <div className="cd-momentum">
                <AttackMomentumChart state={state} colors={colors} names={names} lang={lang} topTeam={null} />
                <ZoneMap state={state} colors={colors} lang={lang} compact />
              </div>
            )}
            {tab === 'season' && <SeasonTab ctx={ctx} />}
            {tab === 'production' && <ProductionTab state={state} ctx={ctx} />}
            {tab === 'recap' && <Recaps state={state} lang={lang} />}
          </div>
        </section>
        <Lineup club={h.away} side="away" state={state} ctx={ctx} season={h.season?.away} />
      </main>
    </div>
  )
}
