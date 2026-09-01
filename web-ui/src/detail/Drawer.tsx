/**
 * One task's controls, run history, change, and event timeline.
 *
 * The drawer owns its selected historical run so reading it never moves the
 * live board.
 */

import { memo, useEffect, useId, useLayoutEffect, useRef, useState } from "react"

import { fetchRunEvents, fetchRuns } from "../api"
import { Card } from "./Card"
import { Control } from "./Control"
import { Question } from "./Question"
import { Decide } from "../review/Decide"
import { Diff } from "../review/Diff"
import { accountOf, durationOf, RunList, sizeOf } from "../review/RunList"
import { outcomeOf } from "../review/rollup"
import { subjectOf } from "../state/stage"
import type { PoieoEvent, Question as Asked, RunSummary } from "../types"
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
const MAX_INLINE_OUTPUT_LENGTH = 240

function appearsInTimeline(event: PoieoEvent): boolean {
  if (event.type === "node_turn") {
    const data = event.data ?? {}
    // A turn that reached for tools is the preamble to those calls. Each call
    // now carries the useful sentence itself, so showing both makes one action
    // read like two. Answering turns still stand on their own below.
    if (Number(data.tool_call_count ?? 0) > 0) return false
    return Boolean(String(data.text ?? "") || String(data.thinking ?? ""))
  }
  return [
    "node_tool_call",
    "node_context_cleared",
    "node_input_dropped",
    "run_change_failed",
    "node_compact_failed",
    "node_started",
    "run_failed",
    "run_aborted",
  ].includes(event.type)
}

type ToolArguments = Record<string, unknown>

function parsedArguments(raw: unknown): ToolArguments | null {
  let value = raw
  if (typeof raw === "string") {
    try {
      value = JSON.parse(raw)
    } catch {
      return null
    }
  }
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as ToolArguments)
    : null
}

function commandPurpose(command: string): string {
  const prDiff = command.match(/(?:^|\s)gh\s+pr\s+diff\s+(\d+)/i)
  if (prDiff) return `Review the changes in PR #${prDiff[1]}`
  const prChecks = command.match(/(?:^|\s)gh\s+pr\s+checks\s+(\d+)/i)
  if (prChecks) return `Check whether PR #${prChecks[1]} passed its checks`
  const prView = command.match(/(?:^|\s)gh\s+pr\s+view\s+(\d+)/i)
  if (prView) return `Check the status of PR #${prView[1]}`
  if (/\b(?:pytest|vitest|npm\s+test|ruff|tsc\s+-b)(?:\s|$)/i.test(command)) {
    return "Run the relevant verification checks"
  }
  if (/\bgit\s+merge-base\s+--is-ancestor\b/i.test(command)) {
    return "Check whether the candidate includes its base"
  }

  const search = command.match(/\b(?:rg|grep)\b[^;|]*?(?:"([^"]+)"|'([^']+)')/i)
  if (search) {
    const pattern = (search[1] || search[2]).replaceAll("\\\"", '"')
    return `Search the project for “${pattern.slice(0, 80)}${pattern.length > 80 ? "…" : ""}”`
  }

  const cat = command.match(/\b(?:cat|type|Get-Content)\s+(?:-[^\s]+\s+)*(?:"([^"]+)"|'([^']+)'|([^\s;|]+))/i)
  if (cat) return `Read ${cat[1] || cat[2] || cat[3]}`

  const sedSegment = command.match(/\bsed\b([^;|]*)/i)?.[1] ?? ""
  const sedFiles = sedSegment.match(/(?:[\w.-]+[\\/])*[\w.-]+\.[A-Za-z0-9]+/g)
  if (sedFiles?.length) return `Read ${sedFiles[sedFiles.length - 1]}`

  const listing = command.match(/\b(?:ls|dir|Get-ChildItem)\s+(?:-[^\s]+\s+)*([^\s;|]+)/i)
  if (listing) return `Look through ${listing[1]}`

  const checkout = command.match(
    /\bgit\s+(?:checkout|switch)\b(?:\s+--?[\w-]+)*\s+([^\s;|]+)/i,
  )
  if (checkout) return `Switch to ${checkout[1]}`

  const show = command.match(/\bgit\s+show\b(?:\s+--?[\w=-]+)*\s+([^\s;|]+)/i)
  if (show) return `Inspect ${show[1]}`

  if (/\b(?:python|python3|py)\b[^;]*(?:-c|<<)/i.test(command)) {
    return "Inspect behavior with Python"
  }
  if (/Independent review/i.test(command)) return "Prepare the independent review"
  if (/(?:^|\s)git\s+status(?:\s|$)/i.test(command)) return "Check the working tree"
  if (/(?:^|\s)git\s+diff(?:\s|$)/i.test(command)) return "Review the current changes"
  if (/(?:^|\s)git\s+log(?:\s|$)/i.test(command)) return "Review recent commits"
  if (/(?:^|\s)git\s+fetch(?:\s|$)/i.test(command)) return "Refresh remote branch information"
  return "Run a command for this task"
}

