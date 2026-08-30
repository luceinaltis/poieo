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
  fetchModels: vi.fn(async () => ({
    binding: { name: "mock", path: "x.yaml" },
    roles: ["default"],
    endpoints: [],
  })),
  fetchUndeclared: vi.fn(async () => []),
}))

import App from "./App"
import { AGENT_RUN } from "./state/fixtures"
import { SKINS } from "./skins/registry"
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
    asking: null,
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
    asking: null,
    then: [],
    shape: { entry: "", nodes: [] },
  },
]

function fakeStore(
  stage: StageState,
  // Named for the project FLOWS' rows belong to: the board shows one
  // project's tasks, so a fake naming another would filter them all away.
  project: ProjectRow | ProjectRow[] | null = { name: "board", root: "/home/k/chores" },
): StageStore & { push(next: StageState): void } {
  let current = stage
  // One array, not a fresh one per call: useSyncExternalStore compares
  // snapshots by identity and re-renders forever if they never match.
  const projectList = project === null ? [] : [project].flat()
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

async function render(
  stage: StageState,
  project?: ProjectRow | ProjectRow[] | null,
) {
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

test("one rendering means no picker, and the board carries the tasks", async () => {
  await render(initialStage(FLOWS))

  // One rendering of the board exists, so there is no picker at all -- the
  // same furniture rule the project name follows: a control with one option
  // is not a control. If a second rendering ever lands in the registry, this
  // flips and the picker has to come back.
  const renderings = SKINS.filter((skin) => !skin.standalone)
  expect(renderings.map((skin) => skin.id)).toEqual(["basic"])
  expect(container.querySelector(".shell-skin")).toBeNull()
  expect(container.querySelectorAll("[data-task]")).toHaveLength(2)
})

test("hours is a place on the rail: there when you go, gone when you leave", async () => {
  await render(initialStage(FLOWS))

  // The rail carries it beside board, models and new task.
  const go = container.querySelector<HTMLElement>('[data-do="open-hours"]')!
  expect(go).not.toBeNull()
  await act(async () => go.click())

  // The stage now answers "what has it been doing" -- and the rendering
  // picker is gone, because it renders the *board*, which is not on screen.
  expect(container.querySelector(".hours")).not.toBeNull()
  expect(container.querySelector(".basic")).toBeNull()
  expect(go.getAttribute("aria-current")).toBe("page")
  expect(container.querySelector(".shell-skin")).toBeNull()

  // Board brings back the rendering that was left, not a hard-coded one.
  await act(async () => container.querySelector<HTMLElement>('[data-do="open-board"]')!.click())
  expect(container.querySelector(".basic")).not.toBeNull()
  expect(container.querySelector(".hours")).toBeNull()
  expect(
    container.querySelector('[data-do="open-board"]')!.getAttribute("aria-current"),
  ).toBe("page")
})

test("a panel opens over hours without knocking it off the stage", async () => {
  await render(initialStage(FLOWS))
  await act(async () => container.querySelector<HTMLElement>('[data-do="open-hours"]')!.click())

  await act(async () => container.querySelector<HTMLElement>('[data-do="open-models"]')!.click())

  // The panel holds the margin; the place behind it is still hours. One item
  // says where you are, and it is the panel's.
  expect(container.querySelector(".hours")).not.toBeNull()
  expect(container.querySelectorAll('[aria-current="page"]')).toHaveLength(1)
  expect(
    container.querySelector('[data-do="open-models"]')!.getAttribute("aria-current"),
  ).toBe("page")

  // Closing it lands back on hours, not on the board.
  await act(async () => container.querySelector<HTMLElement>('[data-do="open-hours"]')!.click())
  expect(
    container.querySelector('[data-do="open-hours"]')!.getAttribute("aria-current"),
  ).toBe("page")
})

test("a task picked off an hours lane opens the drawer with hours still on stage", async () => {
  await render(replay(initialStage(FLOWS), AGENT_RUN))
  await act(async () => container.querySelector<HTMLElement>('[data-do="open-hours"]')!.click())

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .hours-head')!.click()
  })

  expect(container.querySelector(".drawer")).not.toBeNull()
  expect(container.querySelector(".drawer")!.getAttribute("data-task")).toBe("chores")
  expect(container.querySelector(".hours")).not.toBeNull()
})

test("a reader who left on hours comes back to hours", async () => {
  localStorage.setItem("poieo.skin", "hours")
  await render(initialStage(FLOWS))

  expect(container.querySelector(".hours")).not.toBeNull()
  expect(
    container.querySelector('[data-do="open-hours"]')!.getAttribute("aria-current"),
  ).toBe("page")
})

test("a stale stored skin id still renders a board", async () => {
  // "atelier" is the id every reader who tried the workshop has stored.
  localStorage.setItem("poieo.skin", "atelier")
  await render(initialStage(FLOWS))

  // The registry falls back rather than blanking the page.
  expect(container.querySelector(".basic")).not.toBeNull()
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

// -- picking a project --------------------------------------------------------

const TWO: ProjectRow[] = [
  { name: "night shift", root: "/home/k/a" },
  { name: "day job", root: "/home/k/b" },
]

const MIXED: TaskRow[] = [
  { ...FLOWS[0], project: "night shift" },
  { ...FLOWS[1], project: "day job" },
]

const picker = () => container.querySelector<HTMLSelectElement>(".shell-project-pick")


test("one project is a name, not a thing to choose between", async () => {
  await render(initialStage(FLOWS), { name: "night shift", root: "/home/k/a" })

  expect(picker()).toBeNull()
  expect(container.querySelector(".shell-project")!.textContent).toBe("night shift")
})


test("several projects become a picker, and the board shows one of them", async () => {
  await render(initialStage(MIXED), TWO)

  expect(Array.from(picker()!.options).map((o) => o.value)).toEqual([
    "night shift",
    "day job",
  ])
  // The first, until asked otherwise -- and only its task.
  expect(picker()!.value).toBe("night shift")
  expect(container.querySelectorAll("[data-task]")).toHaveLength(1)
  expect(container.querySelector("[data-task]")!.getAttribute("data-task")).toBe(
    "night shift/chores",
  )
})


test("choosing another project changes what the board is showing", async () => {
  await render(initialStage(MIXED), TWO)

  await act(async () => {
    const select = picker()!
    select.value = "day job"
    select.dispatchEvent(new Event("change", { bubbles: true }))
  })

  expect(container.querySelector("[data-task]")!.getAttribute("data-task")).toBe(
    "day job/revision",
  )
})


test("the choice outlives the page, the way the view does", async () => {
  localStorage.setItem("poieo.project", "day job")
  await render(initialStage(MIXED), TWO)

  expect(picker()!.value).toBe("day job")
})


test("a remembered project the daemon no longer runs falls back to the first", async () => {
  // The daemon was restarted without it. A board that showed nothing, because
  // it was filtering on a project that is not there, would look broken.
  localStorage.setItem("poieo.project", "somewhere else")
  await render(initialStage(MIXED), TWO)

  expect(picker()!.value).toBe("night shift")
  expect(container.querySelectorAll("[data-task]")).toHaveLength(1)
})


test("switching projects puts away a drawer opened in the last one", async () => {
  await render(initialStage(MIXED), TWO)
  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="night shift/chores"] .basic-pick')!.click()
  })
  expect(container.querySelector(".drawer")).not.toBeNull()

  await act(async () => {
    const select = picker()!
    select.value = "day job"
    select.dispatchEvent(new Event("change", { bubbles: true }))
  })

  expect(container.querySelector(".drawer")).toBeNull()
})
