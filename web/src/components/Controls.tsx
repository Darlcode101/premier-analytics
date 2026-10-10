import { LANGUAGE_NAMES, t } from '../i18n'
import type { Hello, Language, Mode, Profile } from '../types'

export function Segmented<T extends string>({ value, options, onChange, label }: {
  value: T; options: [T, string][]; onChange: (v: T) => void; label: string
}) {
  return (
    <div className="segmented" role="group" aria-label={label}>
      {options.map(([v, text]) => (
        <button key={v} aria-pressed={value === v} onClick={() => onChange(v)}>{text}</button>
      ))}
    </div>
  )
}

export function Controls({ profile, onChange, hello }: {
  profile: Profile; onChange: (p: Profile) => void; hello: Hello | null
}) {
  const lang = profile.language
  const players = hello ? [hello.home, hello.away].flatMap(c => [...c.lineup, ...c.bench].map(p => ({ ...p, club: c.short_name }))) : []
  return (
    <section className="card controls" aria-label={t(lang, 'watchAs')}>
      <div className="control-row">
        <span className="control-label">{t(lang, 'watchAs')}</span>
        <Segmented<Mode> label={t(lang, 'watchAs')} value={profile.mode}
          options={[['fan', t(lang, 'fan')], ['analyst', t(lang, 'analyst')]]}
          onChange={mode => onChange({ ...profile, mode })} />
      </div>
      <div className="control-row">
        <span className="control-label">{t(lang, 'language')}</span>
        <Segmented<Language> label={t(lang, 'language')} value={lang}
          options={(['en', 'es', 'ar'] as const).map(l => [l, LANGUAGE_NAMES[l]])}
          onChange={language => onChange({ ...profile, language })} />
      </div>
      {hello && (
        <>
          <div className="control-row">
            <label htmlFor="club">{t(lang, 'favouriteClub')}</label>
            <select id="club" value={profile.club_id ?? ''} onChange={e => onChange({ ...profile, club_id: e.target.value || null })}>
              <option value="">{t(lang, 'none')}</option>
              <option value={hello.home.id}>{hello.home.name}</option>
              <option value={hello.away.id}>{hello.away.name}</option>
            </select>
          </div>
          <div className="control-row">
            <label htmlFor="player">{t(lang, 'followPlayer')}</label>
            <select id="player" value={profile.player_id ?? ''} onChange={e => onChange({ ...profile, player_id: e.target.value || null })}>
              <option value="">{t(lang, 'none')}</option>
              {[hello.home, hello.away].map(c => (
                <optgroup key={c.id} label={c.name}>
                  {players.filter(p => p.club === c.short_name).map(p => (
                    <option key={p.id} value={p.id}>{p.number}. {p.name} ({p.position})</option>
                  ))}
                </optgroup>
              ))}
            </select>
          </div>
        </>
      )}
    </section>
  )
}
