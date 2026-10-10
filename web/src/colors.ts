import type { ClubInfo } from './types'

function luminance(hex: string): number {
  const n = parseInt(hex.replace('#', ''), 16)
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255].map(v => {
    const c = v / 255
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4
  })
  return 0.2126 * r + 0.7152 * g + 0.0722 * b
}

function distance(a: string, b: string): number {
  const pa = parseInt(a.slice(1), 16)
  const pb = parseInt(b.slice(1), 16)
  return Math.hypot(((pa >> 16) & 255) - ((pb >> 16) & 255), ((pa >> 8) & 255) - ((pb >> 8) & 255), (pa & 255) - (pb & 255))
}

/** A readable colour for each side on a dark UI; the away side switches to its second kit if the two clash. */
export function teamColors(home: ClubInfo, away: ClubInfo): Record<string, string> {
  const readable = (c: [string, string]) => (luminance(c[0]) < 0.06 ? c[1] : c[0])
  const h = readable(home.colors)
  let a = readable(away.colors)
  if (distance(h, a) < 120) a = a === away.colors[0] ? away.colors[1] : away.colors[0]
  return { [home.id]: h, [away.id]: a }
}

/** Primary kit colours for light surfaces (the fan app); away switches to its second kit on a clash. */
export function kitColors(home: ClubInfo, away: ClubInfo): Record<string, string> {
  const h = home.colors[0]
  const a = distance(h, away.colors[0]) < 120 ? away.colors[1] : away.colors[0]
  return { [home.id]: h, [away.id]: a }
}
