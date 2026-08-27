import { afterEach, beforeEach, expect, test, vi } from "vitest"

import { basic } from "./index"
import { AGENT_RUN } from "../../state/fixtures"
import { initialStage, reduce, replay, setRuns } from "../../state/stage"
import type { FlowRow } from "../../types"
import { BOX } from "../wiring"

const FLOWS: FlowRow[] = [
  {
    name: "chores",
    graph: "agent-task",
    trigger: "loop",
    status: "waiting",
    current_run_id: null,
    last_run: null,
    pending: 0,
    into: null,
    then: [],
    shape: {
      entry: "work",
      nodes: [{ id: "work", type: "agent", next: null, default: null, branches: [], model: null }],
    },
  },
  {
    name: "revision",
    graph: "draft-review",
    trigger: "loop",
    status: "waiting",
    current_run_id: null,
    last_run: null,
    pending: 0,
    into: null,
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

test("a frame for one flow does not rebuild the other flows' boxes", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  const stage = replay(initialStage(FLOWS), AGENT_RUN)
  handle.update(stage)

  // chores is drawn with its graph's nodes inside it.
  const node = el.querySelector('[data-flow="chores"] .basic-node')
  expect(node).not.toBeNull()

  // An event for the other flow arrives; chores was not touched, and the
  // reducer keeps its object identity, so its DOM must survive untouched.
  const next = reduce(stage, {
    run_id: "rr",
    type: "run_started",
    data: { flow: "revision" },
  })
  handle.update(next)

  expect(el.querySelector('[data-flow="chores"] .basic-node')).toBe(node)
  // The flow the frame was for did repaint.
  expect(el.querySelector('[data-flow="revision"]')!.getAttribute("data-status")).toBe(
    "running",
  )
  handle.destroy()
})

const WIRED: FlowRow[] = [
  {
    ...FLOWS[0],
    then: [
      { to: "revision", label: "changed" },
      { to: null, label: "quiet" },
    ],
  },
  FLOWS[1],
]

test("a flow that is running opens itself; the rest stay shut", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(replay(initialStage(FLOWS), AGENT_RUN.slice(0, 4)))

  // Detail where something is happening, and only there: a board of ten flows
  // opened all the way is sixty nodes, which is not a glance.
  expect(el.querySelector('[data-flow="chores"]')!.getAttribute("data-open")).toBe("true")
  expect(el.querySelector('[data-flow="revision"]')!.getAttribute("data-open")).toBe("false")
  handle.destroy()
})

test("opening a flow by hand outlasts the frames that follow", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  const stage = initialStage(FLOWS)
  handle.update(stage)

  el.querySelector<HTMLElement>('[data-flow="revision"] .basic-toggle')!.click()
  expect(el.querySelector('[data-flow="revision"]')!.getAttribute("data-open")).toBe("true")

  // A frame for that flow must not undo the reader's own choice.
  handle.update(reduce(stage, { run_id: "r", type: "run_started", data: { flow: "revision" } }))
  expect(el.querySelector('[data-flow="revision"]')!.getAttribute("data-open")).toBe("true")
  handle.destroy()
})

test("a handoff is drawn as an arrow carrying the word on it", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(initialStage(WIRED))

  // One arrow, not two: the branch that deliberately stops has nothing to
  // point at, and an arrow to nowhere would be a line the reader must ignore.
  expect(el.querySelectorAll(".basic-wire")).toHaveLength(1)
  expect(el.querySelector(".basic-word")!.textContent).toBe("changed")
  handle.destroy()
})

test("a handoff says which way it goes", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(initialStage(WIRED))

  // The whole board rests on one rule -- an arrow that crosses a border ends
  // one run and starts another -- and a bare line is not an arrow. Without a
  // head, "chores hands to review" reads exactly like the reverse.
  const heads = el.querySelectorAll(".basic-tip")
  expect(heads).toHaveLength(1)
  // Pointing at the flow being handed to, not away from it.
  expect(heads[0].getAttribute("d")).toContain(String(BOX.width + BOX.gapX))
  handle.destroy()
})

test("the word on an arrow sits on the line it names", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(initialStage(WIRED))

  // Floated above the line it belonged to the box underneath it instead, and
  // on the top row it had the board's own edge to collide with.
  const [, , y] = el.querySelector(".basic-wire")!.getAttribute("d")!.split(/[ ,]/)
  expect(el.querySelector(".basic-word")!.getAttribute("y")).toBe(y)
  handle.destroy()
})

test("a flow to the right of its sender is not laid on top of it", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(initialStage(WIRED))

  const from = el.querySelector<HTMLElement>('[data-flow="chores"]')!
  const to = el.querySelector<HTMLElement>('[data-flow="revision"]')!
  expect(from.style.left).toBe("0px")
  expect(parseInt(to.style.left, 10)).toBeGreaterThan(0)
  expect(to.style.top).toBe(from.style.top)
  handle.destroy()
})

