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
import type { Arrow, TaskRow, GraphShape, PoieoEvent, Question, RunSummary } from "../types"

export interface ToolCall {
  name: string
  /** What the call acted on -- the path, the pattern, the command line. */
  subject: string
  result: string
  failed: boolean
  at: string
}

export interface LastRun {
  status: string
  steps: number
  finished_at: string
}

export interface TaskState {
  /** What to call it on screen. The key it is filed under is the identity. */
  name: string
  project: string
  /**
   * The four states a view has to draw apart.
   *
   * `paused` is one of them because a task somebody stopped and a task between
   * two runs are the same picture otherwise, and they are opposite answers to
   * the only question a board is really asked. A task held back by its budget
   * lands here too: a different reason, the same answer.
   */
  status: "waiting" | "running" | "paused" | "error"
  /** Whether a hold is on, even while the run it was pressed during finishes. */
  held: boolean
  /**
   * Whether the card file lets this task run at all.
   *
   * Beside `status` rather than a fifth value of it: it is stopped either way,
   * and the band on the card says so either way. What differs is the word, and
   * what a reader has to do about it.
   */
  enabled: boolean
  /**
   * Why the card file and this task disagree, or "" while they do not.
   *
   * Structure rather than state: it changes only when a file does. The empty
   * string and not null, so a view asks it the same way it asks the other
   * lines on a card whether they have anything to say.
   */
  stale: string
  /** Changes waiting for accept/discard, kept live as summaries arrive. */
  pending: number
  /** Changed summaries already reflected in `pending`, bounded to the live window. */
  countedChangeRuns: ReadonlySet<string>
  /** The newest unanswered confirm question, if this task has one. */
  asking: Question | null
  currentNode: string | null
  step: number
  turn: number
  lastText: string
  lastThinking: string
  recentToolCalls: ToolCall[]
  lastRun: LastRun | null
  /**
   * What this task has done lately, for the card line.
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
  /** Whether this task keeps a private copy, and so can have changes at all. */
  tracked: boolean
  /**
   * The wiring: which task works next, and what this one walks on the way.
   *
   * Structure rather than state -- it changes only when a file does, while
   * everything above it moves every few seconds. A view that draws both keeps
   * them apart for exactly that reason: the layout is settled once, and only
   * the highlight moves after that.
   */
  then: Arrow[]
  shape: GraphShape
  /** How this task is scheduled, as the daemon describes it. Structure too. */
  trigger: string
}

/**
 * How far back the tally reaches, in finished runs.
 *
 * The same window the work list below a task is fetched with, and it has to
 * stay the same: the card's number and that list are the same runs, or a
 * reader has no way to tell which of the two is lying.
 */
export const WINDOW = 50

export interface StageState {
  tasks: Record<string, TaskState>
  /** Learned from run_started: no other event says which task it belongs to. */
  runTask: Record<string, string>
  /** Dedup keys for the history/live overlap. Retired when a run ends. */
  seen: Set<string>
}

const TOOL_CALL_CAP = 8

const asString = (value: unknown, fallback = ""): string =>
  typeof value === "string" ? value : fallback

const asNumber = (value: unknown, fallback = 0): number =>
  typeof value === "number" ? value : fallback

/**
 * The one argument worth showing beside a tool's name.
 *
 * Arguments reach the board clipped to a JSON string, so they are parsed here
 * rather than upstream. Tools differ in what they act on -- a path, a glob, a
 * command line -- and the board has room for one of them, so the keys below
 * are tried in the order a reader would look for them. Anything unrecognised
 * falls back to the values themselves, which beats showing nothing.
 */
export function subjectOf(raw: unknown): string {
  let args: unknown = raw
  if (typeof raw === "string") {
    try {
      args = JSON.parse(raw)
    } catch {
      return raw
    }
  }
  if (!args || typeof args !== "object") return ""
  const named = args as Record<string, unknown>
  for (const key of ["path", "pattern", "command", "query", "dir"]) {
    if (typeof named[key] === "string") return named[key] as string
  }
  return Object.values(named)
    .filter((one): one is string => typeof one === "string")
    .join(" ")
}

