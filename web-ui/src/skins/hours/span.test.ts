import { expect, test } from "vitest"

import { DAY, HOUR, crowd, lane, ticks, windowOf } from "./span"
import type { RunSummary } from "../../types"

const NOW = Date.parse("2026-08-22T18:00:00Z")

const run = (id: string, finished: number, extra: Partial<RunSummary> = {}): RunSummary => ({
  run_id: id,
  task: "chores",
  project: "board",
  graph: "agent-task",
  status: "completed",
  started_at: new Date(finished - 60_000).toISOString(),
  finished_at: new Date(finished).toISOString(),
  steps: 3,
  iteration: 1,
  trigger: "loop",
  usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
  error: null,
  said: "",
  ...extra,
})

const changed = (id: string, finished: number): RunSummary =>
  run(id, finished, {
    change: { base: "a", head: "b", files: ["x.py"], insertions: 3, deletions: 1, message: "" },
  })

test("the clock is the last day when anything ran inside it", () => {
  const span = windowOf(NOW - 20 * 60 * 1000, NOW)
  expect(span.to).toBe(NOW)
  expect(span.from).toBe(NOW - DAY)
})

test("the clock stretches back to reach the newest run when everything is stale", () => {
  // A board whose last run was three days ago must not open on an empty day.
  // Nothing else tells a reader the difference between "quiet" and "stopped
  // three days ago", which is the one thing they came here to find out.
  const stale = NOW - 3 * DAY
  const span = windowOf(stale, NOW)
  expect(span.from).toBe(stale)
})

test("the clock is a day wide when nothing has ever run", () => {
  expect(windowOf(null, NOW)).toEqual({ from: NOW - DAY, to: NOW })
})

test("a run sits where its finish falls across the clock", () => {
  const span = { from: NOW - DAY, to: NOW }
  const drawn = lane([run("a", NOW - 12 * HOUR)], true, span)
  expect(drawn.marks).toHaveLength(1)
  expect(drawn.marks[0].x).toBeCloseTo(0.5, 5)
})

test("runs older than the clock are counted, not drawn off the left edge", () => {
  const span = { from: NOW - DAY, to: NOW }
  const drawn = lane([run("new", NOW - HOUR), run("old", NOW - 2 * DAY)], true, span)
  expect(drawn.marks.map((mark) => mark.runId)).toEqual(["new"])
  expect(drawn.earlier).toBe(1)
})

test("a changeless run reads as quiet only when the task keeps a copy", () => {
  // Same bytes, two readings: a task with no private copy has nothing to
  // change against, so its run simply ran. Drawing those as "nothing to do"
  // would tell someone whose task only moves text that it wasted every night.
  const span = { from: NOW - DAY, to: NOW }
  const runs = [run("a", NOW - HOUR)]
  expect(lane(runs, true, span).marks[0].outcome).toBe("nothing")
  expect(lane(runs, false, span).marks[0].outcome).toBe("succeeded")
})

test("a run that changed something, and one that failed, keep their own marks", () => {
  const span = { from: NOW - DAY, to: NOW }
  const runs = [changed("a", NOW - HOUR), run("b", NOW - 2 * HOUR, { status: "failed" })]
  const outcomes = lane(runs, true, span).marks.map((mark) => mark.outcome)
  expect(outcomes).toContain("succeeded")
  expect(outcomes).toContain("failed")
})

test("a run whose timestamp the daemon did not write is skipped, not placed at zero", () => {
  const span = { from: NOW - DAY, to: NOW }
  const drawn = lane([run("bad", NOW, { finished_at: "" })], true, span)
  expect(drawn.marks).toEqual([])
  expect(drawn.earlier).toBe(0)
})

test("marks come out oldest first, whichever way the run index handed them over", () => {
  // The lanes are read left to right; the index hands runs back newest first.
  const span = { from: NOW - DAY, to: NOW }
  const drawn = lane([run("c", NOW - HOUR), run("a", NOW - 5 * HOUR)], true, span)
  expect(drawn.marks.map((mark) => mark.runId)).toEqual(["a", "c"])
})

test("the labelled hours land on the hour and inside the clock", () => {
  // Opened at seventeen past, so a label counted from the left edge rather
  // than from midnight would read 17:17 and every reader would have to do
  // arithmetic to find six o'clock.
  const from = NOW - DAY + 17 * 60 * 1000
  const marks = ticks({ from, to: NOW })
  expect(marks.length).toBeGreaterThanOrEqual(3)
  for (const mark of marks) {
    expect(new Date(mark.at).getMinutes()).toBe(0)
    // Where a label sits is where its own time falls -- a label at the right
    // hour in the wrong place is worse than no label.
    expect(mark.x).toBeCloseTo((mark.at - from) / (NOW - from), 5)
    expect(mark.x).toBeGreaterThanOrEqual(0)
    expect(mark.x).toBeLessThanOrEqual(1)
  }
})

test("a wider clock counts by more than an hour rather than growing a label per hour", () => {
  const week = ticks({ from: NOW - 7 * DAY, to: NOW })
  expect(week.length).toBeLessThanOrEqual(8)
  // ...and says so in days, because a bare clock time repeats seven times.
  expect(week.every((mark) => mark.kind === "date")).toBe(true)
})

