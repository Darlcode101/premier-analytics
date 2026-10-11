import type { ClubInfo } from './types'

export interface Side { club: ClubInfo; goals: number }

/** Scoreboard order: home on the left, unless the viewer's favourite club is pinned there. */
export function scoreboardSides(home: ClubInfo, away: ClubInfo, score: [number, number], favouriteId: string | null) {
  const h: Side = { club: home, goals: score[0] }
  const a: Side = { club: away, goals: score[1] }
  const flip = favouriteId === away.id
  return { left: flip ? a : h, right: flip ? h : a, pinned: favouriteId === home.id || favouriteId === away.id }
}