function createEmptyTaskState(): TaskState {
  return {
    status: "waiting",
    held: false,
    enabled: true,
    stale: "",
    pending: 0,
    countedChangeRuns: new Set(),
    asking: null,
    name: "",
    project: "",
    currentNode: null,
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

/**
 * A task's identity on the board: which project, and which task in it.
 *
 * A name alone stopped being enough when one daemon could run several
 * projects -- every project has a `chores`. The daemon refuses to run two
 * projects answering to one name, which is what makes this pair unique.
 * Built, never split: whoever needs the halves has them already.
 */
export function keyOfTask(project: string, task: string): string {
  return `${project}/${task}`
}

/**
 * The board, narrowed to one project.
 *
 * A daemon runs as many projects as it was given, and looking at all of them
 * at once is looking at a wall: the boxes are unrelated, no arrow crosses
 * between them, and the only thing they share is a machine. One at a time is
 * the whole board, not a filtered one.
 */
export function onlyProject(stage: StageState, project: string | null): StageState {
  if (project === null) return stage
  const tasks: Record<string, TaskState> = {}
  for (const [key, task] of Object.entries(stage.tasks)) {
    if (task.project === project) tasks[key] = task
  }
  return { ...stage, tasks }
}

/**
 * The daemon's word for a runner, as the four states a view draws.
 *
 * The daemon has one more word than the board needs -- `over budget`, which is
 * a task that will run again once its spend ages out. It draws as paused
 * because that is the true answer to what a reader is asking: not right now.
 * Anything unrecognised is `waiting`, so a state added to the daemon draws as
 * the quiet one rather than breaking an old build.
 */
function drawnStatus(row: TaskRow): TaskState["status"] {
  if (row.status === "running") return "running"
  if (row.status === "paused" || row.status === "over budget") return "paused"
  return "waiting"
}

export function initialStage(rows: TaskRow[]): StageState {
  const tasks: Record<string, TaskState> = {}
  for (const row of rows) {
    tasks[keyOfTask(row.project, row.name)] = {
      ...createEmptyTaskState(),
      name: row.name,
      project: row.project,
      tracked: row.into !== null,
      then: row.then,
      shape: row.shape,
      trigger: row.trigger,
      status: drawnStatus(row),
      held: row.holding,
      enabled: row.enabled,
      stale: row.stale ?? "",
      pending: row.pending,
      countedChangeRuns: new Set(
        row.last_run?.status === "completed" && row.last_run.change
          ? [row.last_run.run_id]
          : [],
      ),
      asking: row.asking,
      lastRun: row.last_run
        ? {
            status: row.last_run.status,
            steps: row.last_run.steps,
            finished_at: row.last_run.finished_at,
          }
        : null,
    }
  }
  return { tasks, runTask: {}, seen: new Set() }
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

function taskKeyForEvent(state: StageState, event: PoieoEvent): string | null {
  if (event.type === "run_started") {
    // Ad-hoc `poieo run` executions have no task and do not belong on a board
    // of daemon tasks.
    const task = event.data?.task
    if (typeof task !== "string") return null
    return keyOfTask(asString(event.data?.project, ""), task)
  }
  return state.runTask[event.run_id] ?? null
}

/** null = an event this build does not know; {} = known, but nothing to show. */
function patchFor(event: PoieoEvent, taskState: TaskState): Partial<TaskState> | null {
  const data = event.data ?? {}

  switch (event.type) {
    case "run_started":
      return {
        status: "running",
        currentNode: null,
        step: 0,
        turn: 0,
        lastText: "",
        lastThinking: "",
        recentToolCalls: [],
      }

    case "node_started":
      return {
        currentNode: event.node_id ?? null,
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
            subject: subjectOf(data.arguments),
            result: asString(data.result),
            failed: data.error === true,
            at: event.at ?? "",
          },
          ...taskState.recentToolCalls,
        ].slice(0, TOOL_CALL_CAP),
      }

    case "node_finished":
      // Deliberately nothing: the next node_started replaces currentNode, and
      // clearing it here would blink the board empty between every step.
      return {}

    case "run_finished":
      // Back to whichever kind of not-running this task is. A pause pressed
      // mid-run is honoured the moment the run leaves, which is exactly what
      // the daemon does with it -- and what this used to undo.
      return { status: taskState.held ? "paused" : "waiting", currentNode: null }

    case "run_asking":
      return {
        status: taskState.held ? "paused" : "waiting",
        currentNode: null,
        asking: {
          run_id: event.run_id,
          question: asString(data.question),
          choices: Array.isArray(data.choices)
            ? data.choices.filter((choice): choice is string => typeof choice === "string")
            : [],
        },
      }

    case "run_failed":
    case "run_aborted":
      return { status: "error", currentNode: null }

    default:
      return null // forward compat: a new backend event must not break an old build
  }
}

/**
 * `run_summary` is the odd frame out: BroadcastStore publishes it flat, so its
 * fields sit beside `type` rather than under `data`, and it names its own task.
 * It is also the last word on a run, so it retires that run's bookkeeping.
 */
function applySummary(state: StageState, event: PoieoEvent): StageState {
  const name = asString(event.task, "")
  const task = name && keyOfTask(asString(event.project, ""), name)
  if (!task || !(task in state.tasks)) return state

  for (const key of state.seen) {
    if (key.startsWith(`${event.run_id}|`)) state.seen.delete(key)
  }
  const anotherRunOwnsTask = Object.entries(state.runTask).some(
    ([runId, owner]) => runId !== event.run_id && owner === task,
  )
  const runTask = { ...state.runTask }
  delete runTask[event.run_id]

  const current = state.tasks[task]
  const summary = event as unknown as RunSummary
  const alreadyKnown = current.runs.some((run) => run.run_id === event.run_id)
  const runs = alreadyKnown
    ? current.runs.map((run) => (run.run_id === event.run_id ? summary : run))
    : [summary, ...current.runs]
  const latest = runs[0]
  const summaryOwnsTerminalState = latest?.run_id === event.run_id && !anotherRunOwnsTask
  const completedChange = event.status === "completed" && event.change !== undefined
  const newlyCountedChange = completedChange && !current.countedChangeRuns.has(event.run_id)
  const countedChangeRuns = newlyCountedChange
    ? new Set([...current.countedChangeRuns, event.run_id].slice(-WINDOW))
    : current.countedChangeRuns
  const asking =
    current.asking?.run_id === event.run_id && event.status !== "asking"
      ? null
      : current.asking
  const status: TaskState["status"] =
    event.status === "completed" || event.status === "asking"
      ? current.held
        ? "paused"
        : "waiting"
      : event.status === "failed" || event.status === "aborted"
        ? "error"
        : current.status

  return {
    ...state,
    runTask,
    tasks: {
      ...state.tasks,
      [task]: {
        ...current,
        lastRun: latest
          ? {
              status: latest.status,
              steps: latest.steps,
              finished_at: latest.finished_at,
            }
          : current.lastRun,
        pending: current.pending + (newlyCountedChange ? 1 : 0),
        countedChangeRuns,
        asking,
        ...(summaryOwnsTerminalState ? { status, currentNode: null } : {}),
        // The frame is the summary, flattened -- so it joins the window
        // like one, at the front, and the oldest falls off the back.
        ...windowed(runs, current.tracked),
      },
    },
  }
}

export function reduce(state: StageState, event: PoieoEvent): StageState {
  if (event.type === "run_summary") return applySummary(state, event)

  const task = taskKeyForEvent(state, event)
  if (task === null || !(task in state.tasks)) return state

  const key = keyOf(event)
  if (state.seen.has(key)) return state

  const patch = patchFor(event, state.tasks[task])
  if (patch === null) return state

  // The dedup set is carried, not copied: it is bookkeeping, and copying it on
  // every frame would cost more than the rendering it guards.
  state.seen.add(key)

  let runTask = state.runTask
  if (event.type === "run_started") {
    runTask = { ...state.runTask, [event.run_id]: task }
  } else if (
    ["run_finished", "run_asking", "run_failed", "run_aborted"].includes(event.type) &&
    event.run_id in state.runTask
  ) {
    runTask = { ...state.runTask }
    delete runTask[event.run_id]
  }

  if (Object.keys(patch).length === 0 && runTask === state.runTask) return state

  return {
    ...state,
    runTask,
    tasks: { ...state.tasks, [task]: { ...state.tasks[task], ...patch } },
  }
}

/** The window and its sum, which are never allowed to disagree. */
function windowed(runs: RunSummary[], tracked: boolean): Pick<TaskState, "runs" | "recent"> {
  const kept = runs.slice(0, WINDOW)
  return { runs: kept, recent: rollup(kept, tracked) }
}

/** Seed a task's window from the run index, which the reducer cannot see. */
export function setRuns(state: StageState, task: string, runs: RunSummary[]): StageState {
  if (!(task in state.tasks)) return state
  const taskState = state.tasks[task]
  return {
    ...state,
    tasks: { ...state.tasks, [task]: { ...taskState, ...windowed(runs, taskState.tracked) } },
  }
}

export function replay(state: StageState, events: PoieoEvent[]): StageState {
  return events.reduce(reduce, state)
}
