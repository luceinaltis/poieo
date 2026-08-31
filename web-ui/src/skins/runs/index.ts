/**
 * The runs view: what the board has been doing, and when.
 *
 * The graph answers what a project does and where it is right now. It cannot
 * answer the question a person actually opens this page with in the morning
 * -- *what happened overnight* -- because it does not put time on the screen
 * at all.
 *
 * So: one clock across the top, one lane per task, one mark per run, and every
 * lane read against the same clock. That last part is the whole reason this
 * view exists. A tally tells you three tasks failed; only a shared clock tells
 * you they all failed at 04:12, which is a different problem with a different
 * cause. The hour rules run down through every lane so that lining them up
 * costs a reader nothing.
 *
 * A mark carries its run's outcome in silhouette, not only in colour: a quiet
 * run is a low tick, a run that did its work is a post, and a failure runs the
 * full height of the lane. A night of a healthy task is a picket fence with a
 * few tall posts in it, and that shape is legible before any of the words are
 * -- and to a reader for whom amber and red are one colour, which they are for
 * a great many people.
 *
 * "Did its work" and not "changed something", because the low tick is only
 * available to a task that keeps a private copy: without one there is nothing
 * to have changed, every completed run is a post, and there is no quiet night
 * for one of these to be told apart from. `summarise` says the same thing in
 * words, which is where getting it wrong was visible.
 */

import { changedTasks } from "../changed"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import type { StageState, TaskState } from "../../state/stage"
import { DAY, crowd, lane, ticks, windowOf } from "./span"
import type { Mark, Span } from "./span"
import "./runs.css"

/**
 * How often the clock is allowed to move.
 *
 * The window ends at now, so every mark drifts left continuously -- redrawing
 * every lane on every SSE frame to chase that is exactly what `changedTasks`
 * exists to prevent. A minute of drift is seven hundredths of a percent of a
 * day, which is narrower than a mark.
 */
const TICK = 60_000

interface Row {
  root: HTMLElement
  name: HTMLElement
  trigger: HTMLElement
  track: HTMLElement
  last: HTMLElement
}

function element(tag: string, className: string, parent: Element): HTMLElement {
  const node = document.createElement(tag)
  node.className = className
  parent.append(node)
  return node
}

/**
 * A clock, on a page that is nothing but clock.
 *
 * `shortTime` is what the rest of the board uses and it hands back seconds and
 * an AM/PM marker -- right where it is used, beside one run in the drawer. Here
 * every label is a time and they are read against each other, so seconds are
 * three characters of noise and a twelve-hour clock puts 03:00 twice on an axis
 * that runs for a day.
 */
function clock(at: number): string {
  return new Date(at).toLocaleTimeString(undefined, {
    hour: "2-digit",
    minute: "2-digit",
    hourCycle: "h23",
  })
}

/** How wide the window came out, in the words the header uses. */
function describeSpan(span: Span): string {
  const days = Math.round((span.to - span.from) / DAY)
  return days <= 1 ? "the last day" : `the last ${days} days`
}

/**
 * The one thing a lane cannot draw: when this task last looked.
 *
 * What it *did* is already on screen as marks, so counting the same runs again
 * in words would be a second way of saying what the picture says. When it last
 * looked is what tells "quiet, and there was nothing to do" apart from
 * "stopped" -- and no mark can carry it, because a task that stopped has bare
 * lane to the right of its final mark and so does a task still working.
 */
function describeLast(flowState: TaskState): string {
  if (flowState.status === "running") return "running now"
  // Said before the clock, because it changes what the bare lane to the right
  // of the last mark means: not "quiet tonight" but "it will not look again".
  if (flowState.status === "paused") return "paused"
  const at = Date.parse(flowState.runs[0]?.finished_at ?? flowState.lastRun?.finished_at ?? "")
  return Number.isNaN(at) ? "nothing has run yet" : `last looked ${clock(at)}`
}

/** The newest finish anywhere on the board, which is how far back it reaches. */
function newestFinish(tasks: Record<string, TaskState>): number | null {
  let newest: number | null = null
  for (const flowState of Object.values(tasks)) {
    for (const run of flowState.runs) {
      const at = Date.parse(run.finished_at)
      if (!Number.isNaN(at) && (newest === null || at > newest)) newest = at
    }
  }
  return newest
}

/** A bare div with a label on it is skipped; a group with one is read out. */
function labelled(node: HTMLElement): HTMLElement {
  node.role = "group"
  return node
}

