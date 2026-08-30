import { afterEach, beforeEach, expect, test, vi } from "vitest"

import { runs } from "./index"
import { DAY, HOUR } from "./span"
import { initialStage, reduce, setRuns } from "../../state/stage"
import type { StageState } from "../../state/stage"
import type { RunSummary, TaskRow } from "../../types"

// Handed over in an order that is not the order they are drawn in, so the
// test below can tell a sorted board from an accidentally sorted one.
const FLOWS: TaskRow[] = [
  {
    name: "revision",
    project: "board",
    graph: "draft-review",
    trigger: "loop",
    status: "waiting",
    current_run_id: null,
    last_run: null,
    pending: 0,
    into: "poieo/revision",
    asking: null,
    then: [],
    shape: { entry: "", nodes: [] },
  },
  {
    name: "chores",
    project: "board",
    graph: "agent-task",
    trigger: "every 15m",
    status: "waiting",
    current_run_id: null,
    last_run: null,
    pending: 0,
    // Keeps a private copy, so a run carrying no change is one that looked and
    // found nothing rather than one that simply ran.
    into: "poieo/chores",
    asking: null,
    then: [],
    shape: { entry: "", nodes: [] },
  },
]

const CHORES = FLOWS[1]

const run = (id: string, ago: number, extra: Partial<RunSummary> = {}): RunSummary => ({
  run_id: id,
  task: "chores",
  project: "board",
  graph: "agent-task",
  status: "completed",
  started_at: new Date(Date.now() - ago - 60_000).toISOString(),
  finished_at: new Date(Date.now() - ago).toISOString(),
  steps: 3,
  iteration: 1,
  trigger: "loop",
  usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
  error: null,
  said: "",
  ...extra,
})

const CHANGE = { base: "a", head: "b", files: ["x.py"], insertions: 4, deletions: 2, message: "" }

const board = (runs: RunSummary[]): StageState =>
  setRuns(initialStage(FLOWS), "board/chores", runs)

let el: HTMLDivElement

beforeEach(() => {
  el = document.createElement("div")
  document.body.append(el)
})

afterEach(() => {
  el.remove()
})

test("mount/update/destroy leaves the element empty", () => {
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(board([run("a", HOUR)]))
  expect(el.childElementCount).toBeGreaterThan(0)

  handle.destroy()
  expect(el.childElementCount).toBe(0)
})

test("one lane per task, under its own name and trigger", () => {
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(board([]))

  expect(el.querySelectorAll(".runs-lane")).toHaveLength(2)
  const lane = el.querySelector('[data-task="board/chores"]')!
  expect(lane.querySelector(".runs-name")!.textContent).toBe("chores")
  expect(lane.querySelector(".runs-trigger")!.textContent).toBe("every 15m")

  handle.destroy()
})

test("lanes are in the same order whichever order the tasks arrived in", () => {
  // A board that reorders itself while it is being read is what the graph view
  // went to some trouble to stop doing, and a shared clock makes it worse:
  // comparing two lanes means finding them in the same place twice.
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(board([]))
  const names = () =>
    [...el.querySelectorAll(".runs-name")].map((node) => node.textContent)
  expect(names()).toEqual(["chores", "revision"])

  handle.update(reduce(board([]), {
    run_id: "rr",
    type: "run_started",
    data: { task: "revision", project: "board" },
  }))
  expect(names()).toEqual(["chores", "revision"])

  handle.destroy()
})

test("a run that changed something is a different mark from a quiet one", () => {
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(board([run("quiet", HOUR), run("did", 2 * HOUR, { change: CHANGE })]))

  const marks = [...el.querySelectorAll('[data-task="board/chores"] .runs-mark')]
  expect(marks.map((mark) => mark.getAttribute("data-outcome")).sort()).toEqual([
    "nothing",
    "succeeded",
  ])

  handle.destroy()
})

test("a failed run keeps its own mark", () => {
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(board([run("bad", HOUR, { status: "failed", error: "boom" })]))

  expect(
    el.querySelector('[data-task="board/chores"] .runs-mark')!.getAttribute("data-outcome"),
  ).toBe("failed")

  handle.destroy()
})

