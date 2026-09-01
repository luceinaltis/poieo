/// <reference types="node" />

import { readFileSync } from "node:fs"
import { act } from "react"
import type { ComponentProps } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

import type { PoieoEvent, RunSummary } from "../types"

const fetchRuns = vi.hoisted(() => vi.fn<typeof import("../api").fetchRuns>())
const fetchRunEvents = vi.hoisted(() =>
  vi.fn<typeof import("../api").fetchRunEvents>(),
)
const fetchDiff = vi.hoisted(() => vi.fn<typeof import("../api").fetchDiff>())
vi.mock("../api", () => ({
  fetchRuns,
  fetchRunEvents,
  fetchDiff,
  accept: vi.fn<typeof import("../api").accept>(),
  discard: vi.fn<typeof import("../api").discard>(),
  pause: vi.fn<typeof import("../api").pause>(),
  resume: vi.fn<typeof import("../api").resume>(),
  runNow: vi.fn<typeof import("../api").runNow>(),
}))

import { Drawer } from "./Drawer"

const DRAWER_CSS = readFileSync("src/detail/drawer.css", "utf8")

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  fetchRuns.mockReset()
  fetchRunEvents.mockReset()
  fetchDiff.mockReset()
  fetchRuns.mockResolvedValue([])
  fetchRunEvents.mockResolvedValue([])
  fetchDiff.mockResolvedValue(null)
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
  fetchRunEvents.mockResolvedValue(events)
  await draw([run])
  await press('[data-do="toggle-activity"]')
}

async function draw(
  runs: RunSummary[] = [],
  props: Partial<ComponentProps<typeof Drawer>> = {},
) {
  fetchRuns.mockResolvedValue(runs)
  await act(async () => {
    root.render(<Drawer project="board" task="chores" onClose={() => {}} {...props} />)
  })
  await act(async () => {})
}

async function press(selector: string) {
  await act(async () => {
    container.querySelector<HTMLElement>(selector)!.click()
  })
  await act(async () => {})
}

const timeline = () => container.querySelector(".drawer-timeline")!.textContent ?? ""

test("it is one of the panels on the right edge, not a third geometry", async () => {
  await show([])
  expect(container.querySelector("aside")?.classList.contains("panel")).toBe(true)
})

test("the panel is named by the task heading", async () => {
  await draw()

  const panel = container.querySelector("aside")!
  const labelledBy = panel.getAttribute("aria-labelledby")!
  expect(labelledBy).toBeTruthy()
  expect(container.querySelector(`#${labelledBy}`)?.textContent).toBe("chores")
})

test("the first glance leads with attention and the newest run", async () => {
  const olderChange: RunSummary = {
    ...run,
    run_id: "older-change",
    started_at: "2026-08-26T01:00:00Z",
    finished_at: "2026-08-26T01:00:04Z",
    change: {
      base: "a",
      head: "b",
      files: ["hallway.md"],
      insertions: 3,
      deletions: 1,
      message: "repaired the hallway",
    },
  }
  const newest: RunSummary = {
    ...run,
    run_id: "newest",
    said: "looked around and found nothing",
    usage: {
      input_tokens: 660_598,
      output_tokens: 58_072,
      cache_read_tokens: 633_344,
      cache_write_tokens: 0,
    },
  }

  await draw([newest, olderChange], { into: "main" })

  expect(container.querySelector(".drawer-state")?.textContent).toBe("No action needed")
  expect(container.querySelector(".run-brief h3")?.textContent).toBe("Latest run")
  expect(container.querySelector(".run-brief-what")?.textContent).toContain(
    "looked around and found nothing",
  )
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain("96% cached")
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain("No files changed")
  expect(container.textContent).not.toContain("repaired the hallway")
  expect(fetchRunEvents).not.toHaveBeenCalled()

  const history = container.querySelector<HTMLButtonElement>('[data-do="toggle-runs"]')!
  expect(history.textContent).toContain("All runs")
  expect(history.textContent).toContain("2")
  expect(history.getAttribute("aria-expanded")).toBe("false")
})