function buildRow(task: string, callbacks: SkinCallbacks): Row {
  const root = document.createElement("div")
  root.className = "runs-lane"
  root.dataset.task = task

  const head = element("button", "runs-head", root)
  ;(head as HTMLButtonElement).type = "button"
  head.addEventListener("click", () => callbacks.onSelectTask(task))

  return {
    root,
    name: element("span", "runs-name", head),
    trigger: element("span", "runs-trigger", head),
    track: labelled(element("div", "runs-track", root)),
    last: element("span", "runs-last", root),
  }
}

/**
 * The lane, for a reader who cannot see it.
 *
 * The counts are deliberately absent from the screen -- the marks already are
 * the counts, and writing them out beside the picture would be a second way of
 * saying one thing. There is no picture here, so this is the only way of
 * saying it.
 */
function summarise(marks: Mark[], earlier: number, span: Span, tracked: boolean): string {
  const before = earlier > 0 ? `, ${earlier} more before that` : ""
  if (marks.length === 0) return `nothing ran in ${describeSpan(span)}${before}`
  const changed = marks.filter((mark) => mark.outcome === "succeeded").length
  const quiet = marks.filter((mark) => mark.outcome === "nothing").length
  const failed = marks.filter((mark) => mark.outcome === "failed").length
  const parts = [`${marks.length} run${marks.length === 1 ? "" : "s"} in ${describeSpan(span)}`]
  // One clause per silhouette, so this says what the lane draws.
  //
  // The `tracked` guard is the point of the pair. A task keeping no private
  // copy has nothing to compare against, so `outcomeOf` calls every completed
  // run of one `succeeded` -- read out as "changed something" that told a
  // reader who cannot see the lane that the task had changed a thing it cannot
  // change. But dropping the clause and stopping there would have left an
  // untracked lane reading exactly like a tracked one whose runs all found
  // nothing, which are two different pictures. So the quiet runs are counted
  // too, and only a tracked task can have any.
  if (changed > 0 && tracked) parts.push(`${changed} changed something`)
  if (quiet > 0) parts.push(`${quiet} found nothing to do`)
  if (failed > 0) parts.push(`${failed} failed`)
  return parts.join(", ") + before
}

function paint(row: Row, flowState: TaskState, span: Span): void {
  row.name.textContent = flowState.name
  row.trigger.textContent = flowState.trigger
  row.last.textContent = describeLast(flowState)
  row.root.dataset.status = flowState.status

  const drawn = lane(flowState.runs, flowState.tracked, span)
  const marks: HTMLElement[] = []

  // What the window opened after. A number rather than a mark, because the
  // lane has nowhere to put it -- and left out entirely, a task with months
  // of history would read as one that started this morning.
  if (drawn.earlier > 0) {
    const before = document.createElement("span")
    before.className = "runs-earlier"
    before.textContent = `‹ +${drawn.earlier}`
    before.title = `${drawn.earlier} more before this window`
    marks.push(before)
  }

  // How much lane a drawn mark takes, as the fold threshold. Measured rather
  // than assumed, because this is the one number that differs between a phone
  // and a desktop -- and it is why a 15-minute task is a picket fence on both
  // instead of a solid bar on one. Unmeasurable (jsdom, a lane not yet laid
  // out) comes back 0, and a zero gap folds nothing.
  const width = row.track.clientWidth
  const folds = crowd(drawn.marks, width > 0 ? 5 / width : 0)

  for (const fold of folds) {
    const tick = document.createElement("span")
    tick.className = "runs-mark"
    tick.dataset.outcome = fold.outcome
    tick.style.left = `${fold.x * 100}%`
    tick.title =
      fold.count === 1
        ? `${clock(fold.at)} · ${fold.outcome}`
        : `${fold.count} runs · ${clock(fold.from)}–${clock(fold.at)} · worst: ${fold.outcome}`
    marks.push(tick)
  }

  // A run in flight has no finish to be placed by, so it is drawn at now --
  // the right edge, and the only mark that moves on its own.
  if (flowState.status === "running") {
    const live = document.createElement("span")
    live.className = "runs-live"
    live.title = "running now"
    marks.push(live)
  }

  row.track.ariaLabel = summarise(drawn.marks, drawn.earlier, span, flowState.tracked)
  row.track.replaceChildren(...marks)
}

