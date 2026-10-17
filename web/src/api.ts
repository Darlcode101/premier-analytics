import { useEffect, useReducer, useRef, useState } from 'react'
import { initialState, reducer, type Action, type State } from './state'
import type { AskResult, Language, Message, Profile } from './types'

export interface ClubSummary {
  id: string
  name: string
  short_name: string
  colors: [string, string]
  players: { id: string; name: string; number: number; position: string }[]
}

export async function fetchClubs(): Promise<ClubSummary[]> {
  const r = await fetch('/api/clubs')
  if (!r.ok) throw new Error(`clubs: ${r.status}`)
  return r.json()
}

export async function createMatch(home: string, away: string, seed: number, speed: number): Promise<string> {
  const r = await fetch('/api/matches', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ home, away, seed, speed }),
  })
  if (!r.ok) {
    const detail = await r.json().catch(() => ({}))
    throw new Error(detail.detail ?? `Could not start match (${r.status})`)
  }
  return (await r.json()).match_id
}

/** The desk's ask box (CX-3): a sourced web answer, capped per match. */
export async function askQuestion(matchId: string, question: string, language: Language): Promise<AskResult> {
  try {
    const r = await fetch(`/api/matches/${matchId}/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, language }),
    })
    if (!r.ok) return { status: 'error', text: '', sources: [], remaining: 0 }
    return await r.json()
  } catch {
    return { status: 'error', text: '', sources: [], remaining: 0 }
  }
}

function socketUrl(matchId: string, p: Profile): string {
  const q = new URLSearchParams({ mode: p.mode, language: p.language })
  if (p.club_id) q.set('club_id', p.club_id)
  if (p.player_id) q.set('player_id', p.player_id)
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  return `${proto}://${location.host}/ws/matches/${matchId}?${q}`
}

/** Live match state for one viewer profile. Reconnects (keeping the pitch context) when the profile changes. */
export function useMatch(matchId: string | null, profile: Profile): {
  state: State; connected: boolean; dispatch: (a: Action) => void; send: (msg: object) => void
} {
  const [state, dispatch] = useReducer(reducer, initialState)
  const [connected, setConnected] = useState(false)
  const socketRef = useRef<WebSocket | null>(null)
  const finished = useRef(false)
  finished.current = state.status === 'finished'

  useEffect(() => {
    if (!matchId) return
    let socket: WebSocket | null = null
    let retry: number | undefined
    let closedByUs = false

    const connect = () => {
      socket = new WebSocket(socketUrl(matchId, profile))
      socketRef.current = socket
      socket.onopen = () => setConnected(true)
      socket.onmessage = ev => dispatch(JSON.parse(ev.data) as Message)
      socket.onclose = () => {
        setConnected(false)
        if (!closedByUs && !finished.current) retry = window.setTimeout(connect, 1500)
      }
    }
    connect()
    return () => {
      closedByUs = true
      window.clearTimeout(retry)
      socket?.close()
    }
  }, [matchId, profile.mode, profile.language, profile.club_id, profile.player_id]) // eslint-disable-line react-hooks/exhaustive-deps

  // Desk -> server (GP-4: mark a talking point used). Dropped while reconnecting; the server state wins.
  const send = (msg: object) => {
    if (socketRef.current?.readyState === WebSocket.OPEN) socketRef.current.send(JSON.stringify(msg))
  }
  return { state, connected, dispatch, send }
}
