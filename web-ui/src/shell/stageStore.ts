/**
 * Owns the stage: the feed, the catch-up reads, and who to tell when it moves.
 *
 * Framework-free on purpose. The interesting behaviour here is ordering, not
 * rendering, and it is easier to be sure of it without a component in the way.
 */

import {
  fetchFlows as defaultFetchFlows,
  fetchRunEvents as defaultFetchRunEvents,
  openFeed as defaultOpenFeed,
} from "../api"
import type { FeedStatus } from "../api"
import { initialStage, reduce, replay } from "../state/stage"
import type { StageState, Worker } from "../state/stage"
import type { FlowRow, PoieoEvent } from "../types"

export interface StageApi {
  fetchFlows: typeof defaultFetchFlows
  fetchRunEvents: typeof defaultFetchRunEvents
  openFeed: typeof defaultOpenFeed
}

export interface StageStore {
  getStage(): StageState
  getFlows(): FlowRow[]
  getStatus(): FeedStatus
  subscribe(listener: () => void): () => void
  start(): Promise<void>
  resync(): Promise<void>
  stop(): void
}

/**
 * Fold a fresh flow listing into what we already have.
 *
 * `/api/flows` is authoritative about what finished -- a run that ended while
 * the feed was down published a summary nobody heard, and this is where that
 * gap closes. Live-only detail (the current node, the last turn) is kept.
 */
function seed(state: StageState, flows: FlowRow[]): StageState {
  const fresh = initialStage(flows).workers
  const workers: Record<string, Worker> = {}

  for (const [name, blank] of Object.entries(fresh)) {
    const existing = state.workers[name]
    if (!existing) {
      workers[name] = blank
      continue
    }
    workers[name] = {
      ...existing,
      lastRun: blank.lastRun ?? existing.lastRun,
      status:
        blank.status === "running"
          ? "running"
          : existing.status === "error"
            ? "error"
            : "waiting",
    }
  }
  return { ...state, workers }
}

export function createStageStore(api: StageApi = {
  fetchFlows: defaultFetchFlows,
  fetchRunEvents: defaultFetchRunEvents,
  openFeed: defaultOpenFeed,
}): StageStore {
  let stage = initialStage([])
  let flows: FlowRow[] = []
  let status: FeedStatus = "connecting"
  let closeFeed: (() => void) | null = null

  // While a catch-up read is open, live frames wait their turn: history is
  // older than they are, so folding it in afterwards would walk the board
  // backwards, and dropping them loses events whose run is not known yet.
  let holding = false
  let held: PoieoEvent[] = []

  const listeners = new Set<() => void>()
  const announce = () => {
    for (const listener of listeners) listener()
  }

  function take(event: PoieoEvent): void {
    if (holding) {
      held.push(event)
      return
    }
    const next = reduce(stage, event)
    if (next === stage) return
    stage = next
    announce()
  }

  async function resync(): Promise<void> {
    holding = true
    held = []
    try {
      flows = await api.fetchFlows()
      stage = seed(stage, flows)

      for (const row of flows) {
        if (!row.current_run_id) continue
        stage = replay(stage, await api.fetchRunEvents(row.current_run_id))
      }
    } finally {
      const queued = held
      holding = false
      held = []
      stage = replay(stage, queued)
      announce()
    }
  }

  return {
    getStage: () => stage,
    getFlows: () => flows,
    getStatus: () => status,

    subscribe(listener) {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },

    async start() {
      // Paint something before the socket opens: if the feed never connects,
      // the board should still say what the daemon is running.
      flows = await api.fetchFlows()
      stage = seed(stage, flows)
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
