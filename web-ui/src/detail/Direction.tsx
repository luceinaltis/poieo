import { useState } from "react"
import { leaveDirection } from "../api"
import { useAct } from "../useAct"

export function Direction({ project, task }: { project: string; task: string }) {
  const [text, setText] = useState("")
  const [saved, setSaved] = useState(false)
  const { busy, refused, act } = useAct(() => { setText(""); setSaved(true) })
  return <details className="task-direction">
    <summary>Give direction (optional)</summary>
    <label className="apply-field">
      What should the next run keep in mind?
      <textarea rows={3} maxLength={4000} value={text} disabled={busy}
        onChange={(event) => { setText(event.target.value); setSaved(false) }} />
    </label>
    <button type="button" disabled={busy || !text.trim()}
      onClick={() => void act(() => leaveDirection(project, task, text.trim()))}>
      {busy ? "Saving…" : "Save direction"}
    </button>
    {saved ? <p role="status">Saved for the next run.</p> : null}
    {refused ? <p role="alert">{refused.error}</p> : null}
  </details>
}
