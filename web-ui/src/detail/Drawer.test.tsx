import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

import type { PoieoEvent, RunSummary } from "../types"

const fetchRuns = vi.hoisted(() => vi.fn())
const fetchRunEvents = vi.hoisted(() => vi.fn())
vi.mock("../api", () => ({
  fetchRuns,
  fetchRunEvents,
  fetchDiff: vi.fn(async () => null),
  accept: vi.fn(),
  discard: vi.fn(),
  pause: vi.fn(),
  resume: vi.fn(),
  runNow: vi.fn(),
}))

import { Drawer } from "./Drawer"

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  fetchRuns.mockReset()
  fetchRunEvents.mockReset()
  fetchRuns.mockResolvedValue([])
  fetchRunEvents.mockResolvedValue([])
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

const run: RunSummary = {
  run_id: "r1",
  task: "chores",
  project: "chores",
  graph: "chores",
  status: "completed",
  started_at: "2026-08-26T02:00:00Z",
  finished_at: "2026-08-26T02:00:04Z",
  steps: 2,
  iteration: 1,
  trigger: "every 1h",
  usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
  error: null,
  said: "swept the hallway",
}

function event(type: string, extra: Partial<PoieoEvent> = {}): PoieoEvent {
  return { run_id: "r1", type, at: "2026-08-26T02:00:01Z", ...extra }
}

async function show(events: PoieoEvent[]) {
  fetchRuns.mockResolvedValue([run])
  fetchRunEvents.mockResolvedValue(events)
  await act(async () => {
    root.render(<Drawer project="board" task="chores" onClose={() => {}} />)
  })
  // Two chained effects: the run list resolves, which picks a run, which
  // fetches its events.
  await act(async () => {})
}

const timeline = () => container.querySelector(".drawer-timeline")!.textContent ?? ""

test("it is one of the panels on the right edge, not a third geometry", async () => {
  await show([])
  expect(container.querySelector("aside")?.classList.contains("panel")).toBe(true)
})

test("a step says its name and nothing about what kind of node it is", async () => {
  await show([event("node_started", { node_id: "sweep", data: { type: "agent" } })])

  const entry = container.querySelector('[data-kind="node"]')!
  expect(entry.textContent).toContain("sweep")
  expect(entry.textContent).not.toContain("agent")
})

test("a second turn is another entry, not a counter", async () => {
  await show([
    event("node_turn", { node_id: "sweep", data: { text: "looking", turn: 1 } }),
    event("node_turn", { node_id: "sweep", data: { text: "swept", turn: 2 } }),
  ])

  expect(container.querySelectorAll('[data-kind="turn"]')).toHaveLength(2)
  expect(timeline()).not.toContain("turn 2")
})

test("a tool that answered instantly does not report its milliseconds", async () => {
  await show([event("node_tool_call", { data: { name: "read_file", duration_ms: 0 } })])

  const entry = container.querySelector('[data-kind="tool"]')!
  expect(entry.textContent).toContain("read_file")
  expect(entry.textContent).not.toContain("0ms")
})

test("a tool says what it acted on and what came back", async () => {
  // Twenty rows reading "read_file" are twenty rows a reader learns nothing
  // from. The path is the row.
  await show([
    event("node_tool_call", {
      data: {
        name: "read_file",
        arguments: '{"path": "DESIGN.md"}',
        result: "# poieo Design",
        error: false,
        duration_ms: 0,
      },
    }),
  ])

  const entry = container.querySelector('[data-kind="tool"]')!
  expect(entry.textContent).toContain("DESIGN.md")
  expect(entry.textContent).toContain("# poieo Design")
})

test("a tool that failed is marked failed, and error is a boolean", async () => {
  // The daemon writes `error: bool`; the drawer used to test it for a string,
  // so a failing tool rendered exactly like one that worked.
  await show([
    event("node_tool_call", {
      data: {
        name: "read_file",
        arguments: '{"path": "nope.md"}',
        result: "no such file: nope.md",
        error: true,
        duration_ms: 0,
      },
    }),
  ])

  const entry = container.querySelector('[data-kind="tool"]')!
  expect(entry.getAttribute("data-error")).toBe("true")
  expect(entry.textContent).toContain("no such file: nope.md")
})

test("a turn says how big it was", async () => {
  // The run's own total says what the whole step cost. What a reader chasing
  // a step that slowed down wants is which turn it happened on.
  await show([
    event("node_turn", {
      data: { turn: 8, text: "thinking about it", input_tokens: 84210, output_tokens: 3120 },
    }),
  ])

  const entry = container.querySelector('[data-kind="turn"]')!
  expect(entry.textContent).toContain("84,210")
  expect(entry.textContent).toContain("3,120")
})

