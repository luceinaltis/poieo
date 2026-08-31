import { afterEach, beforeEach, expect, test, vi } from "vitest"

import { basic } from "./index"
import { AGENT_RUN } from "../../state/fixtures"
import { initialStage, reduce, replay, setRuns } from "../../state/stage"
import type { TaskRow } from "../../types"
import { BOX } from "../wiring"

const FLOWS: TaskRow[] = [
  {
    name: "chores",
    project: "board",
    graph: "agent-task",
    trigger: "loop",
    status: "waiting",
    current_run_id: null,
    last_run: null,
    pending: 0,
    into: null,
    asking: null,
    then: [],
    shape: {
      entry: "work",
      nodes: [{ id: "work", type: "agent", next: null, default: null, branches: [], model: null, tools: [] }],
    },
  },
  {
    name: "revision",
    project: "board",
    graph: "draft-review",
    trigger: "loop",
    status: "waiting",
    current_run_id: null,
    last_run: null,
    pending: 0,
    into: null,
    asking: null,
    then: [],
    shape: { entry: "", nodes: [] },
  },
]

let el: HTMLDivElement

beforeEach(() => {
  el = document.createElement("div")
  document.body.append(el)
})

afterEach(() => {
  el.remove()
})

test("a frame for one task does not rebuild the other tasks' boxes", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  // A task of two steps, so there are nodes inside to survive at all: one
  // step draws no graph, the border being that step already.
  const stage = replay(initialStage([build(), FLOWS[1]]), AGENT_RUN)
  handle.update(stage)

  // chores is drawn with its graph's nodes inside it.
  const node = el.querySelector('[data-task="board/chores"] .basic-node')
  expect(node).not.toBeNull()

  // An event for the other task arrives; chores was not touched, and the
  // reducer keeps its object identity, so its DOM must survive untouched.
  const next = reduce(stage, {
    run_id: "rr",
    type: "run_started",
    data: { task: "revision", project: "board" },
  })
  handle.update(next)

  expect(el.querySelector('[data-task="board/chores"] .basic-node')).toBe(node)
  // The task the frame was for did repaint.
  expect(el.querySelector('[data-task="board/revision"]')!.getAttribute("data-status")).toBe(
    "running",
  )
  handle.destroy()
})

const WIRED: TaskRow[] = [
  {
    ...FLOWS[0],
    then: [
      { to: "revision", label: "changed" },
      { to: null, label: "quiet" },
    ],
  },
  FLOWS[1],
]

test("nothing opens itself, however busy it is", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(replay(initialStage(FLOWS), AGENT_RUN.slice(0, 4)))

  // A running task used to open itself, and shut again when it stopped, so a
  // board that runs every minute rearranged itself all day. The `now` line
  // says what that was for; the size changes only when a person asks.
  expect(el.querySelector('[data-task="board/chores"]')!.getAttribute("data-open")).toBe("false")
  expect(el.querySelector('[data-task="board/revision"]')!.getAttribute("data-open")).toBe("false")
  handle.destroy()
})

test("opening a task by hand outlasts the frames that follow", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  const stage = initialStage(FLOWS)
  handle.update(stage)

  el.querySelector<HTMLElement>('[data-task="board/revision"] .basic-toggle')!.click()
  expect(el.querySelector('[data-task="board/revision"]')!.getAttribute("data-open")).toBe("true")

  // A frame for that task must not undo the reader's own choice.
  handle.update(reduce(stage, { run_id: "r", type: "run_started", data: { task: "revision", project: "board" } }))
  expect(el.querySelector('[data-task="board/revision"]')!.getAttribute("data-open")).toBe("true")
  handle.destroy()
})

test("a handoff is drawn as an arrow carrying the word on it", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(WIRED))

  // One arrow, not two: the branch that deliberately stops has nothing to
  // point at, and an arrow to nowhere would be a line the reader must ignore.
  expect(el.querySelectorAll(".basic-wire")).toHaveLength(1)
  expect(el.querySelector(".basic-word")!.textContent).toBe("changed")
  handle.destroy()
})

test("a handoff says which way it goes", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(WIRED))

  // The whole board rests on one rule -- an arrow that crosses a border ends
  // one run and starts another -- and a bare line is not an arrow. Without a
  // head, "chores hands to review" reads exactly like the reverse.
  const heads = el.querySelectorAll(".basic-tip")
  expect(heads).toHaveLength(1)
  // Pointing at the task being handed to, not away from it.
  expect(heads[0].getAttribute("d")).toContain(String(BOX.width + BOX.gapX))
  handle.destroy()
})

