import { expect, test } from "vitest"

import { NOTHING, fold, outcomeOf, rollup } from "./rollup"
import type { RunSummary } from "../types"

const USAGE = {
  input_tokens: 0,
  output_tokens: 0,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
}

function run(over: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: "r",
    task: "chores",
    graph: "agent-task",
    status: "completed",
    started_at: "2026-08-22T02:00:00+00:00",
    finished_at: "2026-08-22T02:00:04+00:00",
    steps: 1,
    iteration: 1,
    trigger: "cron 0 2 * * *",
    usage: USAGE,
    error: null,
    said: "did the thing",
    ...over,
  }
}

function change(over = {}) {
  return {
    base: "aaa",
    head: "bbb",
    files: ["one.py"],
    insertions: 42,
    deletions: 11,
    message: "tidied the exports",
    ...over,
  }
}

test("an empty night rolls up to nothing", () => {
  expect(rollup([])).toEqual(NOTHING)
})

test("counts and sums across a night", () => {
  const summary = rollup([
    run({ run_id: "a", change: change() }),
    run({ run_id: "b", change: change({ insertions: 3, deletions: 1, files: ["x", "y"] }) }),
  ])

  expect(summary.runs).toBe(2)
  expect(summary.succeeded).toBe(2)
  expect(summary.insertions).toBe(45)
  expect(summary.deletions).toBe(12)
})

test("a run that changed nothing succeeded, it did not fail", () => {
  const summary = rollup([run({ run_id: "quiet" })])

  // It ran, it looked, there was nothing to do. Counting that as failed would
  // make a quiet night look broken.
  expect(summary.runs).toBe(1)
  expect(summary.nothingToDo).toBe(1)
  expect(summary.failed).toBe(0)
  expect(summary.insertions).toBe(0)
})

test("a failed run is counted as failed", () => {
  const summary = rollup([run({ status: "failed", error: "NodeError: boom" })])

  expect(summary.failed).toBe(1)
  expect(summary.succeeded).toBe(0)
  expect(summary.nothingToDo).toBe(0)
})

test("a failed run that got partway still contributes no lines", () => {
  // Its change is parked, not on the branch, so it is not part of what is waiting.
  const summary = rollup([run({ status: "failed", change: change() })])

  expect(summary.failed).toBe(1)
  expect(summary.insertions).toBe(0)
  expect(summary.deletions).toBe(0)
})

test("outcomeOf names the three outcomes", () => {
  expect(outcomeOf(run({ change: change() }))).toBe("succeeded")
  expect(outcomeOf(run())).toBe("nothing")
  expect(outcomeOf(run({ status: "failed" }))).toBe("failed")
  expect(outcomeOf(run({ status: "aborted" }))).toBe("failed")
})

test("fold adds one run at a time, matching rollup", () => {
  const runs = [run({ change: change() }), run(), run({ status: "failed" })]
  // Not `runs.reduce(fold, ...)`: reduce would hand the array index in as
  // `tracked`, which is falsy only for the first run.
  expect(runs.reduce((into, one) => fold(into, one), NOTHING)).toEqual(rollup(runs))
})

test("NOTHING is not mutated by folding", () => {
  fold(NOTHING, run({ change: change() }))
  expect(NOTHING.runs).toBe(0)
})


test("a task that keeps no private copy has no 'nothing to do' at all", () => {
  // Its runs never carry a change because there is nothing to change against.
  // Reporting every one of them as "found nothing to do" makes a task that
  // only moves text look like it wasted the night, every night.
  const summary = rollup([run({ run_id: "a" }), run({ run_id: "b" })], false)

  expect(summary.runs).toBe(2)
  expect(summary.nothingToDo).toBe(0)
  expect(summary.succeeded).toBe(2)
})

test("an untracked task still counts its failures", () => {
  const summary = rollup([run({ status: "failed" }), run()], false)

  expect(summary.failed).toBe(1)
  expect(summary.succeeded).toBe(1)
})

test("outcomeOf needs to know whether changes were possible", () => {
  expect(outcomeOf(run(), false)).toBe("succeeded")
  expect(outcomeOf(run(), true)).toBe("nothing")
})
