/**
 * The one place run events are interpreted.
 *
 * Live SSE frames and replayed history are the same bytes, so they fold
 * through the same reducer -- replay is the live path at a different speed.
 * Everything downstream (every skin, the drawer) reads the stage model and
 * never an event, which is what lets a new skin be one module and one line.
 */

import { NOTHING, rollup } from "../review/rollup"
import type { Rollup } from "../review/rollup"
import type { Arrow, FlowRow, GraphShape, PoieoEvent, RunSummary } from "../types"

export interface ToolCall {
  name: string
  error: string | null
  at: string
}

export interface LastRun {
  status: string
  steps: number
  finished_at: string
}

export interface Worker {
  status: "waiting" | "running" | "error"
  currentNode: string | null
  nodeType: string | null
  step: number
  turn: number
  lastText: string
  lastThinking: string
  recentToolCalls: ToolCall[]
  lastRun: LastRun | null
  /**
   * What this flow has done lately, for the card line.
   *
   * "Lately" is the window the run index hands back, not a clock-based night:
   * the work list below the card shows those same runs, so the tally and the
   * list always agree, which is the property a reader would notice breaking.
   */
  recent: Rollup
  /**
   * The window itself, newest first, which `recent` is only the sum of.
   *
   * Kept rather than folded away because a sum cannot forget its oldest term:
   * folding each live summary into a running total, as this used to, walked
   * the number past the window every night a page was left open, and nothing
   * short of a reconnect brought it back.
   */
  runs: RunSummary[]
  /** Whether this flow keeps a private copy, and so can have changes at all. */
  tracked: boolean
  /**
   * The wiring: which flow works next, and what this one walks on the way.
   *
   * Structure rather than state -- it changes only when a file does, while
   * everything above it moves every few seconds. A view that draws both keeps
   * them apart for exactly that reason: the layout is settled once, and only
   * the highlight moves after that.
   */
  then: Arrow[]
  shape: GraphShape
  /** How this flow is scheduled, as the daemon describes it. Structure too. */
  trigger: string
}

/**
 * How far back the tally reaches, in finished runs.
 *
 * The same window the work list below a flow is fetched with, and it has to
 * stay the same: the card's number and that list are the same runs, or a
 * reader has no way to tell which of the two is lying.
 */
export const WINDOW = 50

export interface StageState {
  workers: Record<string, Worker>
  /** Learned from run_started: no other event says which flow it belongs to. */
  runFlow: Record<string, string>
  /** Dedup keys for the history/live overlap. Retired when a run ends. */
  seen: Set<string>
}

const TOOL_CALL_CAP = 8

const asString = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback

const asNumber = (value: unknown, fallback = 0): number =>
  typeof value === "number" ? value : fallback

function blankWorker(): Worker {
  return {
    status: "waiting",
    currentNode: null,
    nodeType: null,
    step: 0,
    turn: 0,
    lastText: "",
    lastThinking: "",
    recentToolCalls: [],
    lastRun: null,
    recent: NOTHING,
    runs: [],
    tracked: false,
    then: [],
    shape: { entry: "", nodes: [] },
    trigger: "",
  }
}

export function initialStage(flows: FlowRow[]): StageState {
  const workers: Record<string, Worker> = {}
  for (const row of flows) {
    workers[row.name] = {
      ...blankWorker(),
      tracked: row.into !== null,
      then: row.then,
      shape: row.shape,
      trigger: row.trigger,
      status: row.status === "running" ? "running" : "waiting",
      lastRun: row.last_run
        ? {
            status: row.last_run.status,
            steps: row.last_run.steps,
            finished_at: row.last_run.finished_at,
          }
        : null,
    }
  }
  return { workers, runFlow: {}, seen: new Set() }
}

/**
 * Events carry no order index, so identity is the fields plus the timestamp:
 * a duplicate is the *same* event twice and matches on all of them, while two
 * real events always differ in type, node, step or turn.
 */
function keyOf(event: PoieoEvent): string {
  const data = event.data ?? {}
  const ordinal = data.step ?? data.turn ?? ""
  return [event.run_id, event.type, event.node_id ?? "", ordinal, event.at ?? ""].join("|")
}

function flowFor(state: StageState, event: PoieoEvent): string | null {
  if (event.type === "run_started") {
    // Ad-hoc `poieo run` executions have no flow and do not belong on a board
    // of daemon flows.
    const flow = event.data?.flow
    return typeof flow === "string" ? flow : null
  }
  return state.runFlow[event.run_id] ?? null
}

