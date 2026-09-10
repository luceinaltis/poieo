import { undo } from "../api"
import type { Decision } from "../api"
import { useAct } from "../useAct"
import { applicationReason } from "./ApplicationResult"

export function UndoChange({ project, task, runId, onDone }: {
  project: string; task: string; runId: string; onDone(): void
}) {
  const { busy, refused, act } = useAct<Decision>(onDone)
  return <section className="undo-change">
    <p>Undo this applied change while preserving later work. The task pauses after undo.</p>
    <button type="button" disabled={busy} onClick={() => void act(() => undo(project, task, runId))}>
      {busy ? "Checking undo…" : "Undo this change"}
    </button>
    {refused ? <p role="alert">{applicationReason(refused) || "The change could not be undone."}</p> : null}
  </section>
}
