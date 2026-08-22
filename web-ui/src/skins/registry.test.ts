import { expect, test } from "vitest"

import { ledger } from "./ledger"
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

test("skinById falls back to ledger for an unknown id", () => {
  // A stale localStorage value must not blank the page.
  expect(skinById("kitchen").id).toBe("ledger")
  expect(skinById(null).id).toBe("ledger")
  expect(skinById("ledger").id).toBe("ledger")
})

test("mount/update/destroy leaves the element empty", () => {
  const el = document.createElement("div")
  const handle = ledger.mount(el, { onSelectWorker: () => {} })
  handle.update(midRun())
  expect(el.childElementCount).toBeGreaterThan(0)

  handle.destroy()
  expect(el.childElementCount).toBe(0)
})

test("ledger renders one card per worker and reflects status", () => {
  const el = document.createElement("div")
  const handle = ledger.mount(el, { onSelectWorker: () => {} })
  handle.update(midRun())

  const cards = el.querySelectorAll("[data-flow]")
  expect(cards).toHaveLength(2)
  expect(el.querySelector('[data-flow="chores"]')!.getAttribute("data-status")).toBe("running")
  expect(el.querySelector('[data-flow="revision"]')!.getAttribute("data-status")).toBe("waiting")
  // the node the agent is on shows up somewhere on its card
  expect(el.querySelector('[data-flow="chores"]')!.textContent).toContain("work")

  handle.destroy()
})

test("the latest thinking and tool call surface on the card", () => {
  const el = document.createElement("div")
  const handle = ledger.mount(el, { onSelectWorker: () => {} })
  handle.update(replay(initialStage(FLOWS), AGENT_RUN))

  const card = el.querySelector('[data-flow="chores"]')!
  expect(card.textContent).toContain("list_dir")
  handle.destroy()
})

test("clicking a card selects that worker", () => {
  const el = document.createElement("div")
  const picked: string[] = []
  const handle = ledger.mount(el, { onSelectWorker: (flow) => picked.push(flow) })
  handle.update(midRun())

  el.querySelector<HTMLElement>('[data-flow="revision"]')!.click()
  expect(picked).toEqual(["revision"])

  handle.destroy()
})

test("no skin imports pixi.js statically", () => {
  // A static import folds PixiJS back into the entry chunk without a word of
  // warning; only `await import("pixi.js")` keeps it in its own file.
  const sources = import.meta.glob("./**/*.{ts,tsx}", {
    query: "?raw",
    import: "default",
    eager: true,
  }) as Record<string, string>

  const offenders = Object.entries(sources)
    .filter(([, source]) => /^\s*import[^\n]*["']pixi\.js["']/m.test(source))
    .map(([path]) => path)

  expect(offenders).toEqual([])
})