test("a flow that found nothing to do says so in one word, not a number", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  // Tracked: a flow that keeps a private copy is the one that can find
  // nothing to do. Without one there is nothing to change against, and a run
  // that ran is all there is to say.
  const quiet = setRuns(
    initialStage([{ ...FLOWS[0], into: "main" }, FLOWS[1]]),
    "chores",
    // Eight runs that all looked and found nothing: a healthy night, and the
    // line the board used to print for it was "8 runs · 8 found nothing to do".
    Array.from({ length: 8 }, (_, i) => ({
      run_id: `r${i}`,
      flow: "chores",
      graph: "agent-task",
      status: "completed",
      started_at: "2026-08-27T02:00:00+00:00",
      finished_at: "2026-08-27T02:00:04+00:00",
      steps: 1,
      iteration: 1,
      trigger: "cron",
      usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
      error: null,
    })),
  )
  handle.update(quiet)

  const said = el.querySelector('[data-flow="chores"] .basic-tally')!.textContent!
  expect(said).toContain("quiet")
  expect(said).not.toContain("8")
  handle.destroy()
})


/** A flow whose graph is a triage line: classify, route, then draft. */
function triage(models: (string | null)[]): FlowRow {
  const [classify, route, draft] = models
  return {
    ...FLOWS[0],
    name: "chores",
    shape: {
      entry: "classify",
      nodes: [
        { id: "classify", type: "llm", next: "route", default: null, branches: [], model: classify },
        {
          id: "route",
          type: "router",
          next: null,
          default: "draft",
          branches: [],
          model: route,
        },
        { id: "draft", type: "llm", next: null, default: null, branches: [], model: draft },
      ],
    },
  }
}

const when = () => el.querySelector('[data-flow="chores"] .basic-when')!.textContent
const pill = (id: string) =>
  el.querySelector<HTMLElement>(`[data-flow="chores"] [data-node="${id}"]`)!

test("a flow that resolves to one model says so once, beside the trigger", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(initialStage([triage(["qwen3:8b", null, "qwen3:8b"])]))

  // Said once, on the line that is legible with the border shut: ten flows
  // collapsed is the glance, and "what is running my board" is answered there.
  expect(when()).toBe("loop · qwen3:8b")
  // ...and not repeated on every node, which would be noise for one answer.
  expect(pill("classify").querySelector(".basic-node-model")).toBeNull()
  handle.destroy()
})

test("a flow on two models counts them, and each node carries its own", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(initialStage([triage(["llama3.2:3b", null, "claude-opus-5"])]))

  // The header cannot answer it, so it stops trying and says how many;
  // opening the border is what says which is which.
  expect(when()).toBe("loop · 2 models")
  expect(pill("classify").querySelector(".basic-node-model")!.textContent).toBe("llama3.2:3b")
  expect(pill("draft").querySelector(".basic-node-model")!.textContent).toBe("claude-opus-5")
  handle.destroy()
})

test("a router carries no model, because it calls none", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(initialStage([triage(["llama3.2:3b", null, "claude-opus-5"])]))

  // The gap is information: it is why branching is free.
  expect(pill("route").querySelector(".basic-node-model")).toBeNull()
  handle.destroy()
})

test("a flow that reports no model at all leaves the trigger line alone", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(initialStage([triage([null, null, null])]))

  // A binding the board could not read is not a reason to write "· null".
  expect(when()).toBe("loop")
  handle.destroy()
})


test("a connector is drawn only where the run really goes", () => {
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(initialStage([triage(["mock", null, "mock"])]))

  // classify -> route is a step. route -> draft is the router's default, so
  // that is a step too. Nothing after that: the arms are siblings.
  expect(pill("classify").dataset.leadsOn).toBe("true")
  expect(pill("route").dataset.leadsOn).toBe("true")
  expect(pill("draft").dataset.leadsOn).toBeUndefined()
  handle.destroy()
})


test("a border is exactly as wide as the arrows think it is", () => {
  // The arrows' geometry is arithmetic rather than measurement, which is what
  // makes it testable at all -- so the constant they are drawn against has to
  // be the width that renders. Declared in the stylesheet it was free to
  // drift from BOX.width, and content-box padding had made it 26px wider:
  // every wire began that far inside the box it was leaving.
  const handle = basic.mount(el, { onSelectWorker: vi.fn() })
  handle.update(initialStage(FLOWS))

  expect(el.querySelector<HTMLElement>('[data-flow="chores"]')!.style.width).toBe(
    `${BOX.width}px`,
  )
  handle.destroy()
})
