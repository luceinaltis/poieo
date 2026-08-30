/**
 * The clock every lane shares, and where a run sits on it.
 *
 * This is the part of the runs view capable of being wrong -- how wide the
 * window is, which runs fall inside it, where each one lands -- so it is pure
 * and tested on its own, the way `skins/wiring.ts` is for the graph. Drawing a
 * tick at a fraction of a lane is arrangement, and jsdom has no geometry to
 * check that against anyway.
 */

import { scaleTime } from "d3-scale"

import { outcomeOf } from "../../review/rollup"
import type { Outcome } from "../../review/rollup"
import type { RunSummary } from "../../types"

export const HOUR = 60 * 60 * 1000
export const DAY = 24 * HOUR

export interface Span {
  from: number
  to: number
}

/**
 * A day, unless the board has been quiet longer than that.
 *
 * A fixed day is what makes two lanes comparable, and it is the span a person
 * opening this page in the morning is asking about. But a board whose last run
 * was Tuesday would then open on an empty day, which reads exactly like a
 * board that has never run -- so the window stretches back to a day *past*
 * the newest run. Not merely to it: that put the run on the left edge with
 * everything before it folded into a badge, and every stopped lane read as
 * the same blank grid. A day past it, the board's last living day is on
 * screen, and the silence since is the width of the rest -- which is the
 * difference between "stopped Tuesday" and "never ran", drawn rather than
 * inferred. It never shrinks below a day: a single run five minutes ago must
 * not be drawn as five minutes of history.
 */
export function windowOf(newest: number | null, now: number): Span {
  if (newest === null || newest >= now - DAY) return { from: now - DAY, to: now }
  return { from: newest - DAY, to: now }
}

export interface Mark {
  runId: string
  outcome: Outcome
  at: number
  /** Where it falls across the window, 0 at the left edge and 1 at now. */
  x: number
}

export interface Lane {
  marks: Mark[]
  /** Runs the window opened after. Counted, because the lane cannot show them. */
  earlier: number
}

/**
 * One task's runs, placed.
 *
 * `tracked` decides what a run carrying no change means, and it is not this
 * module's opinion -- `outcomeOf` owns that, and the tally under a card on the
 * graph view reads the same function. Two views disagreeing about whether a
 * night was quiet or busy is the failure worth spending an import to avoid.
 */
export function lane(runs: RunSummary[], tracked: boolean, span: Span): Lane {
  const width = Math.max(1, span.to - span.from)
  const marks: Mark[] = []
  let earlier = 0

  for (const run of runs) {
    const at = Date.parse(run.finished_at)
    // A run with no readable finish is dropped rather than placed: parsed to
    // NaN it would sit at the left edge, which is a lie about when it ran.
    if (Number.isNaN(at)) continue
    if (at < span.from) {
      earlier += 1
      continue
    }
    marks.push({
      runId: run.run_id,
      outcome: outcomeOf(run, tracked),
      at,
      x: Math.min(1, (at - span.from) / width),
    })
  }

  // The index hands runs back newest first; a lane is read the other way.
  marks.sort((one, other) => one.at - other.at)
  return { marks, earlier }
}

export interface Tick {
  at: number
  x: number
  /**
   * How this one label is worded: a midnight names its day, everything else
   * names its hour. Per tick, not per axis -- on a four-day window the hours
   * repeat, and the dated midnights between them are what tell the fourth
   * 06:00 from the first.
   */
  kind: "time" | "date"
}

/** Past this many the axis is texture rather than a scale. */
const MOST = 8

/**
 * The labelled hours, picked by d3 rather than counted here -- so they land
 * on 06:00 and 12:00, which a reader already knows where to find, and stay on
 * the round local hour across a daylight-saving change, which a ladder of
 * fixed millisecond steps walked straight through. Choosing round times on a
 * civil calendar is the most re-solved problem in charting; this is the one
 * piece of the view where a library knows things this file would get wrong.
 *
 * `most` is how many the caller has room for. A phone gets four labels rather
 * than eight overlapping ones -- and the answer has to come from the caller,
 * because how wide a lane is is not a fact about the clock. Asking for more
 * than the axis can carry is refused rather than honoured: past eight, hour
 * labels are texture rather than a scale at any width. The labels' wording
 * stays ours: d3's formats are twelve-hour and English, and the axis is
 * neither.
 */
export function ticks(span: Span, most: number = MOST): Tick[] {
  const width = Math.max(1, span.to - span.from)
  const room = Math.max(1, Math.min(most, MOST))
  const scale = scaleTime().domain([span.from, span.to])
  // d3's count is a hint, not a bound: a width that lands between two of its
  // intervals comes back with eleven labels for a cap of eight. Asking for
  // fewer walks it down its own ladder of round intervals, which keeps the
  // labels on hours a reader knows -- thinning the list here would not. One
  // step at a time, because the ladder is coarse: halving jumped from nine
  // labels to four when eight was the ask and five was on offer.
  let dates = scale.ticks(room)
  for (let ask = room - 1; dates.length > room && ask >= 1; ask -= 1) {
    dates = scale.ticks(ask)
  }
  return dates.map((day) => ({
    at: +day,
    x: (+day - span.from) / width,
    kind: day.getHours() === 0 && day.getMinutes() === 0 ? "date" : "time",
  }))
}

/** One mark standing for several runs the lane had no room to draw apart. */
export interface Fold {
  /** Where it is drawn: its oldest member's place. Anchoring here is what
   * keeps two folds a full gap apart on screen; the position of the newest
   * member is off by less than a mark's width, and the tooltip has it. */
  x: number
  /** The stretch it stands for. `from` is the oldest member, `at` the newest. */
  from: number
  at: number
  /** The worst of its members: failed > succeeded > nothing. A failure in a
   * crowd of quiet runs is the one thing folding must never smooth over. */
  outcome: Outcome
  count: number
}

const SEVERITY: Record<Outcome, number> = { nothing: 0, succeeded: 1, failed: 2 }

/**
 * Marks too close to tell apart, folded into one.
 *
 * A 15-minute task is fifty marks, and on a phone the lane gives them two
 * pixels each: drawn one per run they fuse into a solid bar, which reads as
 * one long run rather than many short ones. `gap` is the width of a drawn
 * mark as a fraction of the lane, and it comes from the caller because how
 * wide a lane is is not a fact about the clock. Zero folds nothing without a
 * special case: marks arrive sorted, so no spacing is ever under zero -- and
 * the caller that could not measure its lane must not guess a width.
 */
export function crowd(marks: Mark[], gap: number): Fold[] {
  const folds: Fold[] = []
  for (const mark of marks) {
    const open = folds[folds.length - 1]
    // Measured against the fold's anchor, never its newest member. Chained on
    // a moving edge, marks arriving every few minutes fold without bound and
    // a whole night collapses into one tick -- the opposite failure to the
    // fused bar this exists to prevent. Anchored, a fold is at most one gap
    // wide and a dense night is a fence of them.
    if (open !== undefined && mark.x - open.x < gap) {
      open.at = mark.at
      open.count += 1
      if (SEVERITY[mark.outcome] > SEVERITY[open.outcome]) open.outcome = mark.outcome
      continue
    }
    folds.push({ x: mark.x, from: mark.at, at: mark.at, outcome: mark.outcome, count: 1 })
  }
  return folds
}