/** null = an event this build does not know; {} = known, but nothing to show. */
function patchFor(event: PoieoEvent, worker: Worker): Partial<Worker> | null {
  const data = event.data ?? {}

  switch (event.type) {
    case "run_started":
      return {
        status: "running",
        currentNode: null,
        nodeType: null,
        step: 0,
        turn: 0,
        lastText: "",
        lastThinking: "",
        recentToolCalls: [],
      }

    case "node_started":
      return {
        currentNode: event.node_id ?? null,
        nodeType: asString(data.type, "") || null,
        step: asNumber(data.step),
        turn: 0,
      }

    case "node_turn":
      return {
        turn: asNumber(data.turn),
        lastText: asString(data.text),
        lastThinking: asString(data.thinking),
      }

    case "node_tool_call":
      return {
        recentToolCalls: [
          {
            name: asString(data.name),
            error: typeof data.error === "string" ? data.error : null,
            at: event.at ?? "",
          },
          ...worker.recentToolCalls,
        ].slice(0, TOOL_CALL_CAP),
      }

    case "node_finished":
      // Deliberately nothing: the next node_started replaces currentNode, and
      // clearing it here would blink the board empty between every step.
      return {}

    case "run_finished":
      return { status: "waiting", currentNode: null }

    case "run_failed":
    case "run_aborted":
      return { status: "error", currentNode: null }

    default:
      return null // forward compat: a new backend event must not break an old build
  }
}

/**
 * `run_summary` is the odd frame out: BroadcastStore publishes it flat, so its
 * fields sit beside `type` rather than under `data`, and it names its own flow.
 * It is also the last word on a run, so it retires that run's bookkeeping.
 */
function applySummary(state: StageState, event: PoieoEvent): StageState {
  const flow = asString(event.flow, "")
  if (!flow || !(flow in state.workers)) return state

  for (const key of state.seen) {
    if (key.startsWith(`${event.run_id}|`)) state.seen.delete(key)
  }
  const runFlow = { ...state.runFlow }
  delete runFlow[event.run_id]

  return {
    ...state,
    runFlow,
    workers: {
      ...state.workers,
      [flow]: {
        ...state.workers[flow],
        lastRun: {
          status: asString(event.status),
          steps: asNumber(event.steps),
          finished_at: asString(event.finished_at),
        },
        // The frame is the summary, flattened -- so it joins the window
        // like one, at the front, and the oldest falls off the back.
        ...windowed(
          [event as unknown as RunSummary, ...state.workers[flow].runs],
          state.workers[flow].tracked,
        ),
      },
    },
  }
}

export function reduce(state: StageState, event: PoieoEvent): StageState {
  if (event.type === "run_summary") return applySummary(state, event)

  const flow = flowFor(state, event)
  if (flow === null || !(flow in state.workers)) return state

  const key = keyOf(event)
  if (state.seen.has(key)) return state

  const patch = patchFor(event, state.workers[flow])
  if (patch === null) return state

  // The dedup set is carried, not copied: it is bookkeeping, and copying it on
  // every frame would cost more than the rendering it guards.
  state.seen.add(key)

  const runFlow =
    event.type === "run_started" ? { ...state.runFlow, [event.run_id]: flow } : state.runFlow

  if (Object.keys(patch).length === 0 && runFlow === state.runFlow) return state

  return {
    ...state,
    runFlow,
    workers: { ...state.workers, [flow]: { ...state.workers[flow], ...patch } },
  }
}

/** The window and its sum, which are never allowed to disagree. */
function windowed(runs: RunSummary[], tracked: boolean): Pick<Worker, "runs" | "recent"> {
  const kept = runs.slice(0, WINDOW)
  return { runs: kept, recent: rollup(kept, tracked) }
}

/** Seed a flow's window from the run index, which the reducer cannot see. */
export function setRuns(state: StageState, flow: string, runs: RunSummary[]): StageState {
  if (!(flow in state.workers)) return state
  const worker = state.workers[flow]
  return {
    ...state,
    workers: { ...state.workers, [flow]: { ...worker, ...windowed(runs, worker.tracked) } },
  }
}

export function replay(state: StageState, events: PoieoEvent[]): StageState {
  return events.reduce(reduce, state)
}