test("the word on an arrow sits on the line it names", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(WIRED))

  // Floated above the line it belonged to the box underneath it instead, and
  // on the top row it had the board's own edge to collide with.
  const [, , y] = el.querySelector(".basic-wire")!.getAttribute("d")!.split(/[ ,]/)
  expect(el.querySelector(".basic-word")!.getAttribute("y")).toBe(y)
  handle.destroy()
})

test("a task to the right of its sender is not laid on top of it", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(WIRED))

  const from = el.querySelector<HTMLElement>('[data-task="board/chores"]')!
  const to = el.querySelector<HTMLElement>('[data-task="board/revision"]')!
  expect(from.style.left).toBe("0px")
  expect(parseInt(to.style.left, 10)).toBeGreaterThan(0)
  expect(to.style.top).toBe(from.style.top)
  handle.destroy()
})

test("a task that found nothing to do says so in one word, not a number", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  // Tracked: a task that keeps a private copy is the one that can find
  // nothing to do. Without one there is nothing to change against, and a run
  // that ran is all there is to say.
  const quiet = setRuns(
    initialStage([{ ...FLOWS[0], into: "main" }, FLOWS[1]]),
    "board/chores",
    // Eight runs that all looked and found nothing: a healthy night, and the
    // line the board used to print for it was "8 runs · 8 found nothing to do".
    Array.from({ length: 8 }, (_, i) => ({
      run_id: `r${i}`,
      task: "chores",
      project: "board",
      graph: "agent-task",
      status: "completed",
      started_at: "2026-08-27T02:00:00+00:00",
      finished_at: "2026-08-27T02:00:04+00:00",
      steps: 1,
      iteration: 1,
      trigger: "cron",
      usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
      error: null,
      said: "did the thing",
    })),
  )
  handle.update(quiet)

  const said = el.querySelector('[data-task="board/chores"] .basic-tally')!.textContent!
  expect(said).toContain("quiet")
  expect(said).not.toContain("8")
  handle.destroy()
})


/** A task whose graph is a triage line: classify, route, then draft. */
function triage(models: (string | null)[]): TaskRow {
  const [classify, route, draft] = models
  return {
    ...FLOWS[0],
    name: "chores",
    project: "board",
    shape: {
      entry: "classify",
      nodes: [
        { id: "classify", type: "agent", next: "route", default: null, branches: [], model: classify, tools: [] },
        {
          id: "route",
          type: "router",
          next: null,
          default: "draft",
          branches: [],
          model: route,
          tools: [],
        },
        { id: "draft", type: "agent", next: null, default: null, branches: [], model: draft, tools: [] },
      ],
    },
  }
}

const when = () => el.querySelector('[data-task="board/chores"] .basic-when')!.textContent
const pill = (id: string) =>
  el.querySelector<HTMLElement>(`[data-task="board/chores"] [data-node="${id}"]`)!

test("a task that resolves to one model says so once, beside the trigger", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([triage(["qwen3:8b", null, "qwen3:8b"])]))

  // Said once, on the line that is legible with the border shut: ten tasks
  // collapsed is the glance, and "what is running my board" is answered there.
  expect(when()).toBe("loop · qwen3:8b")
  // ...and not repeated on every node, which would be noise for one answer.
  expect(pill("classify").querySelector(".basic-node-model")).toBeNull()
  handle.destroy()
})

test("a task on two models counts them, and each node carries its own", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([triage(["llama3.2:3b", null, "claude-opus-5"])]))

  // The header cannot answer it, so it stops trying and says how many;
  // opening the border is what says which is which.
  expect(when()).toBe("loop · 2 models")
  expect(pill("classify").querySelector(".basic-node-model")!.textContent).toBe("llama3.2:3b")
  expect(pill("draft").querySelector(".basic-node-model")!.textContent).toBe("claude-opus-5")
  handle.destroy()
})

test("a router carries no model, because it calls none", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([triage(["llama3.2:3b", null, "claude-opus-5"])]))

  // The gap is information: it is why branching is free.
  expect(pill("route").querySelector(".basic-node-model")).toBeNull()
  handle.destroy()
})