/**
 * Older events predate agent-written purposes. Say only what their recorded
 * arguments prove; a guessed reason would be more polished and less true.
 */
function fallbackPurpose(name: string, raw: unknown): string {
  const args = parsedArguments(raw)
  const subject = subjectOf(raw)
  if (name === "run_command") {
    const command = args?.command
    return commandPurpose(typeof command === "string" ? command : subject)
  }
  if (name === "read_file") return subject ? `Read ${subject}` : "Read a file"
  if (["write_file", "edit_file", "append_file"].includes(name)) {
    return subject ? `Update ${subject}` : "Update a file"
  }
  if (name === "search_files") {
    return subject ? `Search the project for ${subject}` : "Search the project"
  }
  if (name === "glob_files") {
    return subject ? `Find files matching ${subject}` : "Find relevant files"
  }
  if (name === "list_dir") {
    return subject ? `Look through ${subject}` : "Look through the working folder"
  }
  if (name === "tell") return subject ? `Send an update to ${subject}` : "Send a task update"
  const words = name.replaceAll("_", " ").trim()
  return words ? words[0].toUpperCase() + words.slice(1) : "Continue the task"
}

function toolPurpose(data: Record<string, any>): string {
  const written = typeof data.purpose === "string" ? data.purpose.trim() : ""
  return written || fallbackPurpose(String(data.name ?? ""), data.arguments)
}

function displayArguments(raw: unknown, command: string): string {
  const parsed = parsedArguments(raw)
  if (!parsed) return command ? "" : String(raw ?? "")
  const rest = Object.fromEntries(Object.entries(parsed).filter(([key]) => key !== "command"))
  return Object.keys(rest).length ? JSON.stringify(rest, null, 2) : ""
}

