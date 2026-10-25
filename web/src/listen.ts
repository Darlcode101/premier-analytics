// FC-1: the Listen button. Azure AI Speech in the browser, with a keyless token from the app and a phrase list of
// the match's players and clubs (feasibility check 10-17: without it "Kowalczyk" came back as "Kowal 6").
// Audio goes straight to Azure Speech; each recognised line is sent to the app to be checked, then dropped.
import { fetchSpeechToken } from './api'
import type { Hello, Language } from './types'

const SPEECH_LANGUAGES: Record<Language, string> = {
  en: 'en-GB', es: 'es-ES', ar: 'ar-SA', fr: 'fr-FR', de: 'de-DE', it: 'it-IT', pt: 'pt-BR', nl: 'nl-NL', tr: 'tr-TR',
  zh: 'zh-CN', ja: 'ja-JP', ko: 'ko-KR', hi: 'hi-IN',
}
export const speechLanguage = (lang: Language) => SPEECH_LANGUAGES[lang]

/** Every player's full name and surname, and both clubs, once each. */
export function phrasesFor(h: Hello): string[] {
  const out = new Set<string>()
  for (const c of [h.home, h.away]) {
    out.add(c.short_name)
    out.add(c.name)
    for (const p of [...c.lineup, ...c.bench]) {
      out.add(p.name)
      out.add(p.name.split(' ').slice(-1)[0])
    }
  }
  return [...out]
}

export type ListenStatus = 'listening' | 'unavailable' | 'mic_error' | 'off'

export async function startListening(h: Hello, lang: Language, onLine: (text: string) => void,
  onStatus: (s: ListenStatus) => void, onHearing: (text: string) => void = () => {}): Promise<() => void> {
  const auth = await fetchSpeechToken()
  if (auth.status !== 'ok' || !auth.token || !auth.region) {
    onStatus('unavailable')
    return () => {}
  }
  const sdk = await import('microsoft-cognitiveservices-speech-sdk')  // loaded only when someone listens
  const config = sdk.SpeechConfig.fromAuthorizationToken(auth.token, auth.region)
  config.speechRecognitionLanguage = speechLanguage(lang)
  const recognizer = new sdk.SpeechRecognizer(config, sdk.AudioConfig.fromDefaultMicrophoneInput())
  sdk.PhraseListGrammar.fromRecognizer(recognizer).addPhrases(phrasesFor(h))
  recognizer.recognized = (_s, e) => {
    if (e.result.reason === sdk.ResultReason.RecognizedSpeech && e.result.text.trim()) onLine(e.result.text.trim())
  }
  // 10-25: show words as they are heard, so the desk visibly responds while the commentator is still talking.
  recognizer.recognizing = (_s, e) => { if (e.result.text) onHearing(e.result.text) }
  recognizer.canceled = () => onStatus('mic_error')
  // Entra tokens for Speech last about 10 minutes: refresh well before.
  const refresh = window.setInterval(async () => {
    const next = await fetchSpeechToken()
    if (next.token) recognizer.authorizationToken = next.token
  }, 8 * 60_000)
  try {
    await new Promise<void>((resolve, reject) => recognizer.startContinuousRecognitionAsync(resolve, reject))
    onStatus('listening')
  } catch {
    window.clearInterval(refresh)
    onStatus('mic_error')
    recognizer.close()
    return () => {}
  }
  return () => {
    window.clearInterval(refresh)
    recognizer.stopContinuousRecognitionAsync(() => recognizer.close(), () => recognizer.close())
    onStatus('off')
  }
}