test("a turn with nothing in it does not take a row", async () => {
  // A model that goes straight to a tool leaves an empty turn behind. The
  // tool call under it already says the turn happened.
  await show([
    event("node_turn", { data: { text: "", thinking: "", turn: 1 } }),
    event("node_tool_call", { data: { name: "read_file", duration_ms: 0 } }),
  ])

  expect(container.querySelectorAll('[data-kind="turn"]')).toHaveLength(0)
  expect(container.querySelectorAll('[data-kind="tool"]')).toHaveLength(1)
})

test("a run that cleared its own history says so in the timeline", async () => {
  // A step whose conversation quietly shrinks is a step nobody can reason
  // about afterwards. The reader has to be able to see it happen.
  await show([
    event("node_context_cleared", { data: { turn: 8, freed: 30997, kept: 3 } }),
  ])

  const entry = container.querySelector('[data-kind="cleared"]')!
  expect(entry.textContent).toContain("30,997")
  expect(entry.textContent).toContain("3")
})

test("machinery that could not do its job says so in the timeline", async () => {
  // The two ways a run's own housekeeping can fail. Neither stops the work,
  // and that is exactly why both have to be seen: a run whose change was
  // never recorded looks identical to one that had nothing to do, and every
  // `then:` written against `run.change` silently stops firing.
  await show([
    event("run_change_failed", { data: { error: "Could not read fd0489dc" } }),
    event("node_compact_failed", { data: { error: "the summarizer is down" } }),
  ])

  const rows = container.querySelectorAll('[data-kind="stuck"]')
  expect(rows).toHaveLength(2)
  expect(rows[0].textContent).toContain("fd0489dc")
  expect(rows[1].textContent).toContain("summarizer")
})

test("an endpoint that dropped our conversation says so in the timeline", async () => {
  // The quiet failure. Ollama past num_ctx does not refuse -- it truncates and
  // answers, so the model replies from a conversation with its beginning
  // missing and nothing anywhere says a word.
  await show([
    event("node_input_dropped", {
      data: { turn: 6, before: 4010, kept: 2050, freed: 8000, note: "" },
    }),
  ])

  const entry = container.querySelector('[data-kind="stuck"]')!
  expect(entry.textContent).toContain("4,010")
  expect(entry.textContent).toContain("2,050")
})

test("a tool worth waiting for reports how long it took", async () => {
  await show([event("node_tool_call", { data: { name: "run_tests", duration_ms: 4200 } })])

  expect(container.querySelector('[data-kind="tool"]')!.textContent).toContain("4.2s")
})

test("a short answer is a paragraph, with no triangle to open", async () => {
  await show([event("node_turn", { data: { text: "swept the hallway" } })])

  expect(container.querySelector(".drawer-said")).toBeNull()
  expect(container.querySelector(".drawer-text")!.textContent).toBe("swept the hallway")
})

test("a long answer folds behind its first line, so the run stays readable", async () => {
  const text = `swept the hallway\n${"and then a great deal more about it. ".repeat(20)}`
  await show([event("node_turn", { data: { text } })])

  const said = container.querySelector(".drawer-said")!
  expect(said.querySelector("summary")!.textContent).toContain("swept the hallway")
  // Folded, not dropped: the whole answer is one click away.
  expect(said.querySelector(".drawer-text")!.textContent).toBe(text)
  expect((said as HTMLDetailsElement).open).toBe(false)
})

test("a failed run says why on the timeline", async () => {
  await show([event("run_failed", { data: { error: "the model refused" } })])

  const entry = container.querySelector('[data-error="true"]')!
  expect(entry.textContent).toContain("the model refused")
})

test("a card the daemon will not adopt says why, in the daemon's own words", async () => {
  // The board's card carries the short form -- what to do -- because ten
  // cards have no room for more. A reader who opened this one came for the
  // whole sentence.
  const why = "the card changed more than its prompt, and the rest of it only takes effect on a restart"
  fetchRuns.mockResolvedValue([])
  await act(async () => {
    root.render(<Drawer project="board" task="chores" stale={why} onClose={() => {}} />)
  })
  await act(async () => {})

  expect(container.querySelector(".drawer-stale")?.textContent).toBe(why)
})

test("a card nobody edited says nothing about restarts", async () => {
  await show([])
  expect(container.querySelector(".drawer-stale")).toBeNull()
})