function RunOutput({ text }: { text: string }) {
  if (text.length <= MAX_INLINE_OUTPUT_LENGTH) {
    return <p className="drawer-text">{text}</p>
  }
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
function TimelineEntry({ event }: { event: PoieoEvent }) {
  const data = event.data ?? {}

  if (event.type === "node_turn") {
    const text = String(data.text ?? "")
    const thinking = String(data.thinking ?? "")
    // A model that reached straight for a tool leaves a turn with nothing in
    // it. The tool calls below already say the turn happened, so an empty row
    // here is only a gap in the timeline.
    if (!text && !thinking) return null
    const sent = Number(data.input_tokens ?? 0)
    const wrote = Number(data.output_tokens ?? 0)
    // The turn number is the loop's bookkeeping. What a reader wants from a
    // second turn is that the model spoke again, which the entry already is.
    return (
      <li className="drawer-entry" data-kind="turn">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-event">
          {text ? <RunOutput text={text} /> : null}
          {thinking ? (
            <details className="drawer-thinking">
              <summary>thinking</summary>
              <p>{thinking}</p>
            </details>
          ) : null}
          {/* What this turn cost. The run's total says what the whole step
              spent; a reader chasing a step that slowed down wants to know
              which turn it happened on. */}
          {sent > 0 ? (
            <p className="drawer-cost">
              {`${sent.toLocaleString("en-US")} in`}
              {wrote > 0 ? ` · ${wrote.toLocaleString("en-US")} out` : ""}
            </p>
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
    const name = String(data.name ?? "")
    const purpose = toolPurpose(data)
    const args = parsedArguments(data.arguments)
    const command = typeof args?.command === "string" ? args.command : ""
    const otherArguments = displayArguments(data.arguments, command)
    const result = String(data.result ?? "")
    return (
      <li className="drawer-entry" data-kind="tool" data-error={String(failed)}>
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <details className="drawer-event drawer-tool">
          <summary aria-label={`Show details: ${purpose}`}>
            <span className="drawer-tool-purpose">{purpose}</span>
            <span className="drawer-tool-meta">
              {`${name || "tool"} · ${failed ? "failed" : "completed"}${slow}`}
            </span>
          </summary>
          <div className="drawer-tool-raw">
            <div className="drawer-tool-part">
              <span>Tool</span>
              <pre>{name || "unknown"}</pre>
            </div>
            {command ? (
              <div className="drawer-tool-part">
                <span>Command</span>
                <pre>{command}</pre>
              </div>
            ) : null}
            {otherArguments ? (
              <div className="drawer-tool-part">
                <span>{command ? "Options" : "Input"}</span>
                <pre>{otherArguments}</pre>
              </div>
            ) : null}
            {result ? (
              <div className="drawer-tool-part">
                <span>{command ? "Output" : "Result"}</span>
                <pre>{result}</pre>
              </div>
            ) : (
              <p className="drawer-tool-empty">No result was recorded.</p>
            )}
          </div>
        </details>
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
        <div className="drawer-event drawer-label">
          {`cleared ${freed.toLocaleString("en-US")} characters of older results, `}
          {`keeping the last ${kept}`}
        </div>
      </li>
    )
  }

  if (event.type === "node_input_dropped") {
    // What the endpoint kept against what it was sent. Both numbers, because
    // the gap is the news -- and because a run that ends badly later is
    // explained by this line more often than by anything after it.
    const before = Number(data.before ?? 0)
    const kept = Number(data.kept ?? 0)
    return (
      <li className="drawer-entry" data-kind="stuck">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-event">
          <div className="drawer-label">
            {`the endpoint kept ${kept.toLocaleString("en-US")} of `}
            {`${before.toLocaleString("en-US")} tokens it was sent`}
          </div>
          {data.note ? <p className="drawer-text">{String(data.note)}</p> : null}
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
        <div className="drawer-event">
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
        <div className="drawer-event drawer-label">{event.node_id}</div>
      </li>
    )
  }

  if (event.type === "run_failed" || event.type === "run_aborted") {
    return (
      <li className="drawer-entry" data-kind="tool" data-error="true">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <p className="drawer-event drawer-text">{String(data.error ?? data.reason ?? "stopped")}</p>
      </li>
    )
  }

  return null
}

type AttentionKind =
  | "answer"
  | "review"
  | "restart"
  | "failed"
  | "quiet"

function attentionOf({
  asking,
  pending,
  stale,
  status,
  latest,
}: {
  asking: Asked | null
  pending: number
  stale: string | null
  status: string
  latest: RunSummary | null
}): { kind: AttentionKind; text: string } {
  if (asking) return { kind: "answer", text: "Needs your answer" }
  if (pending > 0) {
    return {
      kind: "review",
      text: `${pending} change${pending === 1 ? "" : "s"} to review`,
    }
  }
  if (stale) return { kind: "restart", text: "Restart needed" }
  if (
    status === "error" ||
    (latest && latest.status !== "completed" && latest.status !== "asking")
  ) {
    return { kind: "failed", text: "Latest run failed" }
  }
  return { kind: "quiet", text: "No action needed" }
}

function briefAccountOf(run: RunSummary, tracked: boolean): string {
  if (run.status !== "completed" && run.status !== "asking") return accountOf(run, tracked)
  const line = (run.said ?? "")
    .trim()
    .split(/\r?\n/)
    .find((part) => part.trim())
  if (!line) return run.status === "asking" ? "waiting for your answer" : accountOf(run, tracked)
  return line.length > 180 ? line.slice(0, 180).trimEnd() + "…" : line
}

function runTime(run: RunSummary): number {
  const finished = Date.parse(run.finished_at)
  if (Number.isFinite(finished)) return finished
  const started = Date.parse(run.started_at)
  return Number.isFinite(started) ? started : Number.NEGATIVE_INFINITY
}

function RunBrief({
  run,
  latest,
  tracked,
  headingId,
}: {
  run: RunSummary | null
  latest: boolean
  tracked: boolean
  headingId: string
}) {
  if (!run) {
    return (
      <section className="run-brief" data-empty="true" aria-labelledby={headingId}>
        <h3 id={headingId}>Latest run</h3>
        <p className="run-empty">Nothing has run yet. Run now or wait for its schedule.</p>
      </section>
    )
  }

  const outcome = run.status === "asking" ? "waiting" : outcomeOf(run, tracked)
  const account = briefAccountOf(run, tracked)
  const duration = durationOf(run)
  const size = sizeOf(run)
  const verb = run.status === "completed" ? "Finished" : run.status === "asking" ? "Asked" : "Stopped"
  const meta = [`${verb} ${shortTime(run.finished_at)}`]
  if (duration) meta.push(duration)
  if (outcome === "nothing" && (run.said ?? "").trim()) meta.push("No files changed")
  if (size) meta.push(size)

  return (
    <section
      className="run-brief"
      data-run={run.run_id}
      data-outcome={outcome}
      data-change={String(Boolean(run.change))}
      aria-labelledby={headingId}
    >
      <h3 id={headingId}>{latest ? "Latest run" : "Selected run"}</h3>
      <p className="run-brief-what">{account}</p>
      <p className="run-brief-meta">{meta.join(" · ")}</p>
    </section>
  )
}

// Memoized because the shell re-renders on every SSE frame: a drawer being
// read must not re-reconcile its whole timeline because another task spoke.
export const Drawer = memo(function Drawer({
  project,
  task,
  status = "waiting",
  enabled = true,
  stale = null,
  pending = 0,
  into = null,
  asking = null,
  liveRuns = [],
  onClose,
  onDecided,
  onAlike,
}: {
  project: string
  task: string
  status?: string
  /** Whether the card file lets this task run at all. */
  enabled?: boolean
  /** Why the card file and the running task disagree, or null. */
  stale?: string | null
  pending?: number
  into?: string | null
  asking?: Asked | null
  /** The stage's live summary window, which can advance while this drawer is open. */
  liveRuns?: RunSummary[]
  onClose(): void
  onDecided?(): void
  /** "Make one like it", passed through to the card fold. */
  onAlike?(seed: { name: string; folder: string; prompt: string }): void
}) {
  const [runs, setRuns] = useState<RunSummary[]>([])
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null)
  const [selectedRunSnapshot, setSelectedRunSnapshot] = useState<RunSummary | null>(null)
  const [historyOpen, setHistoryOpen] = useState(false)
  const [activityOpen, setActivityOpen] = useState(false)
  const [events, setEvents] = useState<PoieoEvent[] | null>(null)
  const [activityLoading, setActivityLoading] = useState(false)
  const [activityError, setActivityError] = useState(false)
  const [refreshVersion, setRefreshVersion] = useState(0)
  const activityRequest = useRef(0)
  const drawerId = useId().replace(/[^a-zA-Z0-9_-]/g, "")
  const titleId = `drawer-${drawerId}-title`
  const briefId = `drawer-${drawerId}-brief`
  const historyId = `drawer-${drawerId}-runs`
  const activityId = `drawer-${drawerId}-activity`

  useEffect(() => {
    let live = true
    void fetchRuns({ task, project, limit: 10 }).then((rows) => {
      if (!live) return
      setRuns(rows)
    })
    return () => {
      live = false
    }
  }, [project, task, refreshVersion])

  const refreshAfterAction = () => {
    setRefreshVersion((version) => version + 1)
    onDecided?.()
  }

  const liveRunIds = new Set(liveRuns.map((run) => run.run_id))
  const mergedRuns = [
    ...liveRuns,
    ...runs.filter((run) => !liveRunIds.has(run.run_id)),
  ].sort((left, right) => runTime(right) - runTime(left))
  const availableRuns = mergedRuns.slice(0, 10)
  const latestRun = availableRuns[0] ?? null
  // A selected run may leave the ten-row history while the stage still holds
  // its later revision (notably an answered question). Keep the history
  // bounded, but take the selected snapshot from the full live window.
  const selectedAvailableRun = mergedRuns.find((row) => row.run_id === selectedRunId)
  const selectedRun =
    selectedAvailableRun ??
    (selectedRunSnapshot?.run_id === selectedRunId ? selectedRunSnapshot : null) ??
    latestRun
  const selectedRunKey = selectedRun?.run_id ?? null

  useEffect(() => {
    if (selectedRunId && selectedAvailableRun) setSelectedRunSnapshot(selectedAvailableRun)
  }, [selectedAvailableRun, selectedRunId])

  useLayoutEffect(() => {
    activityRequest.current += 1
    setActivityOpen(false)
    setEvents(null)
    setActivityLoading(false)
    setActivityError(false)
  }, [selectedRunKey])

  const selectedIsLatest = selectedRun?.run_id === latestRun?.run_id
  const tracked = into !== null
  const attention = attentionOf({ asking, pending, stale, status, latest: latestRun })
  const timelineEvents = events?.filter(appearsInTimeline) ?? null
  const reviewRunId =
    !selectedIsLatest && selectedRun?.change ? selectedRun.run_id : null

  const selectRun = (runId: string) => {
    setHistoryOpen(false)
    if (runId === latestRun?.run_id) {
      setSelectedRunId(null)
      setSelectedRunSnapshot(null)
      return
    }
    setSelectedRunId(runId)
    setSelectedRunSnapshot(availableRuns.find((run) => run.run_id === runId) ?? null)
  }

  const loadActivity = () => {
    const runId = selectedRun?.run_id
    if (!runId) return
    const request = ++activityRequest.current
    setActivityLoading(true)
    setActivityError(false)
    void fetchRunEvents(runId)
      .then((list) => {
        if (activityRequest.current !== request) return
        setEvents(list)
        setActivityLoading(false)
      })
      .catch(() => {
        if (activityRequest.current !== request) return
        setEvents(null)
        setActivityLoading(false)
        setActivityError(true)
      })
  }

  const toggleActivity = () => {
    if (activityOpen) {
      setActivityOpen(false)
      return
    }
    setActivityOpen(true)
    if (events === null && !activityLoading) loadActivity()
  }

  return (
    <aside className="panel drawer" data-task={task} aria-labelledby={titleId}>
      <header className="drawer-head">
        <div className="drawer-title">
          <h2 id={titleId}>{task}</h2>
          <p className="drawer-state" data-state={attention.kind} role="status">
            {attention.text}
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close">
          close
        </button>
      </header>

      <div className="drawer-body">
        {/* First, above the controls: everything after the question is held
            until it is answered, so a reader who misses it is looking at a
            run that has quietly stopped. */}
        <Question
          project={project}
          task={task}
          asking={asking}
          onAnswered={refreshAfterAction}
        />

        {pending > 0 ? (
          <Decide
            project={project}
            task={task}
            pending={pending}
            into={into}
            runId={reviewRunId}
            onDone={refreshAfterAction}
          />
        ) : null}

        {/* The daemon's own sentence, whole. The board's card carries the
            short form -- what to do -- because ten cards have no room for
            more; a reader who opened this one came for the rest of it. */}
        {stale ? (
          <p className="drawer-stale" role="status">
            {stale}
          </p>
        ) : null}

        <Control
          project={project}
          task={task}
          status={status}
          enabled={enabled}
          onActed={refreshAfterAction}
        />

        <div className="run-focus">
          <RunBrief
            run={selectedRun}
            latest={selectedIsLatest}
            tracked={tracked}
            headingId={briefId}
          />

          {selectedRun?.change ? <Diff runId={selectedRun.run_id} /> : null}

          {selectedRun ? (
            <section className="drawer-fold activity-fold">
              <button
                type="button"
                className="drawer-disclosure"
                data-do="toggle-activity"
                aria-expanded={activityOpen}
                aria-controls={activityId}
                onClick={toggleActivity}
              >
                {`Run activity${timelineEvents !== null ? ` (${timelineEvents.length})` : ""}`}
              </button>
              {activityOpen ? (
                <div id={activityId} className="drawer-fold-content activity-content">
                  {activityLoading ? (
                    <p className="activity-loading" role="status">
                      Loading activity…
                    </p>
                  ) : activityError ? (
                    <div className="activity-error" role="alert">
                      <p>Activity could not be loaded.</p>
                      <button type="button" data-do="retry-activity" onClick={loadActivity}>
                        try again
                      </button>
                    </div>
                  ) : timelineEvents?.length ? (
                    <ol className="drawer-timeline">
                      {timelineEvents.map((event, index) => (
                        <TimelineEntry key={`${event.type}-${index}`} event={event} />
                      ))}
                    </ol>
                  ) : (
                    <p className="activity-empty">No activity was recorded for this run.</p>
                  )}
                </div>
              ) : null}
            </section>
          ) : null}
        </div>

        {availableRuns.length > 0 ? (
          <section className="drawer-fold run-history">
            <button
              type="button"
              className="drawer-disclosure"
              data-do="toggle-runs"
              aria-expanded={historyOpen}
              aria-controls={historyId}
              onClick={() => setHistoryOpen((open) => !open)}
            >
              {`All runs (${availableRuns.length})`}
            </button>
            {historyOpen ? (
              <div id={historyId} className="drawer-fold-content">
                <RunList
                  runs={availableRuns}
                  selected={selectedRun?.run_id ?? null}
                  onSelect={selectRun}
                  tracked={tracked}
                />
              </div>
            ) : null}
          </section>
        ) : null}

        <Card
          project={project}
          task={task}
          onSetAside={refreshAfterAction}
          onAlike={onAlike}
        />
      </div>
    </aside>
  )
})
