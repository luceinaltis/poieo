/**
 * Holding a task, waking it, running it right now.
 *
 * The other kind of write beside the review: these verbs touch the daemon's
 * runtime state and never the reader's files, so unlike Decide they need no
 * confirmation step. What they do need is honesty -- a refusal from the
 * daemon is shown, never swallowed.
 */

import { pause, resume, runNow } from "../api"
import type { ControlAnswer } from "../api"
import { Refusal } from "../Refusal"
import { useAct } from "../useAct"

export function Control({
  project,
  task,
  status,
  onActed,
}: {
  project: string
  task: string
  status: string
  onActed(): void
}) {
  const { busy, refused, act } = useAct<ControlAnswer>(onActed)

  const paused = status === "paused"
  const running = status === "running"

  return (
    <div className="control">
      {/* Pause stays offered while running: it takes effect between runs. */}
      <button
        type="button"
        data-do={paused ? "resume" : "pause"}
        disabled={busy}
        onClick={() => void act(() => (paused ? resume(project, task) : pause(project, task)))}
      >
        {paused ? "resume" : "pause"}
      </button>

      <button
        type="button"
        data-do="run-now"
        disabled={busy || running}
        onClick={() => void act(() => runNow(project, task))}
      >
        {running ? "running…" : "run now"}
      </button>

      {refused ? <Refusal answer={refused} /> : null}
    </div>
  )
}