test("the cap holds at awkward widths, not only the round ones", () => {
  // d3's tick count is a hint, not a bound: a window ~1.3 days wide -- a
  // board that went quiet overnight -- lands between two of its intervals
  // and comes back with eleven labels for a cap of eight.
  for (const days of [1, 1.35, 2, 3, 4.5, 5.66, 7]) {
    const marks = ticks({ from: NOW - days * DAY, to: NOW })
    expect(marks.length, `${days} days`).toBeLessThanOrEqual(8)
    expect(marks.length, `${days} days`).toBeGreaterThanOrEqual(2)
  }
})

test("a clock time that would repeat across days is anchored by dated midnights", () => {
  // A four-day window labels sub-day hours, so 06:00 appears four times. The
  // midnight between each pair wears the date instead, which is what tells
  // the fourth 06:00 from the first. One kind per axis could not say this.
  const spread = ticks({ from: NOW - 4 * DAY, to: NOW })
  expect(spread.some((mark) => mark.kind === "date")).toBe(true)
  for (const mark of spread) {
    const at = new Date(mark.at)
    const midnight = at.getHours() === 0 && at.getMinutes() === 0
    expect(mark.kind, at.toISOString()).toBe(midnight ? "date" : "time")
  }
})

test("a caller with room for fewer labels counts by more", () => {
  // A phone's lane is a third of a laptop's, and eight labels there overlap
  // into one unreadable word. The window opens off the round hour on purpose:
  // opened exactly on one, d3's coarse ladder can offer the same count to
  // both callers, and then there is nothing here to see.
  const span = { from: NOW - DAY + 17 * 60 * 1000, to: NOW }
  const roomy = ticks(span)
  const cramped = ticks(span, 4)
  expect(cramped.length).toBeLessThan(roomy.length)
  expect(cramped.length).toBeGreaterThanOrEqual(2)
  for (const mark of cramped) expect(new Date(mark.at).getMinutes()).toBe(0)
})

test("asking for more labels than the axis can carry does not widen it", () => {
  const span = { from: NOW - DAY, to: NOW }
  expect(ticks(span, 99)).toEqual(ticks(span))
})

test("marks that would overlap are folded into one, carrying the worst outcome", () => {
  // A 15-minute task on a phone puts fifty marks in a lane a hundred pixels
  // wide; drawn one per run they fuse into a solid bar, which reads as one
  // long run rather than many short ones.
  const span = { from: NOW - DAY, to: NOW }
  const drawn = lane(
    [run("a", NOW - HOUR), run("b", NOW - HOUR - 60_000), changed("c", NOW - HOUR - 120_000)],
    true,
    span,
  )
  const folded = crowd(drawn.marks, 0.01)
  expect(folded).toHaveLength(1)
  expect(folded[0].outcome).toBe("succeeded")
  expect(folded[0].count).toBe(3)
})

test("a failure is never averaged away by the quiet runs around it", () => {
  const span = { from: NOW - DAY, to: NOW }
  const drawn = lane(
    [
      run("a", NOW - HOUR),
      run("b", NOW - HOUR - 60_000, { status: "failed" }),
      run("c", NOW - HOUR - 120_000),
    ],
    true,
    span,
  )
  const folded = crowd(drawn.marks, 0.01)
  expect(folded).toHaveLength(1)
  expect(folded[0].outcome).toBe("failed")
})

test("marks with room between them are left alone", () => {
  const span = { from: NOW - DAY, to: NOW }
  const drawn = lane([run("a", NOW - HOUR), run("b", NOW - 6 * HOUR)], true, span)
  const folded = crowd(drawn.marks, 0.01)
  expect(folded).toHaveLength(2)
  expect(folded.every((one) => one.count === 1)).toBe(true)
})

test("a fold spans its members' time, oldest to newest", () => {
  const span = { from: NOW - DAY, to: NOW }
  const drawn = lane(
    [run("new", NOW - HOUR), run("old", NOW - HOUR - 300_000)],
    true,
    span,
  )
  const folded = crowd(drawn.marks, 0.05)
  expect(folded).toHaveLength(1)
  expect(folded[0].from).toBe(NOW - HOUR - 300_000)
  expect(folded[0].at).toBe(NOW - HOUR)
})

test("a zero gap folds nothing", () => {
  // The caller could not measure its lane -- jsdom, or a lane not yet laid
  // out -- and guessing a width would fold marks that have room.
  const span = { from: NOW - DAY, to: NOW }
  const drawn = lane(
    [run("a", NOW - HOUR), run("b", NOW - HOUR - 1000)],
    true,
    span,
  )
  expect(crowd(drawn.marks, 0)).toHaveLength(2)
})

test("folding is bounded: a dense night is a fence of folds, never one tick", () => {
  // Fifty 15-minute runs on a phone. Folded against a moving edge they chain
  // into a single mark, which reads as one run -- the opposite failure to the
  // fused bar folding exists to prevent.
  const span = { from: NOW - DAY, to: NOW }
  const runs = Array.from({ length: 50 }, (_, n) => run(`r${n}`, NOW - HOUR - n * 15 * 60_000))
  const gap = 0.03
  const folds = crowd(lane(runs, true, span).marks, gap)
  expect(folds.length).toBeGreaterThan(5)
  for (let n = 1; n < folds.length; n += 1) {
    expect(folds[n].x - folds[n - 1].x).toBeGreaterThanOrEqual(gap)
  }
  // Nothing dropped: the folds still account for every run.
  expect(folds.reduce((sum, fold) => sum + fold.count, 0)).toBe(50)
})
