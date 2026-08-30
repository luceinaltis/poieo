/**
 * The one way this page asks the daemon to change something.
 *
 * Every writing surface -- the review's accept/discard, the control strip's
 * pause/resume/run, a question's answer, making a card, and both of the models
 * panel's writes -- needs the same three things: refuse to fire twice, keep the
 * last refusal to show, and say whether the request went out at all. `busy` is
 * what drives `disabled`, which is what actually prevents the second click; the
 * guard inside is a second belt.
 *
 * **"Went out" is not "worked."** A refused request went out, and a caller that
 * reads the boolean as success empties its form over the refusal it is about to
 * show. Anything that turns on the *answer* reads the answer, inside the send:
 * `MakeTask` and the models panel's address form both do.
 */

import { useState } from "react"

import type { Answer } from "./api"

export interface Act<T extends Answer> {
  busy: boolean
  refused: T | null
  /** True if the request went out; false if one was already in flight. */
  act(send: () => Promise<T>): Promise<boolean>
}

/**
 * `onDone` is handed the answer, because "it worked" is not always the whole
 * story: a models write can land in the file and still be refused by the
 * running daemon, and only the answer says which. Callers that do not care
 * take no argument and are unaffected.
 */
export function useAct<T extends Answer>(onDone: (answer: T) => void): Act<T> {
  const [busy, setBusy] = useState(false)
  const [refused, setRefused] = useState<T | null>(null)

  const act = async (send: () => Promise<T>) => {
    if (busy) return false
    setBusy(true)
    setRefused(null)
    const answer = await send()
    setBusy(false)
    if (answer.ok) onDone(answer)
    else setRefused(answer)
    return true
  }

  return { busy, refused, act }
}