test("runs land left to right in the order they happened", () => {
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(board([run("new", HOUR), run("old", 6 * HOUR)]))

  const at = [...el.querySelectorAll<HTMLElement>('[data-task="board/chores"] .runs-mark')].map(
    (mark) => Number.parseFloat(mark.style.left),
  )
  expect(at).toHaveLength(2)
  expect(at[0]).toBeLessThan(at[1])
  // ...and inside the clock, not off either end of it.
  for (const one of at) {
    expect(one).toBeGreaterThanOrEqual(0)
    expect(one).toBeLessThanOrEqual(100)
  }

  handle.destroy()
})

test("a task whose last run was days ago still shows it", () => {
  // The window is a day by default. Left at that, a board that stopped on
  // Tuesday would open blank -- which reads exactly like a board that has
  // never run, and the difference is the whole reason to come here.
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(board([run("ancient", 3 * DAY)]))

  expect(el.querySelectorAll('[data-task="board/chores"] .runs-mark')).toHaveLength(1)
  // Four: the run is three days back, and the window reaches a day past it
  // so the board's last living day is on screen rather than on the edge.
  expect(el.querySelector(".runs-caption")!.textContent).toContain("4 days")
  const mark = el.querySelector<HTMLElement>('[data-task="board/chores"] .runs-mark')!
  const at = Number.parseFloat(mark.style.left)
  expect(at).toBeGreaterThan(5)
  expect(at).toBeLessThan(50)

  handle.destroy()
})

test("runs the clock opened after are counted rather than dropped", () => {
  // The lane has nowhere to draw them, but leaving them out entirely makes a
  // task with months behind it read as one that started this morning.
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(board([run("today", HOUR), run("tuesday", 3 * DAY), run("monday", 4 * DAY)]))

  const lane = el.querySelector('[data-task="board/chores"]')!
  expect(lane.querySelectorAll(".runs-mark")).toHaveLength(1)
  expect(lane.querySelector(".runs-earlier")!.textContent).toContain("+2")
  // ...and in the spoken summary too: a sighted reader gets the badge, so a
  // screen reader gets the same sentence rather than a shorter one.
  expect(lane.querySelector(".runs-track")!.getAttribute("aria-label")).toContain(
    "2 more before that",
  )

  handle.destroy()
})

test("a running task is marked at now; a waiting one is not", () => {
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  const running = reduce(board([run("a", HOUR)]), {
    run_id: "rr",
    type: "run_started",
    data: { task: "chores", project: "board" },
  })
  handle.update(running)

  expect(el.querySelector('[data-task="board/chores"] .runs-live')).not.toBeNull()
  expect(el.querySelector('[data-task="board/revision"] .runs-live')).toBeNull()
  expect(el.querySelector('[data-task="board/chores"] .runs-last')!.textContent).toBe(
    "running now",
  )

  handle.destroy()
})

test("the hour rules are drawn once for the board, not once per lane", () => {
  // They are what makes two lanes comparable; a copy inside each lane would be
  // free to drift from the one above it.
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(board([run("a", HOUR)]))

  expect(el.querySelectorAll(".runs-rules")).toHaveLength(1)
  expect(el.querySelectorAll(".runs-edge")).toHaveLength(1)
  // Each rule knows whether its label is a date, so a midnight's rule can be
  // drawn heavier -- on a three-day board the days read as rooms.
  for (const rule of el.querySelectorAll<HTMLElement>(".runs-rule")) {
    expect(["time", "date"]).toContain(rule.dataset.kind)
  }
  // One rule under every label, or the grid stops meaning what the axis says.
  const rules = el.querySelectorAll<HTMLElement>(".runs-rule")
  const labels = el.querySelectorAll<HTMLElement>(".runs-tick")
  expect(rules.length).toBe(labels.length)
  expect(rules.length).toBeGreaterThanOrEqual(2)
  expect([...rules].map((one) => one.style.left)).toEqual(
    [...labels].map((one) => one.style.left),
  )

  handle.destroy()
})

test("clicking a lane selects that task", () => {
  const picked: string[] = []
  const handle = runs.mount(el, { onSelectTask: (task) => picked.push(task) })
  handle.update(board([]))

  el.querySelector<HTMLElement>('[data-task="board/revision"] .runs-head')!.click()
  expect(picked).toEqual(["board/revision"])

  handle.destroy()
})

