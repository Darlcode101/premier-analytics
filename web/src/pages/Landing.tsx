import QRCode from 'qrcode'
import { useEffect, useState } from 'react'
import { createMatch, fetchClubs, type ClubSummary } from '../api'
import { LANGUAGE_NAMES, t } from '../i18n'
import type { Language } from '../types'

const SPEEDS: [number, string][] = [[1, '1×'], [10, '10×'], [30, '30×'], [60, '60×']]

function QR({ url }: { url: string }) {
  const [svg, setSvg] = useState('')
  useEffect(() => {
    QRCode.toString(url, { type: 'svg', margin: 1, color: { dark: '#37003c', light: '#ffffff' } }).then(setSvg)
  }, [url])
  return <div className="qr" data-testid="qr" aria-hidden dangerouslySetInnerHTML={{ __html: svg }} />
}

export function Landing({ lang, setLang }: { lang: Language; setLang: (l: Language) => void }) {
  const [clubs, setClubs] = useState<ClubSummary[]>([])
  const [home, setHome] = useState('har')
  const [away, setAway] = useState('ngc')
  const [seed, setSeed] = useState(42)
  const [speed, setSpeed] = useState(10)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [matchId, setMatchId] = useState<string | null>(new URLSearchParams(location.search).get('match'))

  useEffect(() => { fetchClubs().then(setClubs).catch(e => setError(String(e))) }, [])

  const start = async () => {
    setBusy(true)
    setError('')
    try {
      const id = await createMatch(home, away, seed, speed)
      setMatchId(id)
      history.replaceState(null, '', `/?match=${id}`)
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
    } finally {
      setBusy(false)
    }
  }

  const fanUrl = matchId ? `${location.origin}/fan?match=${matchId}&lang=${lang}` : ''
  const deskUrl = matchId ? `/desk?match=${matchId}&lang=${lang}` : ''
  const club = (id: string) => clubs.find(c => c.id === id)

  return (
    <div className="landing">
      <header className="landing-top">
        <div className="wordmark"><span className="mark" aria-hidden /> {t(lang, 'appTitle')}</div>
        <div className="lang-switch" role="group" aria-label={t(lang, 'language')}>
          {(['en', 'es', 'ar'] as const).map(l => (
            <button key={l} aria-pressed={lang === l} onClick={() => setLang(l)}>{LANGUAGE_NAMES[l]}</button>
          ))}
        </div>
      </header>

      <main className="landing-main">
        <section className="landing-hero">
          <h1>{t(lang, 'tagline')}</h1>
          <p className="fictional">{t(lang, 'fictional')}</p>
        </section>

        {!matchId && (
          <section className="landing-card" aria-labelledby="setup-title">
            <h2 id="setup-title">{t(lang, 'newMatch')}</h2>
            <div className="fixture-pick">
              <label>
                <span>{t(lang, 'home')}</span>
                <select id="home" value={home} onChange={e => setHome(e.target.value)}>
                  {clubs.map(c => <option key={c.id} value={c.id} disabled={c.id === away}>{c.name}</option>)}
                </select>
              </label>
              <span className="vs">v</span>
              <label>
                <span>{t(lang, 'away')}</span>
                <select id="away" value={away} onChange={e => setAway(e.target.value)}>
                  {clubs.map(c => <option key={c.id} value={c.id} disabled={c.id === home}>{c.name}</option>)}
                </select>
              </label>
            </div>
            <div className="fixture-pick">
              <label>
                <span>{t(lang, 'seed')}</span>
                <span className="seed-row">
                  <input id="seed" type="number" min={0} value={seed} onChange={e => setSeed(Number(e.target.value))} />
                  <button className="pill-btn" onClick={() => setSeed(Math.floor(Math.random() * 100_000))}>{t(lang, 'random')}</button>
                </span>
              </label>
              <label>
                <span>{t(lang, 'speed')}</span>
                <span className="segmented" role="group" aria-label={t(lang, 'speed')}>
                  {SPEEDS.map(([v, text]) => <button key={v} aria-pressed={speed === v} onClick={() => setSpeed(v)}>{text}</button>)}
                </span>
              </label>
            </div>
            <button className="cta" onClick={start} disabled={busy || !clubs.length}>{t(lang, 'kickOff')}</button>
            {error && <p className="error" role="alert">{error}</p>}
          </section>
        )}

        {matchId && (
          <section className="landing-card ready" aria-labelledby="ready-title">
            <h2 id="ready-title">{t(lang, 'matchReady')}</h2>
            {club(home) && club(away) && <p className="fixture-line">{club(home)!.name} v {club(away)!.name}</p>}
            <div className="surfaces">
              <a className="surface fan" href={fanUrl} data-testid="fan-link">
                <QR url={fanUrl} />
                <strong>{t(lang, 'openFan')}</strong>
                <small>{t(lang, 'scanToOpen')}</small>
              </a>
              <a className="surface desk" href={deskUrl} data-testid="desk-link">
                <span className="desk-icon" aria-hidden />
                <strong>{t(lang, 'openDesk')}</strong>
                <small>{t(lang, 'deskTitle')}</small>
              </a>
            </div>
            <button className="pill-btn" onClick={() => { setMatchId(null); history.replaceState(null, '', '/') }}>{t(lang, 'newMatch')}</button>
          </section>
        )}
      </main>
    </div>
  )
}
