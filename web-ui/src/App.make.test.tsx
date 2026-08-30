/**
 * The rail's third item, and the panel it opens.
 *
 * Making a task is what the page is *for* rather than what one task is doing,
 * which is the rail's own rule -- so it lands beside `models` and not on the
 * bar. What these defend is that one thing is open at a time: the stage
 * reserves a single margin, and two panels in it is a bug you only see on a
 * narrow window.
 */

import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const fetchModels = vi.hoisted(() => vi.fn(async () => null))
const fetchRuns = vi.hoisted(() => vi.fn(async () => []))
const fetchRunEvents = vi.hoisted(() => vi.fn(async () => []))
// The models panel's second read, for engines this project cannot reach. A
// test that opens that panel has to stand in for it too, or it reaches jsdom's
// fetch with a relative URL and lands as an unhandled rejection.
const fetchUndeclared = vi.hoisted(() => vi.fn(async () => []))
vi.mock("./api", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  fetchModels,
  fetchRuns,
  fetchRunEvents,
  fetchUndeclared,
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

function api(): StageApi {
  return {
    fetchTasks: vi.fn(async () => ({
      projects: [{ name: "night shift", root: "/home/k/a" }],
      tasks: [row("chores", "night shift")],
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

async function open() {
  await act(async () => {
    root.render(<App store={createStageStore(api())} />)
  })
  await act(async () => {})
  await act(async () => {})
}

const button = (name: string) => container.querySelector<HTMLElement>(`[data-do="${name}"]`)
const panel = (label: string) => container.querySelector(`[aria-label="${label}"]`)

test("the rail offers making one, beside looking at things", async () => {
  await open()
  const railed = [...container.querySelectorAll(".shell-rail button")].map((b) => b.textContent)
  expect(railed).toEqual(["board", "hours", "models", "new task"])
})

test("it opens the form for the project on screen", async () => {
  await open()
  await act(async () => button("open-make")!.click())

  expect(panel("New task")).not.toBeNull()
})

test("only one panel holds the margin", async () => {
  await open()
  await act(async () => button("open-models")!.click())
  expect(panel("Models")).not.toBeNull()

  await act(async () => button("open-make")!.click())

  // The stage reserves one margin. Two panels in it is a bug that only shows
  // on a narrow window, so it is defended here rather than looked for.
  expect(panel("Models")).toBeNull()
  expect(panel("New task")).not.toBeNull()
})

test("the board is where you land back", async () => {
  await open()
  await act(async () => button("open-make")!.click())
  await act(async () => button("open-board")!.click())

  expect(panel("New task")).toBeNull()
})

test("picking a task on the board takes the margin back", async () => {
  await open()
  await act(async () => button("open-make")!.click())
  expect(panel("New task")).not.toBeNull()

  await act(async () => {
    container
      .querySelector<HTMLElement>('[data-task="night shift/chores"] .basic-pick')!
      .click()
  })

  // The third way into the one margin the stage reserves, and the one the
  // rail cannot defend on its own: a task picked on the board opens the
  // drawer, so whatever was holding the margin has to let go of it.
  expect(panel("New task")).toBeNull()
  expect(container.querySelector(".drawer")).not.toBeNull()
})
