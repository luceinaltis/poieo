/**
 * The one way this page asks the daemon to change something.
 *
 * Both writing surfaces -- the review's accept/discard and the control
 * strip's pause/resume/run -- need the same three things: refuse to fire
 * twice, keep the last refusal to show, and tell the caller when something
 * really happened. `busy` is what drives `disabled`, which is what actually
 * prevents the second click; the guard inside is a second belt.
 */

import { useState } from "react"

import type { Answer } from "./api"

export interface Act<T extends Answer> {
  busy: boolean
  refused: T | null
  /** True if the request went out; false if one was already in flight. */
  act(send: () => Promise<T>): Promise<boolean>
}

export function useAct<T extends Answer>(onDone: () => void): Act<T> {
  const [busy, setBusy] = useState(false)
  const [refused, setRefused] = useState<T | null>(null)

  const act = async (send: () => Promise<T>) => {
    if (busy) return false
    setBusy(true)
    setRefused(null)
    const answer = await send()
    setBusy(false)
    if (answer.ok) onDone()
    else setRefused(answer)
    return true
  }

  return { busy, refused, act }
}