/** Two agent steps on one model, differing only in what they may touch. */
function build(): TaskRow {
  return {
    ...FLOWS[0],
    name: "chores",
    project: "board",
    shape: {
      entry: "work",
      nodes: [
        { id: "work", type: "agent", next: "say", default: null, branches: [], model: "qwen3:8b", tools: ["files", "shell"] },
        { id: "say", type: "agent", next: null, default: null, branches: [], model: "qwen3:8b", tools: [] },
      ],
    },
  }
}

test("a step that can reach the folder says so; one that only answers does not", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([build()]))

  // Same type, same model, same box: what they may touch is the whole
  // difference between a step that rewrites the project and one that talks
  // about it, and it is the last thing a reader should have to open a file
  // to find out. Said in words a reader who has read nothing else can read --
  // "hands" is the word the design documents use, and a screen is not one.
  const hands = pill("work").querySelector(".basic-node-hands")!
  expect(hands.textContent).toBe("edits files")
  expect(hands.getAttribute("title")).toBe("files, shell")
  expect(pill("say").querySelector(".basic-node-hands")).toBeNull()
  handle.destroy()
})

/** One step, which is what the board's own `new task` writes. */
function oneStep(): TaskRow {
  return {
    ...FLOWS[0],
    shape: {
      entry: "work",
      nodes: [
        {
          id: "work",
          type: "agent",
          next: null,
          default: null,
          branches: [],
          model: "qwen3:8b",
          tools: ["files", "shell"],
        },
      ],
    },
  }
}

test("a task draws its steps without being opened first", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([build()]))

  // What a task walks is structure: it changes when a file does, never
  // between one frame and the next. So it can be drawn on a shut border
  // without the board moving under the reader -- and being able to read the
  // work at a glance is the whole reason the board is a canvas rather than a
  // list.
  expect(el.querySelector('[data-task="board/chores"]')!.getAttribute("data-open")).toBe("false")
  expect(el.querySelectorAll('[data-task="board/chores"] .basic-node')).toHaveLength(2)
  handle.destroy()
})

test("a task of one step draws that step, rather than an empty row", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([oneStep()]))

  // It was drawn as nothing while the steps were hidden until asked for: one
  // pill named `work` was noise the reader had opened a border to find. Now
  // that every other task shows its steps unasked, a blank where they belong
  // reads as broken -- and the step carries whether it can reach the folder,
  // which is worth the row on its own.
  const only = el.querySelector<HTMLElement>('[data-task="board/chores"] .basic-node')!
  expect(only.dataset.node).toBe("work")
  expect(only.querySelector(".basic-node-hands")).not.toBeNull()
  handle.destroy()
})

const warning = () => el.querySelector('[data-task="board/chores"] .basic-warn')!.textContent

test("a task that edits the folder itself says so, with the border shut", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([oneStep()]))

  // A run normally works in a private copy and lands the night as a change to
  // accept or discard, which is what makes a step that edits files ordinary.
  // With no copy there is nothing to discard: the run edits the folder, and
  // the morning cannot take it back. That is the one thing on a board of
  // healthy-looking cards a reader must not have to open anything to find.
  expect(warning()).toBe("edits your files directly — no undo")
  handle.destroy()
})

test("a task with a private copy is not warned about: the morning covers it", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([{ ...oneStep(), into: "main" }]))

  expect(warning()).toBe("")
  handle.destroy()
})

test("a task with no copy that only answers is not warned about either", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([triage(["qwen3:8b", null, "qwen3:8b"])]))

  // Nothing in it can reach a file, so there is nothing a copy would protect.
  expect(warning()).toBe("")
  handle.destroy()
})

test("a task that reports no model at all leaves the trigger line alone", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([triage([null, null, null])]))

  // A binding the board could not read is not a reason to write "· null".
  expect(when()).toBe("loop")
  handle.destroy()
})


test("a connector is drawn only where the run really goes", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage([triage(["mock", null, "mock"])]))

  // The entry is arrived at from nowhere. route is arrived at from classify,
  // and draft from route -- and nothing is drawn between two nodes that only
  // happen to share a column.
  expect(pill("classify").dataset.from).toBeUndefined()
  expect(pill("route").dataset.from).toBe("true")
  expect(pill("draft").dataset.from).toBe("true")
  handle.destroy()
})