test("a frame for one task does not rebuild the other lane", () => {
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  const stage = board([run("a", HOUR)])
  handle.update(stage)
  const mark = el.querySelector('[data-task="board/chores"] .runs-mark')

  handle.update(
    reduce(stage, {
      run_id: "rr",
      type: "run_started",
      data: { task: "revision", project: "board" },
    }),
  )

  expect(el.querySelector('[data-task="board/chores"] .runs-mark')).toBe(mark)
  expect(el.querySelector('[data-task="board/revision"]')!.getAttribute("data-status")).toBe(
    "running",
  )

  handle.destroy()
})

test("a task that leaves the board takes its lane with it", () => {
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(board([]))
  expect(el.querySelectorAll(".runs-lane")).toHaveLength(2)

  handle.update(initialStage([CHORES]))
  expect(el.querySelectorAll(".runs-lane")).toHaveLength(1)
  expect(el.querySelector('[data-task="board/revision"]')).toBeNull()

  handle.destroy()
})

test("the clock is given up when the view is", () => {
  // It ticks once a minute to walk the window forward; left running it would
  // keep painting a detached lane for as long as the tab is open.
  vi.useFakeTimers()
  try {
    const before = vi.getTimerCount()
    const handle = runs.mount(el, { onSelectTask: vi.fn() })
    handle.update(board([run("a", HOUR)]))
    expect(vi.getTimerCount()).toBe(before + 1)

    handle.destroy()
    expect(vi.getTimerCount()).toBe(before)
  } finally {
    vi.useRealTimers()
  }
})

test("the lane says in words what it draws in marks, for a reader who cannot see it", () => {
  // The counts are deliberately not on screen -- the marks are the counts, and
  // printing them beside the picture would say one thing twice. Without a
  // picture there is nothing else, so the label is where they go.
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(
    board([
      run("a", HOUR, { change: CHANGE }),
      run("b", 2 * HOUR),
      run("c", 3 * HOUR, { status: "failed" }),
    ]),
  )

  const track = el.querySelector('[data-task="board/chores"] .runs-track')!
  expect(track.getAttribute("aria-label")).toBe(
    "3 runs in the last day, 1 changed something, 1 failed",
  )
  expect(
    el.querySelector('[data-task="board/revision"] .runs-track')!.getAttribute("aria-label"),
  ).toBe("nothing ran in the last day")
  handle.update(board([run("only", HOUR)]))
  expect(
    el.querySelector('[data-task="board/chores"] .runs-track')!.getAttribute("aria-label"),
  ).toBe("1 run in the last day")

  handle.destroy()
})

test("a lane too narrow for its runs folds neighbours instead of fusing them", () => {
  // jsdom cannot measure, so the width is stubbed: fifty 15-minute runs in a
  // lane 120 pixels wide is a phone, and drawn one per run they overlap into
  // a solid bar that reads as one long run.
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  const crowded = Array.from({ length: 50 }, (_, n) => run(`r${n}`, HOUR + n * 15 * 60_000))
  const track = () => el.querySelector<HTMLElement>('[data-task="board/chores"] .runs-track')!

  handle.update(board(crowded))
  const before = track().querySelectorAll(".runs-mark").length
  expect(before).toBe(50)

  Object.defineProperty(track(), "clientWidth", { value: 120, configurable: true })
  // Repainted by the next frame that touches this task.
  handle.update(
    reduce(board(crowded), {
      run_id: "rr",
      type: "run_started",
      data: { task: "chores", project: "board" },
    }),
  )
  const after = track().querySelectorAll(".runs-mark").length
  expect(after).toBeLessThan(before)
  expect(after).toBeGreaterThan(0)

  handle.destroy()
})

test("a task with nothing to change says its runs ran, not that they changed something", () => {
  // `outcomeOf` calls every completed run of an untracked task `succeeded` --
  // there is nothing to compare against, so a run that ran is the whole of
  // what there is to say. Read as "changed something" the lane told a reader
  // who cannot see it that a task had changed a thing it cannot change. The
  // graph view has guarded this since it was written; this one had not.
  const untracked = FLOWS.map((flow) =>
    flow.name === "chores" ? { ...flow, into: null } : flow,
  )
  const handle = runs.mount(el, { onSelectTask: vi.fn() })
  handle.update(setRuns(initialStage(untracked), "board/chores", [run("a", HOUR), run("b", 2 * HOUR)]))

  const label = el.querySelector('[data-task="board/chores"] .runs-track')!.getAttribute("aria-label")
  expect(label).toBe("2 runs in the last day")

  handle.destroy()
})
