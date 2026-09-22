/// <reference types="node" />

import { readFileSync } from "node:fs"
import { act } from "react"
import type { ComponentProps } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

import type { PoieoEvent, RunSummary } from "../types"
import { shortTime } from "../when"

const fetchRuns = vi.hoisted(() => vi.fn<typeof import("../api").fetchRuns>())
const fetchRunEvents = vi.hoisted(() =>
  vi.fn<typeof import("../api").fetchRunEvents>(),
)
const fetchDiff = vi.hoisted(() => vi.fn<typeof import("../api").fetchDiff>())
const fetchRunMemory = vi.hoisted(() => vi.fn<typeof import("../api").fetchRunMemory>())
const fetchRunSummary = vi.hoisted(() => vi.fn<typeof import("../api").fetchRunSummary>())
vi.mock("../api", () => ({
  fetchRuns,
  fetchRunEvents,
  fetchDiff,
  fetchRunMemory,
  fetchRunSummary,
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
  fetchRunMemory.mockReset()
  fetchRunSummary.mockReset()
  fetchRuns.mockResolvedValue([])
  fetchRunEvents.mockResolvedValue([])
  fetchDiff.mockResolvedValue(null)
  fetchRunMemory.mockResolvedValue(null)
  fetchRunSummary.mockResolvedValue(null)
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

test("the heading is the card's title, with the name it answers to beneath", async () => {
  // The title is the card's own word for itself; the name is the file, and
  // the one the rename field and every route go by. Both, and told apart.
  await draw([], { title: "Keep the tests green" })

  const panel = container.querySelector("aside")!
  const labelledBy = panel.getAttribute("aria-labelledby")!
  expect(container.querySelector(`#${labelledBy}`)?.textContent).toBe("Keep the tests green")
  expect(container.querySelector(".drawer-id")?.textContent).toBe("chores")
})

test("a title that is the name is said once", async () => {
  await draw([], { title: "chores" })
  expect(container.querySelector(".drawer-id")).toBeNull()
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
  expect(toggle.textContent).toContain("Run activity")
  expect(toggle.getAttribute("aria-expanded")).toBe("false")
  expect(container.querySelector(".drawer-timeline")).toBeNull()
  expect(fetchRunEvents).not.toHaveBeenCalled()

  await press('[data-do="toggle-activity"]')

  expect(fetchRunEvents).toHaveBeenCalledWith("r1")
  expect(toggle.getAttribute("aria-expanded")).toBe("true")
  expect(toggle.textContent).toContain("1")
  expect(container.querySelector(".drawer-timeline")?.textContent).toContain("README.md")
})

test("the selected run owns its activity before the run picker", async () => {
  await draw([run])

  const focused = container.querySelector(".run-focus")!
  expect(focused.querySelector(".run-brief")).not.toBeNull()
  expect(focused.querySelector('[data-do="toggle-activity"]')).not.toBeNull()
  expect(focused.querySelector('[data-do="toggle-runs"]')).toBeNull()
  expect(
    focused.compareDocumentPosition(container.querySelector('[data-do="toggle-runs"]')!) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).not.toBe(0)
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
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain(
    `Asked ${shortTime(run.finished_at)}`,
  )
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

test("a run that applied its own change says so, with the checks that let it", async () => {
  const applied: RunSummary = {
    ...run,
    change: { base: "a1", head: "b2", files: ["src/x.py"], insertions: 3, deletions: 1, message: "fixed x" },
    application: {
      status: "applied",
      accepted: 1,
      before: "a1",
      after: "c3",
      checks: [{ command: "pytest -q", exit_code: 0, output: "3 passed" }],
    },
  }
  await draw([applied], { into: "main" })
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain("Applied to main")
  const checks = container.querySelector(".run-checks") as HTMLElement
  expect(checks.querySelector("summary")?.textContent).toBe("1 check passed")
  expect(checks.textContent).toContain("pytest -q")
  expect(checks.textContent).toContain("3 passed")
  const commands = Array.from(container.querySelectorAll(".run-focus code"))
    .filter((entry) => entry.textContent === "pytest -q")
  expect(commands).toHaveLength(1)
})

test.each([
  [{ status: "undone" }, "Undone"],
  [{ status: "discarded" }, "Discarded"],
  [{ status: "applied", undo_of: "r0" }, "Undo applied"],
  [{ status: "applied", unchanged: true, accepted: 0 }, "Already included"],
] as const)("the run brief preserves its recorded outcome %s", async (application, label) => {
  await draw([{ ...run, application }], { into: "main" })
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain(label)
  expect(container.querySelector(".run-brief-meta")?.textContent).not.toContain("Not applied")
})

test("a run whose change could not be applied says which check refused it", async () => {
  const blocked: RunSummary = {
    ...run,
    status: "asking",
    change: { base: "a1", head: "b2", files: ["src/x.py"], insertions: 3, deletions: 1, message: "fixed x" },
    application: {
      status: "blocked",
      error: "verification failed",
      checks: [
        { command: "ruff check .", exit_code: 0, output: "All checks passed!" },
        { command: "pytest -q", exit_code: 1, output: "1 failed" },
      ],
    },
  }
  await draw([blocked], { into: "main" })
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain("Not applied")
  const checks = container.querySelector(".run-checks") as HTMLElement
  expect(checks.querySelector("summary")?.textContent).toBe("pytest -q failed (exit 1)")
  expect(checks.querySelectorAll("li")).toHaveLength(2)
  expect(checks.querySelector('li[data-exit="1"]')?.textContent).toContain("1 failed")
})

test("a change whose checks passed but could not land still says why", async () => {
  // A check changed the prepared copy: every command passed,
  // and "2 checks passed" beside "Not applied" would be a riddle.
  const moved: RunSummary = {
    ...run,
    status: "asking",
    change: { base: "a1", head: "b2", files: ["src/x.py"], insertions: 3, deletions: 1, message: "fixed x" },
    application: {
      status: "blocked",
      verification_changed: ["src/x.py"],
      checks: [
        { command: "ruff check .", exit_code: 0, output: "" },
        { command: "pytest -q", exit_code: 0, output: "3 passed" },
      ],
    },
  }
  await draw([moved], { into: "main" })
  expect(container.querySelector(".run-checks > summary")?.textContent).toBe(
    "A check changed src/x.py. Check commands must leave these files unchanged.",
  )
  expect(container.querySelectorAll(".run-checks li")).toHaveLength(2)
})

test("a repair the task tried is said beside the checks", async () => {
  const repaired: RunSummary = {
    ...run,
    change: { base: "a1", head: "b2", files: ["src/x.py"], insertions: 3, deletions: 1, message: "fixed x" },
    application: {
      status: "applied",
      accepted: 1,
      checks: [{ command: "pytest -q", exit_code: 0, output: "" }],
      repair: { ready: true, run_id: "r9", reason: "" },
    },
  }
  await draw([repaired], { into: "main" })
  expect(container.querySelector(".run-repair")?.textContent).toBe("repaired first, by run r9")
})

test("a repair that could not finish says why beside the checks", async () => {
  const unrepaired: RunSummary = {
    ...run,
    status: "asking",
    change: { base: "a1", head: "b2", files: ["src/x.py"], insertions: 3, deletions: 1, message: "fixed x" },
    application: {
      status: "blocked",
      error: "verification failed",
      checks: [{ command: "pytest -q", exit_code: 1, output: "1 failed" }],
      repair: { ready: false, run_id: "r9", reason: "The repair exceeded its 120-second time limit." },
    },
  }
  await draw([unrepaired], { into: "main" })
  expect(container.querySelector(".run-repair")?.textContent).toBe(
    "a repair (run r9) could not finish: The repair exceeded its 120-second time limit.",
  )
})

test("an unfinished check keeps its partial output without claiming it never ran", async () => {
  await draw([{ ...run, application: {
    status: "blocked", checks: [{ command: "pytest -q", exit_code: null, output: "started checking" }],
  } }], { into: "main" })
  expect(container.querySelector(".run-checks > summary")?.textContent).toBe("pytest -q did not finish")
  expect(container.querySelector('.run-checks li[data-exit="none"]')?.textContent).toContain("could not finish")
  expect(container.querySelector('.run-checks li[data-exit="none"]')?.textContent).toContain("started checking")
})

test("a repair refused before starting keeps its reason without inventing a run", async () => {
  await draw([{ ...run, application: {
    status: "blocked", repair: { ready: false, reason: "No repair worker is available." },
  } }], { into: "main" })
  expect(container.querySelector(".run-repair")?.textContent).toBe(
    "a repair could not finish: No repair worker is available.",
  )
})

test("a checked change still waiting for a decision says both", async () => {
  const checked: RunSummary = {
    ...run,
    change: { base: "a1", head: "b2", files: ["src/x.py"], insertions: 3, deletions: 1, message: "fixed x" },
    application: { status: "review", checked_on: "a1", checks: [{ command: "pytest -q", exit_code: 0, output: "" }] },
  }
  await draw([checked], { into: "main", pending: 1 })
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain("Checked, waiting for review")
})

test("a held task leads with that, and says why in the daemon's words", async () => {
  const why = "paused because its change conflicts with the project in src/app.py; retry or keep it paused from the board"
  await draw([run], { status: "paused", heldBecause: why })
  expect(container.querySelector(".drawer-state")?.textContent).toBe("Paused")
  expect(container.querySelector(".drawer-state")?.getAttribute("data-state")).toBe("held")
  expect(container.querySelector(".drawer-held")?.textContent).toBe(why)

  // A pause the reader pressed is still a hold, and still says so.
  await draw([run], { status: "paused", heldBecause: "paused from the board" })
  expect(container.querySelector(".drawer-held")?.textContent).toBe("paused from the board")

  // Nothing to say, nothing drawn.
  await draw([run], { status: "waiting", heldBecause: null })
  expect(container.querySelector(".drawer-held")).toBeNull()
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
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain(
    `Stopped ${shortTime(run.finished_at)}`,
  )
})

test("a quiet run keeps its outcome in the brief instead of duplicate machinery", async () => {
  await draw([run], { into: "main" })

  expect(container.querySelector(".diff-note")).toBeNull()
  expect(container.querySelector(".drawer-summary")).toBeNull()
  expect(container.querySelector(".run-brief-meta")?.textContent).toContain(
    `Finished ${shortTime(run.finished_at)}`,
  )
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

test("each tool leads with its agent-written purpose and folds the raw record", async () => {
  const purpose = "Check whether PR #343 is ready to merge."
  await show([
    event("node_tool_call", {
      data: {
        name: "run_command",
        purpose,
        arguments: JSON.stringify({
          command: "gh pr view 343",
          purpose: "native tool option",
        }),
        result: "exit code: 0\nstate: OPEN",
        error: false,
        duration_ms: 1100,
      },
    }),
  ])

  const details = container.querySelector<HTMLDetailsElement>(".drawer-tool")!
  expect(details.open).toBe(false)
  const summary = details.querySelector("summary")!
  expect(summary.textContent).toContain(purpose)
  expect(summary.textContent).toContain("run_command · completed · 1.1s")
  expect(summary.hasAttribute("aria-label")).toBe(false)
  expect(details.querySelector(".drawer-tool-raw")?.textContent).toContain("run_command")
  expect(details.querySelector(".drawer-tool-raw")?.textContent).toContain("gh pr view 343")
  expect(details.querySelector(".drawer-tool-raw")?.textContent).toContain("native tool option")
  expect(details.querySelector(".drawer-tool-raw")?.textContent).toContain("state: OPEN")
})

test("an older command gets an honest purpose from the command it recorded", async () => {
  await show([
    event("node_tool_call", {
      data: {
        name: "run_command",
        arguments: JSON.stringify({ command: "gh pr diff 343 --patch" }),
        result: "exit code: 0",
        error: false,
      },
    }),
  ])

  expect(container.querySelector(".drawer-tool summary")?.textContent).toContain(
    "Review the changes in PR #343",
  )
})

test("older shell records describe common reads, searches, checks, and revision work", async () => {
  const examples = [
    ["cat AGENTS.md", "Read AGENTS.md"],
    ['grep -rn "confirm" src/poieo --include=*.py', "Search the project for “confirm”"],
    ["sed -n '60,180p' src/poieo/viewer.py", "Read src/poieo/viewer.py"],
    ["ls docs", "Look through docs"],
    ["sed -i 's/old/new/' docs/web.md", "Update docs/web.md with sed"],
    ["sed -i.bak 's/old/new/' docs/web.md", "Update docs/web.md with sed"],
    ["git checkout -- docs/web.md", "Restore docs/web.md from Git"],
    ["git checkout HEAD -- docs/web.md", "Restore docs/web.md from Git"],
    ["git checkout --ours docs/web.md", "Restore docs/web.md from Git"],
    ["git checkout -p docs/web.md", "Restore docs/web.md from Git"],
    ["git checkout -2 docs/web.md", "Restore docs/web.md from Git"],
    ["git checkout topic && echo -- later", "Switch to topic"],
    ["git checkout -b topic main", "Run a Git checkout command for this task"],
    ["git checkout -q --detach origin/pr-358", "Switch to origin/pr-358"],
    ["git show origin/pr-358 --stat", "Inspect origin/pr-358"],
    [
      "git rev-parse HEAD; git merge-base --is-ancestor main HEAD",
      "Check whether the candidate includes its base",
    ],
    ['python -c "print(1)"', "Run a Python command for this task"],
    ["@'\n## Independent review", "Prepare the independent review"],
  ]
  await show(
    examples.map(([command]) =>
      event("node_tool_call", {
        data: {
          name: "run_command",
          arguments: JSON.stringify({ command }),
          result: "exit code: 0",
          error: false,
        },
      }),
    ),
  )

  const summaries = Array.from(container.querySelectorAll(".drawer-tool summary"))
  expect(summaries.map((summary) => summary.textContent)).toEqual(
    examples.map(([, purpose]) => `${purpose}run_command · completed`),
  )
})

test("a tool turn's preamble does not duplicate the purpose entries below it", async () => {
  await show([
    event("node_turn", {
      node_id: "work",
      data: { turn: 1, text: "I will inspect both files first.", tool_call_count: 2 },
    }),
    event("node_tool_call", {
      node_id: "work",
      data: {
        turn: 1,
        name: "read_file",
        purpose: "Read the design contract.",
        arguments: "DESIGN.md",
      },
    }),
    event("node_tool_call", {
      node_id: "work",
      data: {
        turn: 1,
        name: "read_file",
        purpose: "Read the web guide.",
        arguments: "docs/web.md",
      },
    }),
  ])

  expect(container.querySelectorAll('[data-kind="turn"]')).toHaveLength(0)
  expect(container.querySelectorAll(".drawer-tool")).toHaveLength(2)
})

test("a tool preamble remains when its promised activity records are incomplete", async () => {
  await show([
    event("node_turn", {
      node_id: "work",
      data: { turn: 1, text: "I will inspect both files first.", tool_call_count: 2 },
    }),
    event("node_tool_call", {
      node_id: "work",
      data: {
        turn: 1,
        name: "read_file",
        purpose: "Read the design contract.",
        arguments: "DESIGN.md",
      },
    }),
  ])

  expect(container.querySelector('[data-kind="turn"]')?.textContent).toContain(
    "I will inspect both files first.",
  )
  expect(container.querySelectorAll(".drawer-tool")).toHaveLength(1)
})

test("a missing tool-only record leaves an explicit gap in the activity", async () => {
  await show([
    event("node_turn", {
      node_id: "work",
      data: { turn: 1, text: "", thinking: "", tool_call_count: 2 },
    }),
  ])

  expect(container.querySelector('[data-kind="stuck"]')?.textContent).toContain(
    "2 tool calls were not fully recorded",
  )
})

test("a partial tool-only record reports only the calls that are missing", async () => {
  await show([
    event("node_turn", {
      node_id: "work",
      data: { turn: 1, text: "", thinking: "", tool_call_count: 2 },
    }),
    event("node_tool_call", {
      node_id: "work",
      data: {
        turn: 1,
        name: "read_file",
        purpose: "Read the design contract.",
        arguments: "DESIGN.md",
      },
    }),
  ])

  expect(container.querySelector('[data-kind="stuck"]')?.textContent).toContain(
    "1 tool call was not fully recorded",
  )
  expect(container.querySelectorAll(".drawer-tool")).toHaveLength(1)
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

test("expanded tool evidence shares the drawer scroll instead of nesting another one", async () => {
  const rule = DRAWER_CSS.match(/\.drawer-tool-part pre\s*\{([^}]*)\}/s)?.[1] ?? ""
  expect(rule).not.toMatch(/max-height\s*:/)
  expect(rule).not.toMatch(/overflow\s*:\s*auto/)
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

test("the selected run says what it started with, what it says, and what shaped the answer", async () => {
  const onMemory = vi.fn()
  fetchRunMemory.mockResolvedValue({
    run_id: "r1",
    task: "chores",
    shown: [
      { slug: "batch-cap", used: false, preview: "The api rejects batches over 50." },
      { slug: "windows-shell", used: true, preview: "Windows tests need a POSIX shell." },
      { slug: "long-gone", used: null, preview: null },
    ],
  })
  await draw([run], { onMemory })

  expect(fetchRunMemory).toHaveBeenCalledWith("r1")
  // Inside the run's own box, under its time line: a list floating below
  // the brief read as a fact about the task rather than about this run.
  const shown = container.querySelector<HTMLDetailsElement>(".run-brief .run-memory")!
  expect(shown).not.toBeNull()
  expect(shown.tagName).toBe("DETAILS")
  expect(shown.open).toBe(false)
  // One plain sentence is the whole first screen; the rows are a click away.
  expect(shown.querySelector(".run-memory-lead")?.textContent).toBe(
    "This run started with 3 memories; 1 shaped the answer.",
  )
  // The one that mattered comes first, and every row says what it says
  // and what became of it.
  const rows = Array.from(shown.querySelectorAll("li"))
  expect(rows.map((row) => row.getAttribute("data-used"))).toEqual(["true", "false", "unknown"])
  expect(rows[0].textContent).toContain("windows-shell")
  expect(rows[0].textContent).toContain("Windows tests need a POSIX shell.")
  expect(rows[0].textContent).toContain("shaped the answer")
  expect(rows[1].textContent).toContain("The api rejects batches over 50.")
  expect(rows[1].textContent).toContain("seen, not used")
  expect(rows[2].textContent).toContain("no longer in memory")

  await press('[data-memory="windows-shell"]')
  expect(onMemory).toHaveBeenCalledWith("windows-shell")
})

test("a run that used none of its memory says so in the sentence", async () => {
  fetchRunMemory.mockResolvedValue({
    run_id: "r1",
    task: "chores",
    shown: [{ slug: "batch-cap", used: false, preview: "The api rejects batches over 50." }],
  })
  await draw([run])

  expect(container.querySelector(".run-memory-lead")?.textContent).toBe(
    "This run started with 1 memory; none shaped the answer.",
  )
})

test("a run recorded while the project kept no memory shows no memory section", async () => {
  fetchRunMemory.mockResolvedValue({ run_id: "r1", task: "chores", shown: null })
  await draw([run])

  expect(container.querySelector(".run-memory")).toBeNull()
})

test("a run memory chose nothing for says so rather than vanishing", async () => {
  fetchRunMemory.mockResolvedValue({ run_id: "r1", task: "chores", shown: [] })
  await draw([run])

  // Nothing to unfold, so it is a sentence and not a closed triangle.
  const lead = container.querySelector(".run-brief .run-memory-lead")!
  expect(lead.textContent).toBe("This run started with nothing from memory.")
  expect(lead.closest("details")).toBeNull()
})

test("a run named on arrival is selected even when it left the short history", async () => {
  const old: RunSummary = {
    ...run,
    run_id: "20260801T010000-old",
    started_at: "2026-08-01T01:00:00Z",
    finished_at: "2026-08-01T01:00:04Z",
    said: "an account from weeks ago",
  }
  fetchRunSummary.mockResolvedValue(old)
  await draw([run], { runId: "20260801T010000-old" })

  expect(fetchRunSummary).toHaveBeenCalledWith("20260801T010000-old")
  expect(container.querySelector(".run-brief")?.getAttribute("data-run")).toBe("20260801T010000-old")
  expect(container.querySelector(".run-brief h3")?.textContent).toBe("Selected run")
  expect(container.querySelector(".run-brief-what")?.textContent).toContain("an account from weeks ago")
})

test("the selected run says what its prompt was made of, each part against its budget", async () => {
  fetchRunMemory.mockResolvedValue({
    run_id: "r1",
    task: "chores",
    shown: [],
    prompt: {
      page: { chars: 205, budget: 12_000 },
      memory: { chars: 3_600, budget: 4_000 },
      journal: { chars: 11 },
    },
  })
  await draw([run])

  const makeup = container.querySelector<HTMLElement>(".run-brief .run-prompt")!
  expect(makeup).not.toBeNull()
  const page = makeup.querySelector<HTMLElement>('[data-gauge="page"]')!
  expect(page.textContent).toContain("205 / 12k chars")
  const memory = makeup.querySelector<HTMLElement>('[data-gauge="memory"]')!
  expect(memory.dataset.level).toBe("near")
  expect(memory.textContent).toContain("3,600 / 4,000 chars")
  // The journal has a size and no budget, so no bar.
  const journal = makeup.querySelector<HTMLElement>('[data-gauge="journal"]')!
  expect(journal.dataset.level).toBe("unbounded")
  expect(journal.textContent).toContain("11 chars")
})

test("a record written before runs measured their prompt draws no make-up", async () => {
  fetchRunMemory.mockResolvedValue({ run_id: "r1", task: "chores", shown: [], prompt: null })
  await draw([run])

  expect(container.querySelector(".run-prompt")).toBeNull()
})

test("a turn that knows its window puts its input against it", async () => {
  await show([
    event("node_turn", {
      data: { turn: 8, text: "thinking about it", input_tokens: 170_000, output_tokens: 3_120, window: 200_000 },
    }),
  ])

  const entry = container.querySelector('[data-kind="turn"]')!
  const gauge = entry.querySelector<HTMLElement>('[data-gauge="context"]')!
  expect(gauge.dataset.level).toBe("near")
  expect(gauge.textContent).toContain("170k / 200k tokens")
  expect(entry.textContent).toContain("3,120 out")
})

test("a turn whose window nobody could say keeps the plain count", async () => {
  await show([
    event("node_turn", {
      data: { turn: 8, text: "thinking about it", input_tokens: 84_210, output_tokens: 3_120, window: null },
    }),
  ])

  const entry = container.querySelector('[data-kind="turn"]')!
  expect(entry.querySelector('[data-gauge="context"]')).toBeNull()
  expect(entry.textContent).toContain("84,210 in")
})

test("a part the record did not measure is left out rather than drawn empty", async () => {
  fetchRunMemory.mockResolvedValue({
    run_id: "r1",
    task: "chores",
    shown: [],
    prompt: {
      page: { chars: 205, budget: 12_000 },
      memory: { chars: null, budget: 4_000 },
      journal: { chars: null },
    },
  })
  await draw([run])

  const makeup = container.querySelector<HTMLElement>(".run-prompt")!
  expect(makeup.querySelector('[data-gauge="page"]')).not.toBeNull()
  expect(makeup.querySelector('[data-gauge="memory"]')).toBeNull()
  expect(makeup.querySelector('[data-gauge="journal"]')).toBeNull()
})

test("a run in flight is followed from the stage, opens by itself, and folds its tool calls with the newest group open", async () => {
  const live: PoieoEvent[] = [
    event("run_started", { data: { task: "chores", project: "board" } }),
    event("node_started", { node_id: "work", data: { step: 1 } }),
    // The model reaches for two tools, then speaks: a turn that only called
    // tools is told by its calls, and the words come on the next turn.
    event("node_turn", { node_id: "work", data: { turn: 1, text: "", tool_call_count: 2 } }),
    event("node_tool_call", {
      node_id: "work",
      data: { turn: 1, name: "read_file", purpose: "Read the notes", arguments: { path: "notes.md" }, result: "- sweep", error: false },
    }),
    event("node_tool_call", {
      node_id: "work",
      data: { turn: 1, name: "run_command", purpose: "Run the tests", arguments: { command: "pytest" }, result: "ok", error: false },
    }),
    event("node_turn", { node_id: "work", data: { turn: 2, text: "Both fine.", tool_call_count: 0 } }),
  ]
  // The run in flight has no summary yet: the list holds only the run before
  // it, and that is not the run to follow.
  const before = { ...run, run_id: "r0", status: "failed" }
  await draw([before], { status: "running", liveActivity: live, liveRunId: "r1" })

  // Followed, not fetched, and open without a press. The brief and the
  // attention line speak of this run, not of the failed one before it.
  expect(fetchRunEvents).not.toHaveBeenCalled()
  expect(container.querySelector('[data-do="toggle-activity"]')!.getAttribute("aria-expanded")).toBe("true")
  expect(container.querySelector(".run-brief h3")!.textContent).toBe("Run in flight")
  expect(container.querySelector(".drawer-state")!.textContent).toBe("Running now")
  expect(container.textContent).not.toContain("Latest run failed")
  const group = container.querySelector<HTMLDetailsElement>(".drawer-group")!
  expect(group).not.toBeNull()
  expect(group.open).toBe(true)
  expect(group.querySelector("summary")!.textContent).toContain("2 tool calls")
  expect(group.querySelector("summary")!.textContent).toContain("Read the notes")
  expect(group.querySelectorAll(".drawer-tool")).toHaveLength(2)
  expect(container.textContent).toContain("Both fine.")
})

test("a single tool call between turns stays its own line, and the newest run's activity is the stage's even after it has finished", async () => {
  const live: PoieoEvent[] = [
    event("run_started", { data: { task: "chores", project: "board" } }),
    event("node_turn", { node_id: "work", data: { turn: 1, text: "", tool_call_count: 1 } }),
    event("node_tool_call", {
      node_id: "work",
      data: { turn: 1, name: "read_file", purpose: "Read the notes", arguments: { path: "notes.md" }, result: "", error: false },
    }),
    event("node_turn", { node_id: "work", data: { turn: 2, text: "Done.", tool_call_count: 0 } }),
    event("run_finished"),
  ]
  await draw([run], { status: "waiting", liveActivity: live, liveRunId: "r1" })
  await press('[data-do="toggle-activity"]')

  expect(fetchRunEvents).not.toHaveBeenCalled()
  expect(container.querySelector(".drawer-group")).toBeNull()
  expect(container.querySelectorAll(".drawer-tool")).toHaveLength(1)
  expect(container.textContent).toContain("Done.")
})

test("an older run picked from history is still fetched while another runs", async () => {
  const before = { ...run, run_id: "r0", status: "failed" }
  const older = { ...run, run_id: "r-old", status: "completed" }
  fetchRunEvents.mockResolvedValue([event("node_turn", { run_id: "r-old", node_id: "work", data: { turn: 1, text: "Long ago." } })])
  await draw([before, older], { status: "running", liveActivity: [event("run_started")], liveRunId: "r1" })

  await press('[data-do="toggle-runs"]')
  await press('[data-run="r-old"] .run-open')
  await press('[data-do="toggle-activity"]')

  expect(fetchRunEvents).toHaveBeenCalledWith("r-old")
  expect(container.textContent).toContain("Long ago.")
})

test("following survives the run's finish: the timeline stays, open, until its summary lands and after", async () => {
  const before = { ...run, run_id: "r0", status: "failed" }
  const live: PoieoEvent[] = [
    event("run_started", { data: { task: "chores", project: "board" } }),
    event("node_turn", { node_id: "work", data: { turn: 1, text: "Sweeping.", tool_call_count: 0 } }),
  ]
  await draw([before], { status: "running", liveActivity: live, liveRunId: "r1" })
  expect(container.textContent).toContain("Sweeping.")

  // The run ends: status leaves running before the index row exists.
  const finished = [...live, event("run_finished")]
  await draw([before], { status: "waiting", liveActivity: finished, liveRunId: "r1" })
  expect(container.querySelector('[data-do="toggle-activity"]')!.getAttribute("aria-expanded")).toBe("true")
  expect(container.textContent).toContain("Sweeping.")
  expect(container.textContent).not.toContain("No activity was recorded")

  // Then the summary lands: still the same run, still open, still not fetched.
  const landed = { ...run, run_id: "r1", status: "completed", said: "Swept." }
  await draw([before], { status: "waiting", liveActivity: finished, liveRunId: "r1", liveRuns: [landed, before] })
  expect(container.querySelector('[data-do="toggle-activity"]')!.getAttribute("aria-expanded")).toBe("true")
  expect(container.textContent).toContain("Sweeping.")
  expect(container.querySelector(".run-brief h3")!.textContent).toBe("Latest run")
  expect(fetchRunEvents).not.toHaveBeenCalled()
})
