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
import { initialStage, keyOfTask, replay, subjectOf } from "../state/stage"
import type { TaskState } from "../state/stage"
import type { PoieoEvent, RunSummary } from "../types"
import { shortTime } from "../when"
import "./drawer.css"

/**
 * What the model said, without letting one long answer bury the run.
 *
 * A model that wrote six paragraphs pushed everything after it off the
 * screen, and the timeline is a sequence -- what came next is the point of
 * reading it. Long answers fold; short ones are just a paragraph, because a
 * disclosure triangle on two lines is furniture.
 */
const LONG = 240

function Said({ text }: { text: string }) {
  if (text.length <= LONG) return <p className="drawer-text">{text}</p>
  const opening = text.trim().split(/\r?\n/).find((line) => line.trim()) ?? text
  return (
    <details className="drawer-said">
      <summary>{opening.slice(0, 120)}…</summary>
      <p className="drawer-text">{text}</p>
    </details>
  )
}

/**
 * A run's timeline, in the words of somebody watching rather than the words
 * of the machinery running it.
 *
 * Six lines used to carry four machine words -- the node's id, the node's
 * type, the turn counter and a millisecond count -- which is the vocabulary
 * DESIGN.md's principle 7 spends its whole budget avoiding everywhere else.
 * The step's name stays, because the author chose it and it is on the board
 * too; what goes is everything that describes the loop rather than the work.
 */
function Entry({ event }: { event: PoieoEvent }) {
  const data = event.data ?? {}

  if (event.type === "node_turn") {
    const text = String(data.text ?? "")
    const thinking = String(data.thinking ?? "")
    // A model that reached straight for a tool leaves a turn with nothing in
    // it. The tool calls below already say the turn happened, so an empty row
    // here is only a gap in the timeline.
    if (!text && !thinking) return null
    // The turn number is the loop's bookkeeping. What a reader wants from a
    // second turn is that the model spoke again, which the entry already is.
    return (
      <li className="drawer-entry" data-kind="turn">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div>
          {text ? <Said text={text} /> : null}
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
    // The daemon writes a boolean here, and the message a reader wants is in
    // `result` either way -- a failing tool explains itself there.
    const failed = data.error === true
    // Milliseconds only when they are worth a reader's attention. A tool that
    // answered instantly said "0ms" on every line and meant nothing by it.
    const ms = Number(data.duration_ms ?? 0)
    const slow = ms >= 1000 ? ` · ${(ms / 1000).toFixed(1)}s` : ""
    const subject = subjectOf(data.arguments)
    const result = String(data.result ?? "")
    return (
      <li className="drawer-entry" data-kind="tool" data-error={String(failed)}>
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div>
          <div className="drawer-label">
            {String(data.name ?? "")}
            {subject ? ` ${subject}` : ""}
            {slow}
          </div>
          {result ? <p className="drawer-result">{result}</p> : null}
        </div>
      </li>
    )
  }

  if (event.type === "node_context_cleared") {
    // A step whose history quietly shrinks is a step nobody can reason about
    // afterwards -- least of all when the question is why it stopped. The
    // results are gone from the conversation, not from the disk, and the line
    // says which by naming what was kept.
    const freed = Number(data.freed ?? 0)
    const kept = Number(data.kept ?? 0)
    return (
      <li className="drawer-entry" data-kind="cleared">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-label">
          {`cleared ${freed.toLocaleString("en-US")} characters of older results, `}
          {`keeping the last ${kept}`}
        </div>
      </li>
    )
  }

  if (event.type === "run_change_failed" || event.type === "node_compact_failed") {
    // Housekeeping that could not do its job. Neither stops the work, which
    // is exactly why both have to be seen: a run whose change was never
    // recorded reads as a run that had nothing to do, and every `then:`
    // written against `run.change` quietly stops firing while the board goes
    // on showing green.
    const what =
      event.type === "run_change_failed"
        ? "the change could not be recorded"
        : "the older turns could not be folded"
    return (
      <li className="drawer-entry" data-kind="stuck">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div>
          <div className="drawer-label">{what}</div>
          <p className="drawer-text">{String(data.error ?? "")}</p>
        </div>
      </li>
    )
  }

  if (event.type === "node_started") {
    // The step's name, and nothing about what kind of node it is: `agent` and
    // `router` are how the graph is built, not what is happening.
    return (
      <li className="drawer-entry" data-kind="node">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-label">{event.node_id}</div>
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
// read must not re-reconcile its whole timeline because another task spoke.
export const Drawer = memo(function Drawer({
  project,
  task,
  status = "waiting",
  pending = 0,
  into = null,
  onClose,
  onDecided,
}: {
  project: string
  task: string
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
    void fetchRuns({ task, project, limit: 10 }).then((rows) => {
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
  }, [task, reload])

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
  const replayed: TaskState | null = useMemo(() => {
    if (events.length === 0) return null
    const scratch = initialStage([
      {
        name: task,
        project,
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
    return replay(scratch, events).tasks[keyOfTask(project, task)] ?? null
  }, [events, project, task])

  return (
    <aside className="drawer" data-task={task}>
      <header className="drawer-head">
        <h2>{task}</h2>
        <button type="button" onClick={onClose} aria-label="Close">
          close
        </button>
      </header>

      <div className="drawer-body">
        <Control project={project} task={task} status={status} onActed={decided} />

        <Decide project={project} task={task} pending={pending} into={into} runId={null} onDone={decided} />

        <RunList
          runs={runs}
          selected={picked}
          onSelect={setPicked}
          tracked={into !== null}
          controls={(run) =>
            run.change ? (
              <Decide
                project={project}
                task={task}
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
            {replayed.turn > 1 ? ` · turn ${replayed.turn}` : ""}
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