test("a border is exactly as wide as the arrows think it is", () => {
  // The arrows' geometry is arithmetic rather than measurement, which is what
  // makes it testable at all -- so the constant they are drawn against has to
  // be the width that renders. Declared in the stylesheet it was free to
  // drift from BOX.width, and content-box padding had made it 26px wider:
  // every wire began that far inside the box it was leaving.
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(FLOWS))

  expect(el.querySelector<HTMLElement>('[data-task="board/chores"]')!.style.width).toBe(
    `${BOX.width}px`,
  )
  handle.destroy()
})


test("a handoff that goes back does not run through what lies between", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(
    initialStage([
      { ...FLOWS[0], then: [{ to: "revision", label: "changed" }] },
      { ...FLOWS[1], then: [{ to: "chores", label: "and again" }] },
    ]),
  )

  // Two arrows: one forward, one back. Drawn alike, the back one runs at the
  // same height as every box and every word between the two, straight
  // through them.
  const wires = Array.from(el.querySelectorAll(".basic-wire")).map((w) => w.getAttribute("d")!)
  expect(wires).toHaveLength(2)
  const [, backward] = wires
  // Round, under, and up: four turns, where a step onward is one curve.
  expect(backward).toMatch(/H .* V .* H .* V /)

  // And its head points up into an underside, which no arrow going forward
  // ever does -- so the reader cannot read it as one.
  const tips = Array.from(el.querySelectorAll(".basic-tip")).map((t) => t.getAttribute("d")!)
  const rise = (d: string) => {
    const [, , y1, , , y2] = d.split(/[ ,]/)
    return Number(y2) - Number(y1)
  }
  expect(rise(tips[0])).toBe(4)   // forward: level, pointing right
  expect(rise(tips[1])).toBe(-8)  // back: rising, pointing up
  handle.destroy()
})


test("opening a border by hand lays the board out again", () => {
  // Opening changes a border's height, and both the rows and the arrows are
  // measured off those heights. Left alone, every arrow keeps the geometry of
  // the board as it was before the click -- which is how a return leg ends up
  // drawn through the box it was meant to pass under.
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(WIRED))
  const before = el.querySelector(".basic-wire")

  el.querySelector<HTMLElement>('[data-task="board/revision"] .basic-toggle')!.click()

  expect(el.querySelector(".basic-wire")).not.toBe(before)
  handle.destroy()
})


test("the board hangs in a viewport, and takes it with it when it goes", () => {
  // The board is sized by its own layout and cannot place itself. The viewport
  // is the window it is seen through, and one transform on the board decides
  // what is on screen. The viewport also has to be what `destroy` removes:
  // taking the board out and leaving the viewport would leave an empty div in
  // the host on every skin change.
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(FLOWS))

  const viewport = el.querySelector(".basic-viewport")!
  expect(viewport).not.toBeNull()
  expect(viewport.querySelector(".basic")).not.toBeNull()

  handle.destroy()
  expect(el.querySelector(".basic-viewport")).toBeNull()
  expect(el.children).toHaveLength(0)
})

test("the board is placed by a transform, so nothing drawn has to know", () => {
  // jsdom measures nothing, so the numbers are all zero -- what this pins is
  // that a transform is written at all, and that it is finite. A NaN here
  // blanks the page, which is far harder to diagnose than a bad number.
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(FLOWS))

  const style = el.querySelector<HTMLElement>(".basic")!.style.transform
  expect(style).toMatch(/^translate\(-?[\d.]+px, -?[\d.]+px\) scale\([\d.]+\)$/)
  handle.destroy()
})


/** jsdom has pointer events but not capture, which the drag asks for. */
function letItGrab(el: Element) {
  const any = el as unknown as Record<string, unknown>
  any.setPointerCapture = () => {}
  any.releasePointerCapture = () => {}
}

const transform = () => el.querySelector<HTMLElement>(".basic")!.style.transform

test("a wheel over the board zooms it rather than scrolling the page", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(FLOWS))
  const before = transform()

  const wheel = new WheelEvent("wheel", { deltaY: -400, cancelable: true, bubbles: true })
  el.querySelector(".basic-viewport")!.dispatchEvent(wheel)

  expect(transform()).not.toBe(before)
  // Said before the browser acts on it, or the page scrolls out from under the
  // board the reader is trying to look at.
  expect(wheel.defaultPrevented).toBe(true)
  handle.destroy()
})

