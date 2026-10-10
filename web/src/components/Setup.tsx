import { useEffect, useState } from 'react'
import { createMatch, fetchClubs, type ClubSummary } from '../api'
import { t } from '../i18n'
import type { Language } from '../types'

const SPEEDS: [number, string][] = [[1, '1×'], [10, '10×'], [30, '30×'], [60, '60×']]

export function Setup({ lang, onStart }: { lang: Language; onStart: (matchId: string) => void }) {
  const [clubs, setClubs] = useState<ClubSummary[]>([])
  const [home, setHome] = useState('har')
  const [away, setAway] = useState('ngc')
  const [seed, setSeed] = useState(42)
  const [speed, setSpeed] = useState(30)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    fetchClubs().then(setClubs).catch(e => setError(String(e)))
  }, [])

  const start = async () => {
    setBusy(true)
    setError('')
    try {
      onStart(await createMatch(home, away, seed, speed))
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e))
      setBusy(false)
    }
  }

  return (
    <section className="card setup" aria-labelledby="setup-title">
      <h1 id="setup-title">{t(lang, 'appTitle')}</h1>
      <p className="lead">{t(lang, 'tagline')}</p>
      <div className="grid2">
        <div className="control-row">
          <label htmlFor="home">{t(lang, 'home')}</label>
          <select id="home" value={home} onChange={e => setHome(e.target.value)}>
            {clubs.map(c => <option key={c.id} value={c.id} disabled={c.id === away}>{c.name}</option>)}
          </select>
        </div>
        <div className="control-row">
          <label htmlFor="away">{t(lang, 'away')}</label>
          <select id="away" value={away} onChange={e => setAway(e.target.value)}>
            {clubs.map(c => <option key={c.id} value={c.id} disabled={c.id === home}>{c.name}</option>)}
          </select>
        </div>
        <div className="control-row">
          <label htmlFor="seed">{t(lang, 'seed')}</label>
          <div style={{ display: 'flex', gap: 8 }}>
            <input id="seed" type="number" min={0} value={seed} onChange={e => setSeed(Number(e.target.value))} />
            <button className="ghost" onClick={() => setSeed(Math.floor(Math.random() * 100_000))}>{t(lang, 'random')}</button>
          </div>
        </div>
        <div className="control-row">
          <span className="control-label">{t(lang, 'speed')}</span>
          <div className="segmented" role="group" aria-label={t(lang, 'speed')}>
            {SPEEDS.map(([v, text]) => (
              <button key={v} aria-pressed={speed === v} onClick={() => setSpeed(v)}>{text}</button>
            ))}
          </div>
        </div>
      </div>
      <button className="primary" onClick={start} disabled={busy || !clubs.length}>{t(lang, 'kickOff')}</button>
      {error && <p className="error" role="alert">{error}</p>}
    </section>
  )
}
