/**
 * What one flowState has been doing, in detail.
 *
 * The drawer is shell UI, not a skin, so it is allowed to read the API. It
 * keeps its own state throughout: picking a past run here must never move the
 * live board.
 */

import { memo, useEffect, useMemo, useState } from "react"

import { fetchRunEvents, fetchRuns } from "../api"
import { Control } from "./Control"
import { Decide } from "../review/Decide"
import { Diff } from "../review/Diff"
import { RunList } from "../review/RunList"
import { initialStage, replay } from "../state/stage"
import type { FlowState } from "../state/stage"
import type { PoieoEvent, RunSummary } from "../types"
import { shortTime } from "../when"
import "./drawer.css"

function Entry({ event }: { event: PoieoEvent }) {
  const data = event.data ?? {}

  if (event.type === "node_turn") {
    const text = String(data.text ?? "")
    const thinking = String(data.thinking ?? "")
    return (
      <li className="drawer-entry" data-kind="turn">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div>
          <div className="drawer-label">
            {event.node_id} · turn {String(data.turn ?? "")}
          </div>
          {text ? <p className="drawer-text">{text}</p> : null}
          {thinking ? (
            <details className="drawer-thinking">
              <summary>thinking</summary>
              <p>{thinking}</p>
            </details>
          ) : null}
        </div>
      </li>
    )
  }

  if (event.type === "node_tool_call") {
    const failed = typeof data.error === "string" && data.error.length > 0
    return (
      <li className="drawer-entry" data-kind="tool" data-error={String(failed)}>
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div>
          <div className="drawer-label">
            {String(data.name ?? "")} · {String(data.duration_ms ?? 0)}ms
          </div>
          {failed ? <p className="drawer-text">{String(data.error)}</p> : null}
        </div>
      </li>
    )
  }

  if (event.type === "node_started") {
    return (
      <li className="drawer-entry" data-kind="node">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-label">
          {event.node_id} · {String(data.type ?? "")}
        </div>
      </li>
    )
  }

  if (event.type === "run_failed" || event.type === "run_aborted") {
    return (
      <li className="drawer-entry" data-kind="tool" data-error="true">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <p className="drawer-text">{String(data.error ?? data.reason ?? "stopped")}</p>
      </li>
    )
  }

  return null
}

// Memoized because the shell re-renders on every SSE frame: a drawer being
// read must not re-reconcile its whole timeline because another flow spoke.
export const Drawer = memo(function Drawer({
  flow,
  status = "waiting",
  pending = 0,
  into = null,
  onClose,
  onDecided,
}: {
  flow: string
  status?: string
  pending?: number
  into?: string | null
  onClose(): void
  onDecided?(): void
}) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [picked, setPicked] = useState<string | null>(null)
  const [events, setEvents] = useState<PoieoEvent[]>([])
  const [reload, setReload] = useState(0)

  useEffect(() => {
    let live = true
    void fetchRuns({ flow, limit: 10 }).then((rows) => {
      if (!live) return
      setRuns(rows)
      setPicked(
        (current) =>
          current ?? rows.find((row) => row.change)?.run_id ?? rows[0]?.run_id ?? null,
      )
    })
    return () => {
      live = false
    }
  }, [flow, reload])

  const decided = () => {
    setReload((n) => n + 1)
    onDecided?.()
  }

  useEffect(() => {
    if (!picked) {
      setEvents([])
      return
    }
    let live = true
    void fetchRunEvents(picked).then((list) => {
      if (live) setEvents(list)
    })
    return () => {
      live = false
    }
  }, [picked])

  // A stage of its own: replaying here must leave the live board alone.
  const replayed: FlowState | null = useMemo(() => {
    if (events.length === 0) return null
    const scratch = initialStage([
      {
        name: flow,
        graph: "",
        trigger: "",
        status: "waiting",
        current_run_id: null,
        last_run: null,
        pending: 0,
        into: null,
        then: [],
        shape: { entry: "", nodes: [] },
      },
    ])
    return replay(scratch, events).flows[flow] ?? null
  }, [events, flow])

  return (
    <aside className="drawer" data-flow={flow}>
      <header className="drawer-head">
        <h2>{flow}</h2>
        <button type="button" onClick={onClose} aria-label="Close">
          close
        </button>
      </header>

      <div className="drawer-body">
        <Control flow={flow} status={status} onActed={decided} />

        <Decide flow={flow} pending={pending} into={into} runId={null} onDone={decided} />

        <RunList
          runs={runs}
          selected={picked}
          onSelect={setPicked}
          tracked={into !== null}
          controls={(run) =>
            run.change ? (
              <Decide
                flow={flow}
                pending={pending}
                into={into}
                runId={run.run_id}
                onDone={decided}
              />
            ) : null
          }
        />

        {picked ? <Diff runId={picked} /> : null}

        {replayed ? (
          <p className="drawer-summary">
            {replayed.currentNode ?? "finished"}
            {replayed.turn > 0 ? ` · ${replayed.turn} turn(s)` : ""}
          </p>
        ) : null}

        <ol className="drawer-timeline">
          {events.map((event, index) => (
            <Entry key={`${event.type}-${index}`} event={event} />
          ))}
        </ol>
      </div>
    </aside>
  )
})
