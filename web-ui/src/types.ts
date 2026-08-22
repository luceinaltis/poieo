/**
 * The wire shapes the daemon's observation API produces.
 *
 * Kept deliberately close to the Python side: these mirror `poieo.store.Event`,
 * `RunResult.summary()` and the rows `/api/flows` builds. Nothing here is
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
  flow: string | null
  graph: string
  status: string
  started_at: string
  finished_at: string
  steps: number
  iteration: number
  usage: Usage
  error: string | null
  /** Absent when the run altered nothing -- which is not the same as null. */
  change?: Change
}

export interface FlowRow {
  name: string
  graph: string
  trigger: string
  status: string
  current_run_id: string | null
  last_run: RunSummary | null
  /** How many pieces of work are waiting to be looked at. */
  pending: number
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