test("dragging the board moves it; pressing a control does not", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(FLOWS))
  const viewport = el.querySelector<HTMLElement>(".basic-viewport")!
  letItGrab(viewport)
  const before = transform()

  // Mouse events, because `d3-zoom` owns the gesture now and that is what it
  // listens for. `view` is set after construction rather than passed in:
  // jsdom's MouseEvent refuses to take a Window for that field, and d3 reads
  // it to find the window a drag continues on -- left unset it dereferences
  // null and the press throws.
  const here = document.defaultView!
  const mouse = (kind: string, x: number, bubbles = false) => {
    const at = new MouseEvent(kind, { clientX: x, clientY: 0, button: 0, bubbles })
    Object.defineProperty(at, "view", { value: here })
    return at
  }
  const drag = (from: Element, dx: number) => {
    from.dispatchEvent(mouse("mousedown", 0, true))
    here.dispatchEvent(mouse("mousemove", dx))
    here.dispatchEvent(mouse("mouseup", dx))
  }

  // A press that starts on a border's own button is that button's, not a grab
  // of the board behind it -- otherwise selecting a task would drag the board.
  drag(el.querySelector('[data-task="board/chores"] .basic-pick')!, 40)
  expect(transform()).toBe(before)

  drag(viewport, 40)
  expect(transform()).not.toBe(before)
  handle.destroy()
})

test("a double click puts the board back where it started", () => {
  // A reader who has zoomed into a corner otherwise has only a page reload.
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(FLOWS))
  const viewport = el.querySelector(".basic-viewport")!
  const fitted = transform()

  viewport.dispatchEvent(new WheelEvent("wheel", { deltaY: -400, cancelable: true, bubbles: true }))
  expect(transform()).not.toBe(fitted)

  viewport.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }))
  expect(transform()).toBe(fitted)
  handle.destroy()
})


test("the minimap carries one speck per task, and keeps its window rectangle", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(FLOWS))

  const map = el.querySelector(".basic-minimap")!
  expect(map.querySelectorAll(".basic-speck")).toHaveLength(FLOWS.length)
  expect(map.querySelectorAll("[data-speck]")).toHaveLength(FLOWS.length)
  // Redrawing the specks must not take the window rectangle with them: it is
  // replaced along with them and has to be put back.
  expect(map.querySelector(".basic-seen")).not.toBeNull()

  // `data-task` already means "a border on the board". One selector answering
  // with two kinds of thing is how a board of four tasks counts as eight.
  expect(el.querySelectorAll("[data-task]")).toHaveLength(FLOWS.length)
  handle.destroy()
})

test("pressing the minimap moves the view without also dragging the board", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(FLOWS))
  const viewport = el.querySelector(".basic-viewport")!
  const map = el.querySelector(".basic-minimap")!
  letItGrab(map)

  let grabbed = false
  viewport.addEventListener("pointerdown", () => {
    grabbed = true
  })
  map.dispatchEvent(
    new PointerEvent("pointerdown", { clientX: 10, clientY: 5, button: 0, bubbles: true }),
  )

  // Without the stop, a press on the minimap would jump the view and then hand
  // the same press to the board behind it as the start of a drag.
  expect(grabbed).toBe(false)
  handle.destroy()
})

test("a shut border says what the task is doing right now", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  // A running task, mid-graph: the answer to why somebody opened the board.
  const stage = replay(initialStage(FLOWS), AGENT_RUN.slice(0, 4))
  handle.update(stage)

  const now = el.querySelector('[data-task="board/chores"] .basic-now')!
  expect(now.textContent).toContain("work")
  handle.destroy()
})

test("a border with nothing happening says nothing, and takes no room for it", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  handle.update(initialStage(FLOWS))

  // Empty rather than absent: `:empty` is what the stylesheet hides on, so an
  // idle border is its name and its schedule and no blank space beneath.
  expect(el.querySelector('[data-task="board/revision"] .basic-now')!.textContent).toBe("")
  handle.destroy()
})

test("a task that stopped says so where it would have said what it was doing", () => {
  const handle = basic.mount(el, { onSelectTask: vi.fn() })
  // The task has to be known to be running before it can be known to have
  // stopped: `run_failed` carries no task of its own.
  let stage = reduce(initialStage(FLOWS), {
    run_id: "r",
    type: "run_started",
    data: { task: "chores", project: "board" },
  })
  stage = reduce(stage, { run_id: "r", type: "run_failed", data: { error: "boom" } })
  handle.update(stage)

  expect(el.querySelector('[data-task="board/chores"] .basic-now')!.textContent).toBe("stopped")
  handle.destroy()
})
