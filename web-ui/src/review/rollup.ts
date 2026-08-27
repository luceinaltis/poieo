/**
 * What a night amounts to, in one line.
 *
 * Three outcomes, and the middle one is the point: a run that looked and found
 * nothing to do succeeded. Counting it as a failure makes a quiet night read
 * as a broken one, which is the fastest way to teach someone to ignore this
 * screen.
 */

import type { RunSummary } from "../types"

export type Outcome = "succeeded" | "failed" | "nothing"

export interface Rollup {
  runs: number
  succeeded: number
  failed: number
  nothingToDo: number
  insertions: number
  deletions: number
}

export const NOTHING: Rollup = Object.freeze({
  runs: 0,
  succeeded: 0,
  failed: 0,
  nothingToDo: 0,
  insertions: 0,
  deletions: 0,
})

/**
 * `tracked` says whether this task keeps a private copy at all.
 *
 * Without one there is nothing to change against, so a run that carries no
 * change simply ran. Calling that "found nothing to do" would tell someone
 * whose task only moves text that it wasted every night it ever worked.
 */
export function outcomeOf(run: RunSummary, tracked = true): Outcome {
  if (run.status !== "completed") return "failed"
  if (!tracked) return "succeeded"
  return run.change ? "succeeded" : "nothing"
}

export function fold(into: Rollup, run: RunSummary, tracked = true): Rollup {
  const outcome = outcomeOf(run, tracked)
  // A failed run's change is parked rather than waiting, so its lines are
  // not part of what there is to accept.
  const change = outcome === "succeeded" ? run.change : undefined

  return {
    runs: into.runs + 1,
    succeeded: into.succeeded + (outcome === "succeeded" ? 1 : 0),
    failed: into.failed + (outcome === "failed" ? 1 : 0),
    nothingToDo: into.nothingToDo + (outcome === "nothing" ? 1 : 0),
    insertions: into.insertions + (change?.insertions ?? 0),
    deletions: into.deletions + (change?.deletions ?? 0),
  }
}

export function rollup(runs: RunSummary[], tracked = true): Rollup {
  return runs.reduce((into, run) => fold(into, run, tracked), NOTHING)
}
