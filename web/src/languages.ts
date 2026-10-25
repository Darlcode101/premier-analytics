// DK-12: the desk's 13 languages, each named in itself. Only Arabic is right to left.
export const LANGUAGES = ['en', 'es', 'ar', 'fr', 'de', 'it', 'pt', 'nl', 'tr', 'zh', 'ja', 'ko', 'hi'] as const
export type Language = typeof LANGUAGES[number]

export const isLanguage = (l: string | null): l is Language => l !== null && (LANGUAGES as readonly string[]).includes(l)

export const LANGUAGE_NAMES: Record<Language, string> = {
  en: 'English', es: 'Español', ar: 'العربية', fr: 'Français', de: 'Deutsch', it: 'Italiano', pt: 'Português',
  nl: 'Nederlands', tr: 'Türkçe', zh: '中文', ja: '日本語', ko: '한국어', hi: 'हिन्दी',
}

export const dirOf = (l: Language): 'rtl' | 'ltr' => (l === 'ar' ? 'rtl' : 'ltr')
