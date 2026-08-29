/**
 * The bar's models button, over the real store.
 *
 * The panel is about a project rather than a task, which is the whole reason
 * it hangs off the bar -- so what these defend is that it asks about the
 * project actually on screen, and that it does not fight the drawer for the
 * one margin the stage reserves.
 */

import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const fetchModels = vi.hoisted(() => vi.fn())
// The drawer reads the API directly rather than through the store, so a test
// that opens one has to stand in for its reads too -- otherwise they reach
// jsdom's fetch with a relative URL and land as an unhandled rejection.
const fetchRuns = vi.hoisted(() => vi.fn(async () => []))
const fetchRunEvents = vi.hoisted(() => vi.fn(async () => []))
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchModels,
  fetchRuns,
  fetchRunEvents,
}))

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
  current_run_id: null,
  last_run: null,
  pending: 0,
  into: null,
  asking: null,
  then: [],
  shape: {
    entry: "work",
    nodes: [
      { id: "work", type: "agent", next: null, default: null, branches: [], model: null, tools: [] },
    ],
  },
})

const PROJECTS = [
  { name: "night shift", root: "/home/k/a" },
  { name: "day job", root: "/home/k/b" },
]

const REPORT = {
  binding: { name: "hybrid", path: "/home/k/a/models/default.yaml" },
  providers: { ollama: { type: "ollama", api_key_env: null, api_key_set: null } },
  default: "ollama/qwen3:32b",
  roles: {},
}

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
  fetchModels.mockReset()
  fetchModels.mockResolvedValue(REPORT)
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

async function open() {
  await act(async () => {
    root.render(<App store={createStageStore(api())} />)
  })
  await act(async () => {})
  await act(async () => {})
}

const button = (name: string) =>
  container.querySelector<HTMLElement>(`[data-do="${name}"]`)

test("the bar opens the panel for the project on screen", async () => {
  await open()

  await act(async () => button("open-models")!.click())

  expect(fetchModels).toHaveBeenCalledWith("night shift")
  expect(container.querySelector(".models")).not.toBeNull()
})

test("picking the other project asks about that one instead", async () => {
  await open()

  await act(async () => {
    const pick = container.querySelector<HTMLSelectElement>(".shell-project-pick")!
    pick.value = "day job"
    pick.dispatchEvent(new Event("change", { bubbles: true }))
  })
  await act(async () => button("open-models")!.click())

  expect(fetchModels).toHaveBeenCalledWith("day job")
})

test("opening the panel closes the drawer", async () => {
  await open()

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="night shift/chores"] .basic-pick')!.click()
  })
  expect(container.querySelector(".drawer")).not.toBeNull()

  await act(async () => button("open-models")!.click())

  // Both are fixed to the same edge at the same width, and the stage reserves
  // one margin. Two of them open is a panel nobody can read.
  expect(container.querySelector(".drawer")).toBeNull()
  expect(container.querySelector(".models")).not.toBeNull()
})

test("closing the panel puts the board back", async () => {
  await open()
  await act(async () => button("open-models")!.click())

  await act(async () => {
    container.querySelector<HTMLElement>(".models-close")!.click()
  })

  expect(container.querySelector(".models")).toBeNull()
})
