import { expect, test } from "vitest"

import { basic } from "./basic"
import { DEFAULT_SKIN_ID, SKINS, skinById } from "./registry"
import { AGENT_RUN } from "../state/fixtures"
import { initialStage, replay } from "../state/stage"
import type { TaskRow } from "../types"

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
    then: [{ to: "revision", label: "changed" }],
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
    shape: {
      entry: "draft",
      nodes: [{ id: "draft", type: "agent", next: null, default: null, branches: [], model: null, tools: [] }],
    },
  },
]

const midRun = () => replay(initialStage(FLOWS), AGENT_RUN.slice(0, 4))

test("every registered skin satisfies the contract", () => {
  expect(SKINS.length).toBeGreaterThan(0)
  for (const skin of SKINS) {
    expect(typeof skin.id).toBe("string")
    expect(typeof skin.label).toBe("string")
    expect(typeof skin.mount).toBe("function")
  }
  const ids = SKINS.map((skin) => skin.id)
  expect(new Set(ids).size).toBe(ids.length)
})

test("the graph is what opens by default", () => {
  // The reader arrives asking what the project does and where it is, and the
  // graph is the skin that answers that. It is also the fallback, so a reader
  // with nothing stored and one with something unreadable stored see the same
  // page rather than two different ones.
  expect(DEFAULT_SKIN_ID).toBe("basic")
  expect(skinById(null).id).toBe(DEFAULT_SKIN_ID)
})

test("skinById falls back to basic for an unknown id", () => {
  // A stale localStorage value must not blank the page.
  expect(skinById("kitchen").id).toBe("basic")
  expect(skinById(null).id).toBe("basic")
  expect(skinById("basic").id).toBe("basic")
})

test("mount/update/destroy leaves the element empty", () => {
  const el = document.createElement("div")
  const handle = basic.mount(el, { onSelectTask: () => {} })
  handle.update(midRun())
  expect(el.childElementCount).toBeGreaterThan(0)

  handle.destroy()
  expect(el.childElementCount).toBe(0)
})

test("basic renders one box per task and reflects status", () => {
  const el = document.createElement("div")
  const handle = basic.mount(el, { onSelectTask: () => {} })
  handle.update(midRun())

  expect(el.querySelectorAll("[data-task]")).toHaveLength(2)
  expect(el.querySelector('[data-task="board/chores"]')!.getAttribute("data-status")).toBe("running")
  expect(el.querySelector('[data-task="board/revision"]')!.getAttribute("data-status")).toBe("waiting")
  // A running task opens itself, so the node it is on is visible without
  // anyone having asked -- detail where something is happening, and only there.
  expect(el.querySelector('[data-task="board/chores"]')!.textContent).toContain("work")

  handle.destroy()
})

test("the latest thinking and tool call surface on an open task", () => {
  const el = document.createElement("div")
  const handle = basic.mount(el, { onSelectTask: () => {} })
  handle.update(replay(initialStage(FLOWS), AGENT_RUN))

  const card = el.querySelector('[data-task="board/chores"]')!
  expect(card.textContent).toContain("list_dir")
  handle.destroy()
})

test("clicking a task's name selects it; the chevron is for opening", () => {
  const el = document.createElement("div")
  const picked: string[] = []
  const handle = basic.mount(el, { onSelectTask: (task) => picked.push(task) })
  handle.update(midRun())

  el.querySelector<HTMLElement>('[data-task="board/revision"] .basic-pick')!.click()
  expect(picked).toEqual(["board/revision"])

  handle.destroy()
})

test("no skin imports three.js statically", () => {
  // A static import folds three.js back into the entry chunk without a word of
  // warning; only `await import("three")` keeps it in its own file.
  const sources = import.meta.glob("./**/*.{ts,tsx}", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>

  const offenders = Object.entries(sources)
    // Tests are never bundled, and checking the swing against the real three.js
    // maths is worth more than a rule they cannot break.
    .filter(([path]) => !path.endsWith(".test.ts"))
    .filter(([, source]) => /^\s*import[^\n]*["']three["']/m.test(source))
    .map(([path]) => path)

  expect(offenders).toEqual([])
})


