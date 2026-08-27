import { expect, test } from "vitest"

import { basic } from "./basic"
import { DEFAULT_SKIN_ID, SKINS, skinById } from "./registry"
import { AGENT_RUN } from "../state/fixtures"
import { initialStage, replay } from "../state/stage"
import type { FlowRow } from "../types"

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
    then: [{ to: "revision", label: "changed" }],
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
    shape: {
      entry: "draft",
      nodes: [{ id: "draft", type: "llm", next: null, default: null, branches: [], model: null }],
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

test("the workshop is what opens by default", () => {
  expect(DEFAULT_SKIN_ID).toBe("atelier")
})

test("skinById falls back to basic for an unknown id", () => {
  // A stale localStorage value must not blank the page.
  expect(skinById("kitchen").id).toBe("basic")
  expect(skinById(null).id).toBe("basic")
  expect(skinById("basic").id).toBe("basic")
})

test("mount/update/destroy leaves the element empty", () => {
  const el = document.createElement("div")
  const handle = basic.mount(el, { onSelectWorker: () => {} })
  handle.update(midRun())
  expect(el.childElementCount).toBeGreaterThan(0)

  handle.destroy()
  expect(el.childElementCount).toBe(0)
})

test("basic renders one box per flow and reflects status", () => {
  const el = document.createElement("div")
  const handle = basic.mount(el, { onSelectWorker: () => {} })
  handle.update(midRun())

  expect(el.querySelectorAll("[data-flow]")).toHaveLength(2)
  expect(el.querySelector('[data-flow="chores"]')!.getAttribute("data-status")).toBe("running")
  expect(el.querySelector('[data-flow="revision"]')!.getAttribute("data-status")).toBe("waiting")
  // A running flow opens itself, so the node it is on is visible without
  // anyone having asked -- detail where something is happening, and only there.
  expect(el.querySelector('[data-flow="chores"]')!.textContent).toContain("work")

  handle.destroy()
})

test("the latest thinking and tool call surface on an open flow", () => {
  const el = document.createElement("div")
  const handle = basic.mount(el, { onSelectWorker: () => {} })
  handle.update(replay(initialStage(FLOWS), AGENT_RUN))

  const card = el.querySelector('[data-flow="chores"]')!
  expect(card.textContent).toContain("list_dir")
  handle.destroy()
})

test("clicking a flow's name selects it; the chevron is for opening", () => {
  const el = document.createElement("div")
  const picked: string[] = []
  const handle = basic.mount(el, { onSelectWorker: (flow) => picked.push(flow) })
  handle.update(midRun())

  el.querySelector<HTMLElement>('[data-flow="revision"] .basic-pick')!.click()
  expect(picked).toEqual(["revision"])

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


