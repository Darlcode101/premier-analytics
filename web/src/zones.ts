// Ball location as one of 9 zones (R-2). Coordinates are the shared pitch from the backend:
// 105 x 68 m, y = 0 is the top touchline, home attacks towards x = 105 in the first half.

export type Third = 'defensive' | 'middle' | 'final'
export type Channel = 'left' | 'centre' | 'right'

const L = 105
const W = 68
export const PITCH_L = L
export const PITCH_W = W

const band = (v: number, size: number) => Math.min(2, Math.max(0, Math.floor((v / size) * 3)))

/** Grid cell on screen: col 0..2 left to right, row 0..2 top to bottom. */
export function cellOf(x: number, y: number): { col: number; row: number } {
  return { col: band(x, L), row: band(y, W) }
}

export function attacksRight(team: string, period: number, homeId: string): boolean {
  return (team === homeId) === (period === 1)
}

/** Zone named from the point of view of a team attacking right (or left). */
export function describeZone(x: number, y: number, attackingRight: boolean): { third: Third; channel: Channel } {
  const { col, row } = cellOf(attackingRight ? x : L - x, attackingRight ? y : W - y)
  // Facing +x on a screen whose y grows downwards, the top touchline is on your left.
  return {
    third: (['defensive', 'middle', 'final'] as const)[col],
    channel: (['left', 'centre', 'right'] as const)[row],
  }
}

/** Mirror the pitch so the viewer's favourite club always attacks to the right. */
export function mirrorFor(favouriteId: string | null, period: number, homeId: string): boolean {
  return favouriteId !== null && !attacksRight(favouriteId, period, homeId)
}