export const runs: Skin = {
  id: "runs",
  label: "Runs",
  // A place, not a rendering: the rail carries it, the picker does not.
  standalone: true,

  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle {
    const root = element("div", "runs", el)
    const axis = element("div", "runs-axis", root)
    const caption = element("span", "runs-caption", axis)
    const scale = element("div", "runs-scale", axis)
    const body = element("div", "runs-body", root)
    // Behind every lane rather than inside each one: the hour rules are what
    // make two lanes comparable, so there is one set of them for the board.
    const rules = element("div", "runs-rules", body)

    const rows = new Map<string, Row>()
    const painted = new Map<string, TaskState>()
    let last: StageState | null = null
    let span: Span = windowOf(null, Date.now())

    /** How many hour labels fit, at roughly the width one of them takes. */
    function room(): number {
      return Math.max(3, Math.floor(scale.clientWidth / 88))
    }

    function drawAxis(): void {
      caption.textContent = describeSpan(span)
      const labels: HTMLElement[] = []
      const lines: HTMLElement[] = []
      for (const mark of ticks(span, room())) {
        const at = new Date(mark.at)
        const label = document.createElement("span")
        label.className = "runs-tick"
        label.style.left = `${mark.x * 100}%`
        label.textContent =
          mark.kind === "date"
            ? // `undefined` follows the reader's locale, which put `9월 1일`
              // in the middle of an English ruler -- the same thing the clock
              // did before it was pinned, one formatter over. The date sits
              // between `18:00` and `03:00`, so it reads as those do.
              at.toLocaleDateString("en-GB", { month: "short", day: "numeric" })
            : clock(mark.at)
        labels.push(label)

        const rule = document.createElement("span")
        rule.className = "runs-rule"
        rule.dataset.kind = mark.kind
        rule.style.left = `${mark.x * 100}%`
        lines.push(rule)
      }
      scale.replaceChildren(...labels)

      // The present, down the right edge of every lane, so a mark against it
      // reads as still going rather than as merely the last one.
      const edge = document.createElement("span")
      edge.className = "runs-edge"
      rules.replaceChildren(...lines, edge)
    }

    function repaint(stage: StageState, tasks: Iterable<string>): void {
      for (const task of tasks) {
        const row = rows.get(task)
        const flowState = stage.tasks[task]
        if (row !== undefined && flowState !== undefined) paint(row, flowState, span)
      }
    }

    const walking = setInterval(() => {
      if (last === null) return
      span = windowOf(newestFinish(last.tasks), Date.now())
      drawAxis()
      repaint(last, rows.keys())
    }, TICK)

    // Everything here is sized by the window as well as by the data: the axis
    // for how many labels fit, the lanes for how close is too close to draw
    // apart. So a window that changes size relabels one and refolds the other
    // -- without the second, opening the drawer leaves the marks folded for a
    // lane that no longer exists, until the next frame happens to repaint
    // them. Guarded: jsdom has no observer, and a view that cannot watch
    // simply keeps what it was given.
    const watching =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            drawAxis()
            if (last !== null) repaint(last, rows.keys())
          })
    watching?.observe(scale)

    drawAxis()

    return {
      update(stage: StageState) {
        // Only ever *widened* here. Recomputing the window on every frame
        // would move it by however long the frame took to arrive, which makes
        // every mark's position differ from the one before it -- and then a
        // frame about one task repaints all of them, which is the exact cost
        // `changedTasks` exists to avoid. Walking the window forward is the
        // clock's job, once a minute. This is only the case the clock cannot
        // wait for: a run older than the window the view opened with, which
        // has nowhere to be drawn until the window reaches back to it.
        const want = windowOf(newestFinish(stage.tasks), Date.now())
        const moved = want.from < span.from
        if (moved) {
          span = want
          drawAxis()
        }

        const fresh = changedTasks(stage.tasks, painted)
        let set = false
        for (const [task] of fresh) {
          if (rows.has(task)) continue
          const row = buildRow(task, callbacks)
          rows.set(task, row)
          body.append(row.root)
          set = true
        }
        for (const [task, row] of rows) {
          if (task in stage.tasks) continue
          row.root.remove()
          rows.delete(task)
          set = true
        }

        // Alphabetical, and re-sorted only when the set changes: a board that
        // reorders itself while it is being read is what the graph view went to
        // some trouble to stop doing.
        if (set) {
          const order = [...rows.entries()].sort(([one], [other]) =>
            (stage.tasks[one]?.name ?? one).localeCompare(stage.tasks[other]?.name ?? other),
          )
          for (const [, row] of order) body.append(row.root)
        }

        repaint(stage, moved ? rows.keys() : fresh.map(([task]) => task))
        last = stage
      },

      destroy() {
        clearInterval(walking)
        watching?.disconnect()
        rows.clear()
        painted.clear()
        root.remove()
      },
    }
  },
}
