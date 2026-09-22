/**
 * One task's controls, run history, change, and event timeline.
 *
 * The drawer owns its selected historical run so reading it never moves the
 * live board.
 */

import { memo, useEffect, useId, useLayoutEffect, useRef, useState } from "react"

import { fetchRunEvents, fetchRunMemory, fetchRuns, fetchRunSummary } from "../api"
import { Gauge } from "../Gauge"
import { Card } from "./Card"
import { Control } from "./Control"
import { Direction } from "./Direction"
import { Question } from "./Question"
import { Decide } from "../review/Decide"
import { Diff } from "../review/Diff"
import { ApplicationResult, applicationLabel } from "../review/ApplicationResult"
import { UndoChange } from "../review/UndoChange"
import { accountOf, durationOf, RunList, sizeOf } from "../review/RunList"
import { outcomeOf } from "../review/rollup"
import { Timeline, visibleTimelineEvents } from "./Timeline"
import type { Application, PoieoEvent, Question as Asked, RunMemory, RunSummary, ShownMemory } from "../types"
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

type AttentionKind =
  | "held"
  | "answer"
  | "review"
  | "restart"
  | "failed"
  | "quiet"

function attentionOf({
  asking,
  pending,
  stale,
  heldBecause,
  status,
  latest,
}: {
  asking: Asked | null
  pending: number
  stale: string | null
  heldBecause: string | null
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
  // Ahead of the failed run: a task that paused itself after three of them
  // has one thing to say, and it is why it stopped, not that the last one
  // failed too. The sentence itself is drawn below, whole.
  if (status === "paused" && heldBecause) return { kind: "held", text: "Paused" }
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

/**
 * What became of the run's change, in the words of the time line.
 *
 * Completed decisions keep their recorded outcome, including undo and work
 * already included. A blocked change still needs a decision; the checks say why.
 */
function describeApplication(application: Application | undefined, into: string | null): string | null {
  if (!application) return null
  if (application.status === "applied" && !application.undo_of && !application.unchanged && application.accepted !== 0) {
    return into ? `Applied to ${into}` : "Applied"
  }
  if (application.status === "review") return "Checked, waiting for review"
  if (application.status === "blocked") return "Not applied"
  return applicationLabel(application)
}

function RunBrief({
  run,
  latest,
  tracked,
  into,
  headingId,
  memory,
  onMemory,
}: {
  run: RunSummary | null
  latest: boolean
  tracked: boolean
  /** What an applied change was added to; null when the task keeps no copy. */
  into: string | null
  headingId: string
  /** What this run started with from memory, once it has been read. */
  memory?: RunMemory | null
  onMemory?(slug: string): void
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
  const applied = describeApplication(run.application, into)
  if (applied) meta.push(applied)

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
      {run.application ? <ApplicationResult result={run.application} /> : null}
      {memory && memory.run_id === run.run_id ? <PromptMakeup memory={memory} /> : null}
      {memory && memory.run_id === run.run_id ? <ShownMemory memory={memory} onMemory={onMemory} /> : null}
    </section>
  )
}

/**
 * What the run knew when it started, said the way a reader would ask it.
 *
 * The record says which entries recall put in front of the model and which
 * of them surfaced in what it wrote back -- the same judgement `poieo
 * memory` makes when it says how many runs used what they were shown.
 *
 * One sentence, inside the run's own box under its time line, and the rows
 * folded behind it. It sat below the box first, and read as a fact about
 * the task rather than about this run; the sentence starts with "This run"
 * for the same reason. Each row carries the entry's own opening words and a
 * plain word for what became of it, because a slug alone was a name a reader
 * had to open to understand. The ones that shaped the answer come first.
 *
 * Nothing is drawn when the record says nothing about memory (the project
 * kept none when this ran). An empty list is different, and says so -- as a
 * sentence, since there is nothing to unfold.
 */
/**
 * What the run's prompt was made of, each part against its budget: the page
 * and the memory entries have one, the journal only a size. Nothing is drawn
 * for a record written before runs measured this, and a part the record did
 * not measure is left out rather than drawn empty.
 */
function PromptMakeup({ memory }: { memory: RunMemory }) {
  const prompt = memory.prompt
  if (!prompt) return null
  return (
    <div className="run-prompt" data-run-prompt={memory.run_id} aria-label="What the prompt was made of">
      {prompt.page.chars !== null ? (
        <Gauge label="page" used={prompt.page.chars} limit={prompt.page.budget} unit="chars" />
      ) : null}
      {prompt.memory.chars !== null ? (
        <Gauge label="memory" used={prompt.memory.chars} limit={prompt.memory.budget} unit="chars" />
      ) : null}
      {prompt.journal.chars !== null ? (
        <Gauge label="journal" used={prompt.journal.chars} limit={null} unit="chars" />
      ) : null}
    </div>
  )
}

function ShownMemory({ memory, onMemory }: { memory: RunMemory; onMemory?(slug: string): void }) {
  if (!memory.shown) return null
  const shown = memory.shown
  if (!shown.length) {
    return <p className="run-memory-lead">This run started with nothing from memory.</p>
  }
  const used = shown.filter((one) => one.used === true)
  const rows = [...used, ...shown.filter((one) => one.used !== true)]
  const count = `${shown.length} memor${shown.length === 1 ? "y" : "ies"}`
  const became = (one: ShownMemory) =>
    one.used === true ? "shaped the answer" : one.used === false ? "seen, not used" : "seen; no longer in memory"
  return (
    <details className="run-memory">
      <summary className="run-memory-lead">
        {`This run started with ${count}; ${used.length ? used.length : "none"} shaped the answer.`}
      </summary>
      <ul className="run-memory-list">
        {rows.map((one) => (
          <li key={one.slug} data-used={one.used === null ? "unknown" : String(one.used)}>
            <button
              type="button"
              className="run-memory-open"
              data-memory={one.slug}
              disabled={!onMemory}
              onClick={() => onMemory?.(one.slug)}
            >
              {one.slug}
            </button>
            {one.preview ? <span className="run-memory-preview">{one.preview}</span> : null}
            <span className="run-memory-became">{became(one)}</span>
          </li>
        ))}
      </ul>
    </details>
  )
}

// Memoized because the shell re-renders on every SSE frame: a drawer being
// read must not re-reconcile its whole timeline because another task spoke.
export const Drawer = memo(function Drawer({
  project,
  task,
  title,
  status = "waiting",
  enabled = true,
  stale = null,
  heldBecause = null,
  pending = 0,
  into = null,
  asking = null,
  liveRuns = [],
  liveActivity = [],
  liveRunId = null,
  runId = null,
  onClose,
  onDecided,
  onAlike,
  onMemory,
}: {
  project: string
  task: string
  /**
   * What the card calls itself, for the heading. `task` is the file and the
   * identity every route here takes; when the two differ the name is said
   * under the title, because it is also what the rename field changes.
   */
  title?: string
  status?: string
  /** Whether the card file lets this task run at all. */
  enabled?: boolean
  /** Why the card file and the running task disagree, or null. */
  stale?: string | null
  /** Why the task is held, in the daemon's own words, or null. */
  heldBecause?: string | null
  pending?: number
  into?: string | null
  asking?: Asked | null
  /** The stage's live summary window, which can advance while this drawer is open. */
  liveRuns?: RunSummary[]
  /**
   * The newest run's timeline from the stage, event by event, and which run
   * it is. What the drawer follows rather than fetches, so a reader watches
   * the task act as it acts.
   */
  liveActivity?: PoieoEvent[]
  liveRunId?: string | null
  /**
   * A run to open on, named by id -- how a memory entry's source run is
   * reached. It may be older than the short history holds, so its row is
   * fetched on its own rather than looked for among the ten.
   */
  runId?: string | null
  onClose(): void
  onDecided?(): void
  /** "Make one like it", passed through to the card fold. */
  onAlike?(seed: { name: string; folder: string; prompt: string }): void
  /** Open the memory place at one entry this run was shown. */
  onMemory?(slug: string): void
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
  const [memory, setMemory] = useState<RunMemory | null>(null)
  const activityRequest = useRef(0)
  const memoryRequest = useRef(0)
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

  // Arriving on a named run. Its row is asked for by id rather than sought
  // among the ten: a memory entry's source is routinely older than that.
  useEffect(() => {
    if (!runId) return
    let live = true
    setHistoryOpen(false)
    setSelectedRunId(runId)
    void fetchRunSummary(runId).then((found) => {
      if (live && found) setSelectedRunSnapshot(found)
    })
    return () => {
      live = false
    }
  }, [runId])

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

  // A run in flight has no summary yet -- the index row is written when it
  // ends -- so it is not in the list a reader picks from, and "the latest
  // run" there is the one before it. Unless the reader picked an older run,
  // the stage's newest run is the one the activity is about, and it stays
  // so through the run's finish: the summary landing does not change which
  // run is being read, so it must not reset what is open.
  const watching = liveRunId !== null && (selectedRun?.run_id === liveRunId || selectedRunId === null)
  const following = watching && status === "running"
  // The run being followed, before it has a summary to be picked by.
  const inFlight = following && selectedRun?.run_id !== liveRunId
  const activityKey = watching ? liveRunId : selectedRunKey

  useLayoutEffect(() => {
    activityRequest.current += 1
    setActivityOpen(false)
    setEvents(null)
    setActivityLoading(false)
    setActivityError(false)
  }, [activityKey])

  // The record is written when the run ends, so a run watched to its finish
  // is asked again once its status settles -- hence the status in the deps.
  const selectedRunStatus = selectedRun?.status ?? null
  useEffect(() => {
    const request = ++memoryRequest.current
    setMemory(null)
    if (!selectedRunKey) return
    void fetchRunMemory(selectedRunKey).then((found) => {
      if (memoryRequest.current !== request) return
      setMemory(found)
    })
  }, [selectedRunKey, selectedRunStatus])

  const selectedIsLatest = selectedRun?.run_id === latestRun?.run_id
  const tracked = into !== null
  // Above a timeline streaming this run, the previous run's outcome would be
  // the drawer contradicting itself: while a run is in flight the attention
  // line and the brief speak of it, not of the one before.
  const attentionSaid = attentionOf({ asking, pending, stale, heldBecause, status, latest: inFlight ? null : latestRun })
  const attention = inFlight && attentionSaid.kind === "quiet" ? { kind: "quiet" as const, text: "Running now" } : attentionSaid
  const startedAt = inFlight ? (liveActivity.find((event) => event.type === "run_started")?.at ?? "") : ""
  // The newest run is read from the stage, which has its timeline from the
  // start, rather than fetched: its record is still being written while it
  // runs, and once it has finished the stage's copy is the whole of it.
  // Older runs are fetched when opened.
  const timelineSource = watching ? liveActivity : events
  const timelineEvents = timelineSource ? visibleTimelineEvents(timelineSource) : null
  const reviewRunId =
    !selectedIsLatest && selectedRun?.change ? selectedRun.run_id : null
  const selectedSettled = ["applied", "discarded", "undone"].includes(selectedRun?.application?.status ?? "")
  const canUndo = selectedRun?.application?.status === "applied" &&
    selectedRun.application.before && selectedRun.application.after &&
    !selectedRun.application.undo_of && !selectedRun.application.unchanged && selectedRun.application.accepted !== 0

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

  // A reader who opened a running task came to watch it: its activity opens
  // by itself, and again when the run list settles under it -- the reset on
  // `selectedRunKey` above would otherwise close what nobody closed. A
  // reader who closes it keeps it closed until the next run.
  useEffect(() => {
    if (following) setActivityOpen(true)
  }, [following, activityKey])

  const toggleActivity = () => {
    if (activityOpen) {
      setActivityOpen(false)
      return
    }
    setActivityOpen(true)
    if (events === null && !activityLoading && !watching) loadActivity()
  }

  return (
    <aside className="panel drawer" data-task={task} aria-labelledby={titleId}>
      <header className="drawer-head">
        <div className="drawer-title">
          <h2 id={titleId}>{title || task}</h2>
          {title && title !== task ? <p className="drawer-id">{task}</p> : null}
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

        {pending > 0 && !selectedSettled ? (
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

        {/* Why it is not running, above the button that would start it. A
            pause the reader pressed says so too, which is the honest sentence
            beside a resume button; the ones worth the room are the holds
            nobody pressed. */}
        {status === "paused" && heldBecause ? (
          <p className="drawer-held" role="status">
            {heldBecause}
          </p>
        ) : null}

        <Control
          project={project}
          task={task}
          status={status}
          enabled={enabled}
          onActed={refreshAfterAction}
        />
        <Direction key={`${project}/${task}`} project={project} task={task} />

        <div className="run-focus">
          {inFlight ? (
            <section className="run-brief" data-run={liveRunId ?? undefined} data-in-flight="true" aria-labelledby={briefId}>
              <h3 id={briefId}>Run in flight</h3>
              <p className="run-brief-what">{startedAt ? `Started ${shortTime(startedAt)}` : "Starting"}</p>
              <p className="run-brief-meta">Its outcome and change arrive when it ends.</p>
            </section>
          ) : (
            <RunBrief
              into={into}
              run={selectedRun}
              latest={selectedIsLatest}
              tracked={tracked}
              headingId={briefId}
              memory={memory}
              onMemory={onMemory}
            />
          )}

          {canUndo && selectedRun ? <UndoChange key={selectedRun.run_id} project={project} task={task}
            runId={selectedRun.run_id} onDone={refreshAfterAction} /> : null}
          {selectedRun && (selectedRun.change || selectedRun.application?.before) ? <Diff runId={selectedRun.run_id} /> : null}

          {selectedRun || watching ? (
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
                    <Timeline events={timelineEvents} following={following} />
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
