/**
 * Holding a task, waking it, running it right now.
 *
 * The other kind of write beside the review: these verbs touch the daemon's
 * runtime state and never the reader's files, so unlike Decide they need no
 * confirmation step. What they do need is honesty -- a refusal from the
 * daemon is shown, never swallowed.
 */

import { useState } from "react"

import { pause, resume, runNow } from "../api"
import type { ControlAnswer } from "../api"

export function Control({
  flow,
  status,
  onActed,
}: {
  flow: string
  status: string
  onActed(): void
}) {
  const [busy, setBusy] = useState(false)
  const [refusal, setRefusal] = useState<string | null>(null)

  const act = async (go: () => Promise<ControlAnswer>) => {
    if (busy) return
    setBusy(true)
    setRefusal(null)
    const answer = await go()
    setBusy(false)
    if (answer.ok) onActed()
    else setRefusal(answer.error || "That didn't work.")
  }

  const paused = status === "paused"
  const running = status === "running"

  return (
    <div className="control">
      {/* Pause stays offered while running: it takes effect between runs. */}
      <button
        type="button"
        data-do={paused ? "resume" : "pause"}
        disabled={busy}
        onClick={() => void act(() => (paused ? resume(flow) : pause(flow)))}
      >
        {paused ? "resume" : "pause"}
      </button>

      <button
        type="button"
        data-do="run-now"
        disabled={busy || running}
        onClick={() => void act(() => runNow(flow))}
      >
        {running ? "running…" : "run now"}
      </button>

      {refusal ? <p className="control-refusal">{refusal}</p> : null}
    </div>
  )
}
