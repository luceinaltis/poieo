import { useState } from "react"
import { leaveDirection } from "../api"
import type { DirectionAnswer } from "../api"
import { useAct } from "../useAct"

export function Direction({ project, task }: { project: string; task: string }) {
  const [text, setText] = useState("")
  // Where the last direction went, said in its own words: a run in flight
  // hears it at its next turn, and the next run reads it at its start.
  const [heard, setHeard] = useState<"delivered" | "saved" | null>(null)
  const { busy, refused, act } = useAct<DirectionAnswer>((answer) => {
    setText("")
    setHeard(answer.status === "delivered" ? "delivered" : "saved")
  })
  return <details className="task-direction">
    <summary>Give direction (optional)</summary>
    <label className="apply-field">
      What should the next run keep in mind?
      <textarea rows={3} maxLength={4000} value={text} disabled={busy}
        onChange={(event) => { setText(event.target.value); setHeard(null) }} />
    </label>
    <button type="button" disabled={busy || !text.trim()}
      onClick={() => void act(() => leaveDirection(project, task, text.trim()))}>
      {busy ? "Saving…" : "Save direction"}
    </button>
    {heard === "delivered" ? <p role="status">Delivered to the run in flight: it hears it at its next model turn, and the journal keeps it either way.</p> : null}
    {heard === "saved" ? <p role="status">Saved for the next run.</p> : null}
    {refused ? <p role="alert">{refused.error}</p> : null}
  </details>
}