test("a fresher run index outranks a stale live window", async () => {
  const staleRuns = Array.from({ length: 10 }, (_, index) => ({
    ...run,
    run_id: `stale-${index}`,
    started_at: `2026-08-26T01:${String(59 - index).padStart(2, "0")}:00Z`,
    finished_at: `2026-08-26T01:${String(59 - index).padStart(2, "0")}:04Z`,
  }))
  const fresh = {
    ...run,
    run_id: "fresh-from-index",
    started_at: "2026-08-26T03:00:00Z",
    finished_at: "2026-08-26T03:00:04Z",
    said: "the newest indexed result",
  }

  await draw([fresh], { liveRuns: staleRuns })

  expect(container.querySelector(".run-brief")?.getAttribute("data-run")).toBe(
    "fresh-from-index",
  )
})

test("an older run replaces the brief and closes the run list", async () => {
  const older: RunSummary = {
    ...run,
    run_id: "older",
    started_at: "2026-08-25T22:00:00Z",
    finished_at: "2026-08-25T22:00:08Z",
    said: "an older account",
  }
  await draw([{ ...run, run_id: "newest", said: "the latest account" }, older], {
    into: null,
  })

  await press('[data-do="toggle-runs"]')
  expect(container.querySelector('[data-do="toggle-runs"]')?.getAttribute("aria-expanded")).toBe(
    "true",
  )
  await press('[data-run="older"] .run-open')

  expect(container.querySelector('[data-do="toggle-runs"]')?.getAttribute("aria-expanded")).toBe(
    "false",
  )
  expect(container.querySelector(".run-brief h3")?.textContent).toBe("Selected run")
  expect(container.querySelector(".run-brief-what")?.textContent).toContain("an older account")
  expect(container.querySelector('[data-do="toggle-activity"]')?.getAttribute("aria-expanded")).toBe(
    "false",
  )
  expect(fetchRunEvents).not.toHaveBeenCalled()
})

test("activity stays folded and is fetched only when opened", async () => {
  fetchRunEvents.mockResolvedValue([
    event("run_started"),
    event("node_tool_call", { data: { name: "read_file", arguments: '{"path":"README.md"}' } }),
  ])
  await draw([run])

  const toggle = container.querySelector<HTMLButtonElement>('[data-do="toggle-activity"]')!
  expect(toggle.getAttribute("aria-expanded")).toBe("false")
  expect(container.querySelector(".drawer-timeline")).toBeNull()
  expect(fetchRunEvents).not.toHaveBeenCalled()

  await press('[data-do="toggle-activity"]')

  expect(fetchRunEvents).toHaveBeenCalledWith("r1")
  expect(toggle.getAttribute("aria-expanded")).toBe("true")
  expect(toggle.textContent).toContain("1")
  expect(container.querySelector(".drawer-timeline")?.textContent).toContain("README.md")
})

test("activity gives direction when it is empty or cannot be loaded", async () => {
  await draw([run])
  fetchRunEvents.mockRejectedValueOnce(new Error("offline"))

  await press('[data-do="toggle-activity"]')
  expect(container.querySelector(".activity-error")?.textContent).toContain("could not be loaded")

  fetchRunEvents.mockResolvedValueOnce([])
  await press('[data-do="retry-activity"]')
  expect(container.querySelector(".activity-empty")?.textContent).toContain("No activity")
  expect(fetchRunEvents).toHaveBeenCalledTimes(2)
})

test("a late activity response cannot cross into another selected run", async () => {
  let resolveLatest!: (events: PoieoEvent[]) => void
  fetchRunEvents.mockImplementation((runId: string) =>
    runId === "newest"
      ? new Promise<PoieoEvent[]>((resolve) => {
          resolveLatest = resolve
        })
      : Promise.resolve([
          { ...event("node_tool_call", { data: { name: "read_file", arguments: "older.md" } }), run_id: runId },
        ]),
  )
  await draw([
    { ...run, run_id: "newest" },
    { ...run, run_id: "older", started_at: "2026-08-25T22:00:00Z" },
  ])

  await press('[data-do="toggle-activity"]')
  await press('[data-do="toggle-runs"]')
  await press('[data-run="older"] .run-open')
  expect(container.querySelector('[data-do="toggle-activity"]')?.getAttribute("aria-expanded")).toBe(
    "false",
  )

  await act(async () => {
    resolveLatest([
      event("node_tool_call", { data: { name: "read_file", arguments: "stale.md" } }),
    ])
  })
  expect(container.textContent).not.toContain("stale.md")

  await press('[data-do="toggle-activity"]')
  expect(container.querySelector(".drawer-timeline")?.textContent).toContain("older.md")
})

