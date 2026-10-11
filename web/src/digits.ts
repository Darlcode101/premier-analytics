import type { Language } from './types'

const EASTERN = '٠١٢٣٤٥٦٧٨٩'

/** Display-time digits for the viewer's language: Eastern Arabic digits (and ٫ ٪) in Arabic.
 *  Data, AI text and the Critic all keep Western digits; this only changes what is drawn. */
export function localDigits(value: string | number, lang: Language): string {
  const s = String(value)
  if (lang !== 'ar') return s
  return s
    .replace(/(?<=\d)\.(?=\d)/g, '٫')
    .replace(/%/g, '٪')
    .replace(/\d/g, d => EASTERN[Number(d)])
}
