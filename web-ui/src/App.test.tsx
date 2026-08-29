import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

vi.mock("./api", () => ({
  fetchTasks: vi.fn(async () => []),
  fetchRuns: vi.fn(async () => [
    {
      run_id: "newest-but-quiet",
      task: "chores",
      graph: "agent-task",
      status: "completed",
      started_at: "2026-08-22T07:30:00+00:00",
      finished_at: "2026-08-22T07:30:01+00:00",
      steps: 1,
      iteration: 2,
      usage: {
        input_tokens: 0,
        output_tokens: 0,
        cache_read_tokens: 0,
        cache_write_tokens: 0,
      },
      error: null,
      said: "did the thing",
    },
    {
      run_id: "20260822T072819-98a6708d",
      task: "chores",
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
      said: "did the thing",
      change: {
        base: "aaa",
        head: "bbb",
        files: ["TODO.md"],
        insertions: 2,
        deletions: 0,
        message: "Added TODO.md",
      },
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
import { initialStage, reduce, replay } from "./state/stage"
import type { StageState } from "./state/stage"
import type { StageStore } from "./shell/stageStore"
import type { ProjectRow } from "./types"
import type { TaskRow } from "./types"

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
    then: [],
    shape: { entry: "", nodes: [] },
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
    then: [],
    shape: { entry: "", nodes: [] },
  },
]

function fakeStore(
  stage: StageState,
  project: ProjectRow | null = { name: "chores", root: "/home/k/chores" },
): StageStore & { push(next: StageState): void } {
  let current = stage
  // One array, not a fresh one per call: useSyncExternalStore compares
  // snapshots by identity and re-renders forever if they never match.
  const projectList = project ? [project] : []
  const listeners = new Set<() => void>()
  return {
    getStage: () => current,
    getFlows: () => FLOWS,
    getProjects: () => projectList,
    getStatus: () => "live",
    subscribe: (listener) => {
      listeners.add(listener)
      return () => listeners.delete(listener)
    },
    start: vi.fn(async () => {}),
    resync: vi.fn(async () => {}),
    stop: vi.fn(),
    push(next: StageState) {
      current = next
      for (const listener of listeners) listener()
    },
  }
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  localStorage.clear()
  // The shell is driven here by clicking a flowState on the board, so these ask
  // for the DOM skin explicitly. The default is the canvas one.
  localStorage.setItem("poieo.skin", "basic")
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

async function render(stage: StageState, project?: ProjectRow | null) {
  const store = fakeStore(stage, project === undefined ? undefined : project)
  await act(async () => {
    root.render(<App store={store} />)
  })
  return store
}

test("no tasks renders the invitation, not an error", async () => {
  await render(initialStage([]))
  expect(container.textContent).toContain("Nothing is running yet")
})

test("the picker lists the registered skins and the board carries the tasks", async () => {
  await render(initialStage(FLOWS))

  const picker = container.querySelector("select")!
  expect(Array.from(picker.options).map((o) => o.value).sort()).toEqual([
    "atelier",
    "basic",
  ])
  expect(picker.value).toBe("basic")
  expect(container.querySelectorAll("[data-task]")).toHaveLength(2)
})

test("a stale stored skin id still renders a board", async () => {
  localStorage.setItem("poieo.skin", "kitchen")
  await render(initialStage(FLOWS))

  // The registry falls back rather than blanking the page.
  expect(container.querySelector("select")!.value).toBe("basic")
  expect(container.querySelectorAll("[data-task]").length).toBeGreaterThan(0)
})

test("selecting a flowState opens the drawer, and reading it leaves the board alone", async () => {
  const stage = replay(initialStage(FLOWS), AGENT_RUN)
  const store = await render(stage)

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })

  const drawer = container.querySelector(".drawer")!
  expect(drawer).not.toBeNull()
  expect(drawer.getAttribute("data-task")).toBe("chores")
  // the drawer read a past run through its own scratch stage
  expect(drawer.textContent).toContain("list_dir")
  expect(store.getStage()).toBe(stage)
})

test("closing the drawer puts it away", async () => {
  await render(replay(initialStage(FLOWS), AGENT_RUN))

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })
  await act(async () => {
    container.querySelector<HTMLElement>('[aria-label="Close"]')!.click()
  })

  expect(container.querySelector(".drawer")).toBeNull()
})


test("opening a different flowState does not show the previous one's runs", async () => {
  // The drawer keeps a selected run. Without a fresh instance per
  // task, switching tasks leaves the last task's run in the diff pane.
  await render(replay(initialStage(FLOWS), AGENT_RUN))

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })
  expect(container.querySelector(".drawer")!.getAttribute("data-task")).toBe("chores")
  const first = container.querySelector("[data-run][data-selected='true']")

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/revision"] .basic-pick')!.click()
  })

  const drawer = container.querySelector(".drawer")!
  expect(drawer.getAttribute("data-task")).toBe("revision")
  // nothing carried over from the flowState we just left
  expect(container.querySelector("[data-run][data-selected='true']")).not.toBe(first)
})


test("a frame for another task leaves the open drawer alone", async () => {
  // A busy board streams frames while someone reads a drawer. Every entry in
  // the timeline formats its timestamp on render, so "the drawer did not
  // re-render" is observable as "no timestamp was formatted again".
  const stage = replay(initialStage(FLOWS), AGENT_RUN)
  const store = await render(stage)

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })
  expect(container.querySelectorAll(".drawer-entry").length).toBeGreaterThan(0)

  const formatted = vi.spyOn(Date.prototype, "toLocaleTimeString")
  await act(async () => {
    store.push(reduce(stage, { run_id: "rr", type: "run_started", data: { task: "revision" } }))
  })

  expect(formatted).not.toHaveBeenCalled()
  formatted.mockRestore()
})


test("the drawer opens on the run that changed something", async () => {
  // The newest run found nothing to do. Opening on it greets the reader with
  // "this run changed no files", which is not what they came for.
  await render(replay(initialStage(FLOWS), AGENT_RUN))

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })

  const selected = container.querySelector("[data-run][data-selected='true']")!
  expect(selected.getAttribute("data-run")).toBe("20260822T072819-98a6708d")
})


// -- whose board this is ------------------------------------------------------


test("the bar names the project, so two boards are not the same board", async () => {
  await render(initialStage([]), { name: "night shift", root: "/home/k/chores" })

  const named = container.querySelector(".shell-project")!
  expect(named.textContent).toBe("night shift")
  // Two worktrees of one repository are two projects with the same folder
  // name; the path is what tells them apart once the names collide.
  expect(named.getAttribute("title")).toBe("/home/k/chores")
})


test("the tab says it too, because that is what two open boards show", async () => {
  await render(initialStage([]), { name: "night shift", root: "/home/k/chores" })
  expect(document.title).toContain("night shift")
})


test("a board that has not heard yet says nothing rather than guessing", async () => {
  await render(initialStage([]), null)
  expect(container.querySelector(".shell-project")).toBeNull()
})
