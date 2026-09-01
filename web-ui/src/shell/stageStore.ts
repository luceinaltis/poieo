/**
 * Owns the stage: the feed, the catch-up reads, and who to tell when it moves.
 *
 * Framework-free on purpose. The interesting behaviour here is ordering, not
 * rendering, and it is easier to be sure of it without a component in the way.
 */

import {
  fetchTasks as defaultFetchTasks,
  fetchRunEvents as defaultFetchRunEvents,
  fetchRuns as defaultFetchRuns,
  openFeed as defaultOpenFeed,
} from "../api"
import type { FeedStatus } from "../api"
import { WINDOW, initialStage, keyOfTask, reduce, replay, setRuns } from "../state/stage"
import type { StageState, TaskState } from "../state/stage"
import type { ProjectRow, TaskRow, PoieoEvent } from "../types"

export interface StageApi {
  fetchTasks: typeof defaultFetchTasks
  fetchRunEvents: typeof defaultFetchRunEvents
  fetchRuns: typeof defaultFetchRuns
  openFeed: typeof defaultOpenFeed
}

/** How far back the review window reaches. The stage owns the number: the
 * card's tally and this list have to be the same runs. */
export const REVIEW_LIMIT = WINDOW

export interface StageStore {
  getStage(): StageState
  getTasks(): TaskRow[]
  /** Whose board this is -- every project the daemon runs. Empty until the
   *  first listing answers. */
  getProjects(): ProjectRow[]
  getStatus(): FeedStatus
  subscribe(listener: () => void): () => void
  start(): Promise<void>
  resync(): Promise<void>
  stop(): void
}

/**
 * Fold a fresh task listing into what we already have.
 *
 * `/api/tasks` is authoritative about what finished -- a run that ended while
 * the feed was down published a summary nobody heard, and this is where that
 * gap closes. Live-only detail (the current node, the last turn) is kept.
 */
function isChangedSummary(event: PoieoEvent): boolean {
  return (
    event.type === "run_summary" &&
    event.status === "completed" &&
    event.change !== undefined
  )
}

function reflectedChangedRuns(events: PoieoEvent[]): Map<string, string[]> {
  const reflected = new Map<string, string[]>()
  for (const event of events) {
    if (
      !isChangedSummary(event) ||
      typeof event.task !== "string" ||
      typeof event.project !== "string"
    ) {
      continue
    }
    const task = keyOfTask(event.project, event.task)
    reflected.set(task, [...(reflected.get(task) ?? []), event.run_id])
  }
  return reflected
}

function seed(state: StageState, rows: TaskRow[], reflectedEvents: PoieoEvent[] = []): StageState {
  const fresh = initialStage(rows).tasks
  const tasks: Record<string, TaskState> = {}
  const reflected = reflectedChangedRuns(reflectedEvents)

  for (const [name, blank] of Object.entries(fresh)) {
    const existing = state.tasks[name]
    const reflectedRuns = reflected.get(name) ?? []
    if (!existing) {
      tasks[name] = {
        ...blank,
        countedChangeRuns: new Set(
          [...blank.countedChangeRuns, ...reflectedRuns].slice(-REVIEW_LIMIT),
        ),
      }
      continue
    }
    const listedRunClearsError =
      (blank.lastRun?.status === "completed" || blank.lastRun?.status === "asking") &&
      (existing.lastRun === null ||
        existing.lastRun.status !== blank.lastRun.status ||
        existing.lastRun.finished_at !== blank.lastRun.finished_at)
    tasks[name] = {
      ...existing,
      tracked: blank.tracked,
      // Structure is the listing's to state, not the event stream's: a graph
      // edited while the page was open arrives here or nowhere.
      then: blank.then,
      shape: blank.shape,
      trigger: blank.trigger,
      stale: blank.stale,
      enabled: blank.enabled,
      pending: blank.pending,
      countedChangeRuns: new Set(
        [
          ...existing.countedChangeRuns,
          ...blank.countedChangeRuns,
          ...reflectedRuns,
        ].slice(-REVIEW_LIMIT),
      ),
      asking: blank.asking,
      lastRun: blank.lastRun ?? existing.lastRun,
      // Whether a hold is on is the daemon's to say, never the event
      // stream's: no frame is published when somebody presses pause.
      held: blank.held,
      // The listing wins except while the feed knows about a failure that its
      // last run does not yet supersede. A newer completed or asking run clears
      // that old failure; the same older run cannot. Held reaches here from
      // `blank`, so a pause pressed while this page was open survives the read.
      status:
        blank.status === "waiting" &&
        existing.status === "error" &&
        !listedRunClearsError
          ? "error"
          : blank.status,
    }
  }
  return { ...state, tasks }
}