test("a task with no runs points to what happens next", async () => {
  await draw()

  expect(container.querySelector(".run-brief h3")?.textContent).toBe("Latest run")
  expect(container.querySelector(".run-empty")?.textContent).toContain("Run now or wait")
  expect(container.querySelector('[data-do="toggle-runs"]')).toBeNull()
  expect(container.querySelector('[data-do="toggle-activity"]')).toBeNull()
})

test("a person's answer outranks every other task state", async () => {
  await draw([{ ...run, status: "asking", said: "Ship this change?" }], {
    status: "error",
    pending: 2,
    into: "main",
    stale: "restart the daemon",
    asking: {
      run_id: "asking",
      question: "Ship this change?",
      choices: ["ship", "hold"],
    },
  })

  expect(container.querySelector(".drawer-state")?.textContent).toBe("Needs your answer")
  const question = container.querySelector(".question")!
  const control = container.querySelector(".control")!
  expect(question.compareDocumentPosition(control) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  expect(container.querySelector(".run-brief-what")?.textContent).toBe("Ship this change?")
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain("Asked 11:00")
  expect(container.querySelector(".run-brief")?.getAttribute("data-outcome")).toBe("waiting")
})

test("attention names a waiting change, a restart, and a failed run", async () => {
  await draw([run], { pending: 1, into: "main" })
  expect(container.querySelector(".drawer-state")?.textContent).toBe("1 change to review")

  await draw([run], { pending: 0, into: "main", stale: "restart the daemon" })
  expect(container.querySelector(".drawer-state")?.textContent).toBe("Restart needed")

  await draw([{ ...run, status: "failed", error: "the endpoint stopped" }], {
    status: "error",
    stale: null,
  })
  expect(container.querySelector(".drawer-state")?.textContent).toBe("Latest run failed")
})

test("routine runtime states remain no action needed", async () => {
  await draw([run], { status: "running" })
  expect(container.querySelector(".drawer-state")?.textContent).toBe("No action needed")

  await draw([run], { status: "paused", enabled: false })
  expect(container.querySelector(".drawer-state")?.textContent).toBe("No action needed")
})

test("a changed run brief includes its result and change size", async () => {
  await draw([
    {
      ...run,
      said: "repaired the hallway",
      change: {
        base: "a",
        head: "b",
        files: ["hallway.md"],
        insertions: 3,
        deletions: 1,
        message: "repaired the hallway",
      },
    },
  ])

  expect(container.querySelector(".run-brief-what")?.textContent).toBe("repaired the hallway")
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain("+3 / -1 · 1 file")
})

test("a failed run brief includes the failure and stopped time", async () => {
  await draw([{ ...run, status: "failed", error: "the endpoint stopped" }])

  expect(container.querySelector(".run-brief-what")?.textContent).toBe("the endpoint stopped")
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain("Stopped 11:00")
})

test("a quiet run keeps its outcome in the brief instead of duplicate machinery", async () => {
  await draw([run], { into: "main" })

  expect(container.querySelector(".diff-note")).toBeNull()
  expect(container.querySelector(".drawer-summary")).toBeNull()
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain("Finished 11:00")
})

test("the card fold is named for what the reader finds there", async () => {
  await draw()
  expect(container.querySelector(".card-open")?.textContent).toBe("Task setup")
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

test("a long tool record stays inside the drawer's event column", async () => {
  const unbroken = "x".repeat(1_000)
  await show([
    event("node_tool_call", {
      data: {
        name: "run_command",
        arguments: JSON.stringify({ command: unbroken }),
        result: unbroken,
        error: false,
      },
    }),
  ])

  const body = container.querySelector<HTMLElement>(".drawer-body")!
  const entry = container.querySelector<HTMLElement>(".drawer-entry")!
  const content = container.querySelector<HTMLElement>(".drawer-event")!
  expect(body.contains(content)).toBe(true)
  expect(entry.lastElementChild).toBe(content)
  expect(content.textContent).toContain(unbroken)
  expect(DRAWER_CSS).toMatch(
    /\.drawer-entry\s*\{[^}]*grid-template-columns:\s*auto minmax\(0,\s*1fr\)/s,
  )
  expect(DRAWER_CSS).toMatch(/\.drawer-event\s*\{[^}]*overflow-wrap:\s*anywhere/s)
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
