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
    root.render(<Drawer task="chores" onClose={() => {}} />)
  })
  // Two chained effects: the run list resolves, which picks a run, which
  // fetches its events.
  await act(async () => {})
}

const timeline = () => container.querySelector(".drawer-timeline")!.textContent ?? ""

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
