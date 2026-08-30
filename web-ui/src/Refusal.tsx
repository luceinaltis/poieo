/**
 * What a refusal looks like, wherever the reader hit one.
 *
 * `useAct` is the state half of every writing surface -- refuse to fire twice,
 * keep the last refusal to show. This is the other half: the one line that
 * shows it. There were five of them, one per surface, and what they had in
 * common was a sentence to fall back on when the daemon refused without saying
 * why. Four carried it and the fifth did not, so a refusal with an empty
 * `error` left a disabled button, a form that would not clear, and nothing on
 * screen to explain either.
 *
 * **`ok: false` with no sentence is a real shape, not a defensive guess.**
 * `post` builds its answer as `{ok: response.ok, ...payload}` over a body that
 * may have failed to parse to `{}`, so any 4xx that does not answer in JSON
 * arrives here with nothing to say. The fallback is what that case reads as.
 *
 * A surface with more to add passes it as children -- the choices a question
 * will accept, the providers a binding declares. The daemon's own sentence
 * comes first either way, because it is the specific one.
 */

import type { ReactNode } from "react"

import type { Answer } from "./api"

export function Refusal({ answer, children }: { answer?: Answer; children?: ReactNode }) {
  return (
    // Announced, not just coloured: a refusal is the one thing on this page a
    // reader may be waiting on, and red is not available to everybody.
    <p className="refusal" role="alert">
      {answer ? answer.error || "That didn't work." : null}
      {children}
    </p>
  )
}