export function createStageStore(api: StageApi = {
  fetchTasks: defaultFetchTasks,
  fetchRunEvents: defaultFetchRunEvents,
  fetchRuns: defaultFetchRuns,
  openFeed: defaultOpenFeed,
}): StageStore {
  let stage = initialStage([])
  let tasks: TaskRow[] = []
  let projects: ProjectRow[] = []
  let status: FeedStatus = "connecting"
  let closeFeed: (() => void) | null = null

  // While a catch-up read is open, live frames wait their turn: history is
  // older than they are, so folding it in afterwards would walk the board
  // backwards, and dropping them loses events whose run is not known yet.
  let holding = false
  let held: PoieoEvent[] = []
  let changedSummaryRevision = 0

  const listeners = new Set<() => void>()
  const announce = () => {
    for (const listener of listeners) listener()
  }

  function take(event: PoieoEvent): void {
    if (isChangedSummary(event)) changedSummaryRevision += 1
    if (holding) {
      held.push(event)
      return
    }
    const next = reduce(stage, event)
    if (next === stage) return
    stage = next
    announce()
  }

  /** The run index knows what a night amounted to; the event stream does not.
   *
   * Asked together, not one task after another: live frames queue until the
   * catch-up read finishes, so it should cost one round trip's latency, not N.
   */
  async function tally(current: StageState, rows: TaskRow[]): Promise<StageState> {
    const tallies = await Promise.all(
      rows.map(async (row) => ({
        row,
        runs: await api.fetchRuns({
          task: row.name,
          project: row.project,
          limit: REVIEW_LIMIT,
        }),
      })),
    )
    let next = current
    for (const { row, runs } of tallies) {
      next = setRuns(next, keyOfTask(row.project, row.name), runs)
    }
    return next
  }

  /**
   * A changed frame seen during catch-up crosses two independent HTTP/SSE
   * connections, so response order cannot prove which snapshot included it.
   * Read the authoritative count again after that frame; repeat only if
   * another changed frame crosses the follow-up read too.
   */
  async function refreshListingAfterChanges(): Promise<void> {
    holding = true
    held = []
    try {
      while (true) {
        const revisionBeforeRead = changedSummaryRevision
        const listing = await api.fetchTasks()
        tasks = listing.tasks
        projects = listing.projects
        const stable = revisionBeforeRead === changedSummaryRevision
        stage = seed(stage, tasks, stable ? held : [])
        if (stable) break
      }
    } finally {
      const queued = held
      holding = false
      held = []
      stage = replay(stage, queued)
      announce()
    }
  }

  async function resync(): Promise<void> {
    const revisionBeforeRead = changedSummaryRevision
    holding = true
    held = []
    try {
      const listing = await api.fetchTasks()
      tasks = listing.tasks
      projects = listing.projects
      stage = seed(stage, tasks)

      // Both reads are independent of each other; fetch everything at once
      // and fold in the same order the sequential code did.
      const running = tasks.filter((row) => row.current_run_id)
      const [tallied, histories] = await Promise.all([
        tally(stage, tasks),
        Promise.all(running.map((row) => api.fetchRunEvents(row.current_run_id!))),
      ])
      stage = tallied
      for (const events of histories) stage = replay(stage, events)
    } finally {
      const queued = held
      holding = false
      held = []
      stage = replay(stage, queued)
      announce()
    }
    if (changedSummaryRevision !== revisionBeforeRead) {
      await refreshListingAfterChanges()
    }
  }

  return {
    getStage: () => stage,
    getTasks: () => tasks,
    getProjects: () => projects,
    getStatus: () => status,

    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },

    async start() {
      // Paint something before the socket opens: if the feed never connects,
      // the board should still say what the daemon is running.
      const listing = await api.fetchTasks()
      tasks = listing.tasks
      projects = listing.projects
      stage = seed(stage, tasks)
      stage = await tally(stage, tasks)
      announce()

      closeFeed = api.openFeed({
        onEvent: take,
        onStatus(next) {
          status = next
          announce()
        },
        onResync() {
          void resync()
        },
      })
    },

    resync,

    stop() {
      closeFeed?.()
      closeFeed = null
    },
  }
}
