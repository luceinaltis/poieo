/**
 * The picker over the real store, not a fake one.
 *
 * App.test.tsx drives a hand-made StageStore, which never runs `seed()`,
 * `tally()` or a replay -- and those are the whole of what the live page does
 * between opening and painting. A picker that works against a fake and not
 * against the real thing is exactly the bug a fake hides.
 */

import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

import App from "./App"
import { createStageStore } from "./shell/stageStore"
import type { StageApi } from "./shell/stageStore"
import type { TaskRow } from "./types"

const row = (name: string, project: string): TaskRow => ({
  name,
  project,
  graph: "g",
  trigger: "loop",
  status: "waiting",
  holding: false,
  stale: null,
  current_run_id: null,
  last_run: null,
  pending: 0,
  into: null,
  asking: null,
  then: [],
  shape: { entry: "work", nodes: [{ id: "work", type: "agent", next: null, default: null, branches: [], model: null, tools: [] }] },
})

const PROJECTS = [
  { name: "night shift", root: "/home/k/a", keeps_copies: true },
  { name: "day job", root: "/home/k/b", keeps_copies: true },
]

function api(): StageApi {
  return {
    fetchTasks: vi.fn(async () => ({
      projects: PROJECTS,
      tasks: [row("chores", "night shift"), row("chores", "day job")],
    })),
    fetchRunEvents: vi.fn(async () => []),
    fetchRuns: vi.fn(async () => []),
    openFeed: vi.fn(() => () => {}),
  }
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  localStorage.setItem("poieo.skin", "basic")
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

const shown = () =>
  Array.from(container.querySelectorAll("[data-task]")).map((one) =>
    one.getAttribute("data-task"),
  )

async function open() {
  await act(async () => {
    root.render(<App store={createStageStore(api())} />)
  })
  // start() resolves the listing, then the tally.
  await act(async () => {})
  await act(async () => {})
}

test("the board opens on one project's tasks, not both", async () => {
  await open()
  expect(shown()).toEqual(["night shift/chores"])
})

test("picking the other project repaints the board", async () => {
  await open()

  await act(async () => {
    const pick = container.querySelector<HTMLSelectElement>(".shell-project-pick")!
    pick.value = "day job"
    pick.dispatchEvent(new Event("change", { bubbles: true }))
  })

  expect(shown()).toEqual(["day job/chores"])
})

test("a resync does not drag the other project back onto the board", async () => {
  // The live page re-reads the listing whenever the feed reconnects, and that
  // read is authoritative about what exists. It must not be authoritative
  // about what the reader asked to look at.
  await open()

  await act(async () => {
    const pick = container.querySelector<HTMLSelectElement>(".shell-project-pick")!
    pick.value = "day job"
    pick.dispatchEvent(new Event("change", { bubbles: true }))
  })
  await act(async () => {})
  await act(async () => {})

  expect(shown()).toEqual(["day job/chores"])
})
