/**
 * The wire shapes the daemon's observation API produces.
 *
 * Kept deliberately close to the Python side: these mirror `poieo.store.Event`,
 * `RunResult.summary()` and the rows `/api/tasks` builds. Nothing here is
 * interpreted -- that is the reducer's job.
 */

export interface Usage {
  input_tokens: number
  output_tokens: number
  cache_read_tokens: number
  cache_write_tokens: number
}

export interface Change {
  base: string
  head: string
  files: string[]
  insertions: number
  deletions: number
  /** The run's own one-line account of what it did. */
  message: string
}

export interface RunSummary {
  run_id: string
  task: string | null
  graph: string
  status: string
  started_at: string
  finished_at: string
  steps: number
  iteration: number
  /** What actually fired this run -- a schedule, "run now", or "after <task>". */
  trigger: string
  usage: Usage
  error: string | null
  /** The run's own account of itself, whether or not it changed a file. */
  said: string
  /** Absent when the run altered nothing -- which is not the same as null. */
  change?: Change
}

/**
 * One arrow, wherever it is drawn.
 *
 * A router's branches and a task's `then:` are the same `Branch` one level
 * apart, so the wire gives them the same shape and a view learns one arrow
 * rather than two. `to` is null when the branch deliberately ends there, and
 * `label` falls back to the condition when the author named no word for it --
 * the same fallback the run record uses.
 */
export interface Arrow {
  to: string | null
  label: string
}

/** One node of a graph, as much of it as a drawing needs. */
export interface NodeShape {
  id: string
  type: string
  next: string | null
  default: string | null
  branches: Arrow[]
  /** The model id this node would call; null for a router, which calls none. */
  model: string | null
  /** Absent -- not zeroed -- when the editor never placed this node. */
  ui?: { x: number; y: number }
}

/** A graph's wiring. No prompts: they are long, and this rides every paint. */
export interface GraphShape {
  entry: string
  nodes: NodeShape[]
}

/**
 * Whose board this is.
 *
 * Two daemons on two ports serve pages that are otherwise identical -- same
 * title, same skin, same empty state -- so the listing carries the name of
 * the project it came from.
 */
export interface ProjectRow {
  name: string
  /** The folder the project is, which is what tells two same-named ones apart. */
  root: string
}

/** What `GET /api/tasks` answers: the board, and whose board it is. */
export interface Listing {
  project: ProjectRow | null
  tasks: TaskRow[]
}

export interface TaskRow {
  name: string
  graph: string
  trigger: string
  status: string
  current_run_id: string | null
  last_run: RunSummary | null
  /** How many changes are waiting to be looked at. */
  pending: number
  /** What accepting them would add to; null when the task keeps no copy. */
  into: string | null
  /** Which task works next, and on what condition. Empty for most tasks. */
  then: Arrow[]
  /** What this task walks on the way there. */
  shape: GraphShape
}

/**
 * One line of a run's JSONL, and one SSE frame -- they are the same bytes.
 *
 * `node_id` is absent rather than null on run-level events (`Event.as_dict`
 * drops None). `run_summary` is the one frame that breaks the envelope: the
 * BroadcastStore publishes it flat, so its summary fields sit beside `type`
 * instead of under `data`, and it carries no `at`.
 */
export interface PoieoEvent {
  run_id: string
  type: string
  at?: string
  node_id?: string
  data?: Record<string, any>
  [flatSummaryField: string]: unknown
}


export interface DiffFile {
  path: string
  status: string
  insertions: number
  deletions: number
}

export interface DiffReport {
  run_id: string
  base?: string
  head?: string
  files?: DiffFile[]
  patch?: string
  truncated?: boolean
  /** Present and null when the run altered nothing. */
  change?: null
}
