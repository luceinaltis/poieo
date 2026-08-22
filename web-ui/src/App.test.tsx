import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

vi.mock("./api", () => ({
  fetchFlows: vi.fn(async () => []),
  fetchRuns: vi.fn(async () => [
    {
      run_id: "20260822T072819-98a6708d",
      flow: "chores",
      graph: "agent-task",
      status: "completed",
      started_at: "2026-08-22T07:28:19.836+00:00",
      finished_at: "2026-08-22T07:28:19.845+00:00",
      steps: 1,
      iteration: 1,
      usage: {
        input_tokens: 0,
        output_tokens: 0,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
      },
      error: null,
    },
  ]),
  fetchRunEvents: vi.fn(async () => AGENT_RUN),
  fetchDiff: vi.fn(async () => ({ run_id: "20260822T072819-98a6708d", change: null })),
  accept: vi.fn(async () => ({ ok: true, accepted: 0 })),
  discard: vi.fn(async () => ({ ok: true, discarded: 0 })),
  openFeed: vi.fn(() => () => {}),
}))

import App from "./App"
import { AGENT_RUN } from "./state/fixtures"
import { initialStage, replay } from "./state/stage"
import type { StageState } from "./state/stage"
import type { StageStore } from "./shell/stageStore"
import type { FlowRow } from "./types"

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

function fakeStore(stage: StageState): StageStore {
  const listeners = new Set<() => void>()
  return {
    getStage: () => stage,
    getFlows: () => FLOWS,
    getStatus: () => "live",
    subscribe: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    start: vi.fn(async () => {}),
    resync: vi.fn(async () => {}),
    stop: vi.fn(),
  }
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

async function render(stage: StageState) {
  const store = fakeStore(stage)
  await act(async () => {
    root.render(<App store={store} />)
  })
  return store
}

test("no flows renders the invitation, not an error", async () => {
  await render(initialStage([]))
  expect(container.textContent).toContain("Nothing is running yet")
})

test("the picker lists the registered skins and the board carries the workers", async () => {
  await render(initialStage(FLOWS))

  const picker = container.querySelector("select")!
  expect(picker.options.length).toBeGreaterThan(0)
  expect(picker.value).toBe("ledger")
  expect(container.querySelectorAll("[data-flow]")).toHaveLength(2)
})

test("a stale stored skin id still renders a board", async () => {
  localStorage.setItem("poieo.skin", "kitchen")
  await render(initialStage(FLOWS))

  // The registry falls back rather than blanking the page.
  expect(container.querySelector("select")!.value).toBe("ledger")
  expect(container.querySelectorAll("[data-flow]").length).toBeGreaterThan(0)
})

test("selecting a worker opens the drawer, and reading it leaves the board alone", async () => {
  const stage = replay(initialStage(FLOWS), AGENT_RUN)
  const store = await render(stage)

  await act(async () => {
    container.querySelector<HTMLElement>('[data-flow="chores"]')!.click()
  })

  const drawer = container.querySelector(".drawer")!
  expect(drawer).not.toBeNull()
  expect(drawer.getAttribute("data-flow")).toBe("chores")
  // the drawer read a past run through its own scratch stage
  expect(drawer.textContent).toContain("list_dir")
  expect(store.getStage()).toBe(stage)
})

test("closing the drawer puts it away", async () => {
  await render(replay(initialStage(FLOWS), AGENT_RUN))

  await act(async () => {
    container.querySelector<HTMLElement>('[data-flow="chores"]')!.click()
  })
  await act(async () => {
    container.querySelector<HTMLElement>('[aria-label="Close"]')!.click()
  })

  expect(container.querySelector(".drawer")).toBeNull()
})


test("opening a different worker does not show the previous one's work", async () => {
  // The drawer keeps a selected piece of work. Without a fresh instance per
  // flow, switching workers leaves the last flow's run in the diff pane.
  await render(replay(initialStage(FLOWS), AGENT_RUN))

  await act(async () => {
    container.querySelector<HTMLElement>('[data-flow="chores"]')!.click()
  })
  expect(container.querySelector(".drawer")!.getAttribute("data-flow")).toBe("chores")
  const first = container.querySelector("[data-run][data-selected='true']")

  await act(async () => {
    container.querySelector<HTMLElement>('[data-flow="revision"]')!.click()
  })

  const drawer = container.querySelector(".drawer")!
  expect(drawer.getAttribute("data-flow")).toBe("revision")
  // nothing carried over from the worker we just left
  expect(container.querySelector("[data-run][data-selected='true']")).not.toBe(first)
})
