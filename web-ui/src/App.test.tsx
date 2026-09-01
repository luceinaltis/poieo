import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

vi.mock("./api", () => ({
  fetchTasks: vi.fn<typeof import("./api").fetchTasks>(async () => ({
    projects: [],
    tasks: [],
  })),
  fetchRuns: vi.fn<typeof import("./api").fetchRuns>(async () => [
    {
      run_id: "newest-but-quiet",
      task: "chores",
      project: "board",
      graph: "agent-task",
      status: "completed",
      started_at: "2026-08-22T07:30:00+00:00",
      finished_at: "2026-08-22T07:30:01+00:00",
      steps: 1,
      iteration: 2,
      trigger: "loop",
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
      project: "board",
      graph: "agent-task",
      status: "completed",
      started_at: "2026-08-22T07:28:19.836+00:00",
      finished_at: "2026-08-22T07:28:19.845+00:00",
      steps: 1,
      iteration: 1,
      trigger: "loop",
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
  fetchRunEvents: vi.fn<typeof import("./api").fetchRunEvents>(async () => AGENT_RUN),
  fetchDiff: vi.fn<typeof import("./api").fetchDiff>(async () => ({
    run_id: "20260822T072819-98a6708d",
    change: null,
  })),
  accept: vi.fn<typeof import("./api").accept>(async () => ({ ok: true, accepted: 0 })),
  discard: vi.fn<typeof import("./api").discard>(async () => ({
    ok: true,
    discarded: 0,
  })),
  openFeed: vi.fn<typeof import("./api").openFeed>(() => () => {}),
  fetchCard: vi.fn<typeof import("./api").fetchCard>(async () => ({
    task: "chores",
    text: "name: Chores\nfolder: ../work\nprompt: tidy\n",
    name: "Chores",
    folder: "../work",
    prompt: "tidy",
    plain: false,
  })),
  rewriteCard: vi.fn<typeof import("./api").rewriteCard>(async () => ({
    ok: true,
    task: "chores",
    live: true,
  })),
  setAside: vi.fn<typeof import("./api").setAside>(async () => ({
    ok: true,
    task: "chores",
  })),
  fetchModels: vi.fn<typeof import("./api").fetchModels>(async () => ({
    binding: { name: "mock", path: "x.yaml" },
    roles: ["default"],
    endpoints: [],
  })),
  fetchUndeclared: vi.fn<typeof import("./api").fetchUndeclared>(async () => []),
  fetchMemory: vi.fn<typeof import("./api").fetchMemory>(async () => ({
    enabled: false,
    page: null,
    stats: null,
    capabilities: { words: false, meaning: false, ask: false },
    graph: {
      nodes: [],
      edges: [],
      total_nodes: 0,
      total_edges: 0,
      truncated: false,
      edges_truncated: false,
    },
  })),
  fetchMemoryEntry: vi.fn<typeof import("./api").fetchMemoryEntry>(async () => null),
  searchMemory: vi.fn<typeof import("./api").searchMemory>(async () => ({
    ok: true,
    results: [],
  })),
  askMemory: vi.fn<typeof import("./api").askMemory>(async () => ({
    ok: true,
    citations: [],
    evidence: [],
  })),
}))

import App from "./App"
import { AGENT_RUN } from "./state/fixtures"
import { SKINS } from "./skins/registry"
import { initialStage, reduce, replay, setRuns } from "./state/stage"
import type { StageState } from "./state/stage"
import type { StageStore } from "./shell/stageStore"
import type { PoieoEvent, ProjectRow, RunSummary, TaskRow } from "./types"

const TASK_ROWS: TaskRow[] = [
  {
    name: "chores",
    project: "board",
    graph: "agent-task",
    trigger: "loop",
    status: "waiting",
    holding: false,
    enabled: true,
    stale: null,
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
    holding: false,
    enabled: true,
    stale: null,
    current_run_id: null,
    last_run: null,
    pending: 0,
    into: null,
    asking: null,
    then: [],
    shape: { entry: "", nodes: [] },
  },
]

const DRAWER_RUN: RunSummary = {
  run_id: "drawer-old",
  task: "chores",
  project: "board",
  graph: "agent-task",
  status: "completed",
  started_at: "2026-08-31T08:00:00Z",
  finished_at: "2026-08-31T08:00:04Z",
  steps: 1,
  iteration: 1,
  trigger: "schedule",
  usage: { input_tokens: 10, output_tokens: 2, cache_read_tokens: 0, cache_write_tokens: 0 },
  error: null,
  said: "the previous result",
}

function fakeStore(
  stage: StageState,
  // Named for the project represented by TASK_ROWS: the board shows one
  // project's tasks, so a fake naming another would filter them all away.
  project: ProjectRow | ProjectRow[] | null = { name: "board", root: "/home/k/chores", keeps_copies: true },
): StageStore & { push(next: StageState): void } {
  let current = stage
  // One array, not a fresh one per call: useSyncExternalStore compares
  // snapshots by identity and re-renders forever if they never match.
  const projectList = project === null ? [] : [project].flat()
  const listeners = new Set<() => void>()
  return {
    getStage: () => current,
    getTasks: () => TASK_ROWS,
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
  // The shell is driven here by clicking a task on the board, so these ask
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
  expect(container.textContent).toContain("No tasks yet. Create one to put your models to work.")

  const start = container.querySelector<HTMLElement>('[data-do="empty-new-task"]')
  expect(start?.textContent).toBe("New task")
  await act(async () => start!.click())
  expect(container.querySelector('.make[aria-label="New task"]')).not.toBeNull()
})

test("the shell carries the approved poieo lockup", async () => {
  await render(initialStage([]))

  const lockup = container.querySelector<HTMLImageElement>(".shell-lockup")
  expect(lockup?.alt).toBe("poieo")
  expect(lockup?.src).toContain("lockup.svg")
  expect(container.querySelector(".shell-title")).toBeNull()
})

test("one rendering means no picker, and the board carries the tasks", async () => {
  await render(initialStage(TASK_ROWS))

  // One rendering of the board exists, so there is no picker at all -- the
  // same furniture rule the project name follows: a control with one option
  // is not a control. If a second rendering ever lands in the registry, this
  // flips and the picker has to come back.
  const renderings = SKINS.filter((skin) => !skin.standalone)
  expect(renderings.map((skin) => skin.id)).toEqual(["basic"])
  expect(container.querySelector(".shell-skin")).toBeNull()
  expect(container.querySelectorAll("[data-task]")).toHaveLength(2)
})

test("runs is a place on the rail: there when you go, gone when you leave", async () => {
  await render(initialStage(TASK_ROWS))

  // The rail carries it beside board, models and new task.
  const go = container.querySelector<HTMLElement>('[data-do="open-runs"]')!
  expect(go).not.toBeNull()
  await act(async () => go.click())

  // The stage now answers "what has it been doing" -- and the rendering
  // picker is gone, because it renders the *board*, which is not on screen.
  expect(container.querySelector(".runs")).not.toBeNull()
  expect(container.querySelector(".basic")).toBeNull()
  expect(go.getAttribute("aria-current")).toBe("page")
  expect(container.querySelector(".shell-skin")).toBeNull()

  // Board brings back the rendering that was left, not a hard-coded one.
  await act(async () => container.querySelector<HTMLElement>('[data-do="open-board"]')!.click())
  expect(container.querySelector(".basic")).not.toBeNull()
  expect(container.querySelector(".runs")).toBeNull()
  expect(
    container.querySelector('[data-do="open-board"]')!.getAttribute("aria-current"),
  ).toBe("page")
})

test("memory is a project place on the rail, not a rendering of the task board", async () => {
  await render(initialStage(TASK_ROWS))

  const go = container.querySelector<HTMLElement>('[data-do="open-memory"]')!
  expect(go).not.toBeNull()
  await act(async () => go.click())
  await act(async () => {})

  expect(container.textContent).toContain("This project keeps no long memory")
  expect(container.querySelector(".shell-board")!.getAttribute("data-hidden")).toBe("true")
  expect(go.getAttribute("aria-current")).toBe("page")

  await act(async () => container.querySelector<HTMLElement>('[data-do="open-board"]')!.click())
  expect(container.querySelector(".basic")).not.toBeNull()
  expect(container.querySelector(".memory-state")).toBeNull()
})

test("a panel opens over runs without knocking it off the stage", async () => {
  await render(initialStage(TASK_ROWS))
  await act(async () => container.querySelector<HTMLElement>('[data-do="open-runs"]')!.click())

  await act(async () => container.querySelector<HTMLElement>('[data-do="open-models"]')!.click())

  // The panel holds the margin; the place behind it is still runs. One item
  // says where you are, and it is the panel's.
  expect(container.querySelector(".runs")).not.toBeNull()
  expect(container.querySelectorAll('[aria-current="page"]')).toHaveLength(1)
  expect(
    container.querySelector('[data-do="open-models"]')!.getAttribute("aria-current"),
  ).toBe("page")

  // Closing it lands back on runs, not on the board.
  await act(async () => container.querySelector<HTMLElement>('[data-do="open-runs"]')!.click())
  expect(
    container.querySelector('[data-do="open-runs"]')!.getAttribute("aria-current"),
  ).toBe("page")
})

test("a task picked off a runs lane opens the drawer with runs still on stage", async () => {
  await render(replay(initialStage(TASK_ROWS), AGENT_RUN))
  await act(async () => container.querySelector<HTMLElement>('[data-do="open-runs"]')!.click())

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .runs-head')!.click()
  })

  expect(container.querySelector(".drawer")).not.toBeNull()
  expect(container.querySelector(".drawer")!.getAttribute("data-task")).toBe("chores")
  expect(container.querySelector(".runs")).not.toBeNull()
})

test("a reader who left on runs comes back to runs", async () => {
  localStorage.setItem("poieo.skin", "runs")
  await render(initialStage(TASK_ROWS))

  expect(container.querySelector(".runs")).not.toBeNull()
  expect(
    container.querySelector('[data-do="open-runs"]')!.getAttribute("aria-current"),
  ).toBe("page")
})

test("a stale stored skin id still renders a board", async () => {
  // "atelier" is the id every reader who tried the workshop has stored.
  localStorage.setItem("poieo.skin", "atelier")
  await render(initialStage(TASK_ROWS))

  // The registry falls back rather than blanking the page.
  expect(container.querySelector(".basic")).not.toBeNull()
  expect(container.querySelectorAll("[data-task]").length).toBeGreaterThan(0)
})

test("selecting a task opens the drawer, and reading it leaves the board alone", async () => {
  const stage = replay(initialStage(TASK_ROWS), AGENT_RUN)
  const store = await render(stage)

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })

  const drawer = container.querySelector(".drawer")!
  expect(drawer).not.toBeNull()
  expect(drawer.getAttribute("data-task")).toBe("chores")
  expect(drawer.querySelector(".run-brief")?.textContent).toContain("did the thing")
  // The audit costs nothing until asked for, and reading it still belongs to
  // the drawer rather than the live board.
  expect(drawer.textContent).not.toContain("list_dir")
  await act(async () => {
    drawer.querySelector<HTMLElement>('[data-do="toggle-activity"]')!.click()
  })
  expect(drawer.textContent).toContain("list_dir")
  expect(store.getStage()).toBe(stage)
})

test("closing the drawer puts it away", async () => {
  await render(replay(initialStage(TASK_ROWS), AGENT_RUN))

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })
  await act(async () => {
    container.querySelector<HTMLElement>('[aria-label="Close"]')!.click()
  })

  expect(container.querySelector(".drawer")).toBeNull()
})


test("opening a different task does not show the previous one's runs", async () => {
  // The drawer keeps a selected run. Without a fresh instance per
  // task, switching tasks leaves the last task's run in the diff pane.
  await render(replay(initialStage(TASK_ROWS), AGENT_RUN))

  const firstOpener = container.querySelector<HTMLElement>(
    '[data-task="board/chores"] .basic-pick',
  )!
  await act(async () => firstOpener.click())
  expect(container.querySelector(".drawer")!.getAttribute("data-task")).toBe("chores")
  const first = container.querySelector(".run-brief")

  const secondOpener = container.querySelector<HTMLElement>(
    '[data-task="board/revision"] .basic-pick',
  )!
  await act(async () => secondOpener.click())

  const drawer = container.querySelector(".drawer")!
  expect(drawer.getAttribute("data-task")).toBe("revision")
  // nothing carried over from the task we just left
  expect(container.querySelector(".run-brief")).not.toBe(first)
  expect(drawer.querySelector('[data-do="toggle-activity"]')?.getAttribute("aria-expanded")).toBe(
    "false",
  )

  await act(async () => {
    drawer.querySelector<HTMLElement>('[aria-label="Close"]')!.click()
  })
  expect(document.activeElement).toBe(secondOpener)
})


test("a frame for another task leaves the open drawer alone", async () => {
  // A busy board streams frames while someone reads a drawer. Every entry in
  // the timeline formats its timestamp on render, so "the drawer did not
  // re-render" is observable as "no timestamp was formatted again".
  const stage = replay(initialStage(TASK_ROWS), AGENT_RUN)
  const store = await render(stage)

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })
  await act(async () => {
    container.querySelector<HTMLElement>('[data-do="toggle-activity"]')!.click()
  })
  expect(container.querySelectorAll(".drawer-entry").length).toBeGreaterThan(0)

  const formatted = vi.spyOn(Date.prototype, "toLocaleTimeString")
  await act(async () => {
    store.push(reduce(stage, { run_id: "rr", type: "run_started", data: { task: "revision" } }))
  })

  expect(formatted).not.toHaveBeenCalled()
  formatted.mockRestore()
})


test("the drawer opens on the newest run", async () => {
  // The first glance answers what happened most recently. An older change is
  // still in All runs, rather than quietly replacing the latest result.
  await render(replay(initialStage(TASK_ROWS), AGENT_RUN))

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })

  const selected = container.querySelector(".run-brief")!
  expect(selected.getAttribute("data-run")).toBe("newest-but-quiet")
  expect(selected.querySelector("h3")?.textContent).toBe("Latest run")
  expect(container.querySelector("[data-run][data-selected='true']")).toBeNull()
})

test("an open drawer follows a live result and its review attention", async () => {
  const stage = setRuns(initialStage(TASK_ROWS), "board/chores", [DRAWER_RUN])
  const store = await render(stage)
  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })
  expect(container.querySelector(".run-brief")?.getAttribute("data-run")).toBe("drawer-old")

  const summary: PoieoEvent = {
    ...DRAWER_RUN,
    type: "run_summary",
    run_id: "drawer-live",
    started_at: "2026-08-31T09:00:00Z",
    finished_at: "2026-08-31T09:00:05Z",
    said: "updated the guide",
    change: {
      base: "a",
      head: "b",
      files: ["GUIDE.md"],
      insertions: 4,
      deletions: 0,
      message: "updated the guide",
    },
  }
  await act(async () => store.push(reduce(stage, summary)))

  expect(container.querySelector(".run-brief")?.getAttribute("data-run")).toBe("drawer-live")
  expect(container.querySelector(".run-brief-what")?.textContent).toBe("updated the guide")
  expect(container.querySelector(".drawer-state")?.textContent).toBe("1 change to review")
})

test("a selected live run stays selected as the live window advances", async () => {
  let stage = setRuns(initialStage(TASK_ROWS), "board/chores", [DRAWER_RUN])
  const store = await render(stage)
  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })

  const first: PoieoEvent = {
    ...DRAWER_RUN,
    type: "run_summary",
    run_id: "live-first",
    status: "asking",
    started_at: "2026-08-31T09:00:00Z",
    finished_at: "2026-08-31T09:00:05Z",
    said: "Ship the first result?",
  }
  stage = reduce(stage, first)
  await act(async () => store.push(stage))

  const second: PoieoEvent = {
    ...DRAWER_RUN,
    type: "run_summary",
    run_id: "live-2",
    started_at: "2026-08-31T10:00:00Z",
    finished_at: "2026-08-31T10:00:05Z",
    said: "live result 2",
  }
  stage = reduce(stage, second)
  await act(async () => store.push(stage))
  await act(async () => {
    container.querySelector<HTMLElement>('[data-do="toggle-runs"]')!.click()
  })
  await act(async () => {
    container.querySelector<HTMLElement>('[data-failed-toggle="true"]')!.click()
  })
  await act(async () => {
    container.querySelector<HTMLElement>('[data-run="live-first"] .run-open')!.click()
  })

  for (let index = 3; index <= 12; index += 1) {
    const summary: PoieoEvent = {
      ...DRAWER_RUN,
      type: "run_summary",
      run_id: `live-${index}`,
      started_at: `2026-08-31T${String(index + 8).padStart(2, "0")}:00:00Z`,
      finished_at: `2026-08-31T${String(index + 8).padStart(2, "0")}:00:05Z`,
      said: `live result ${index}`,
    }
    stage = reduce(stage, summary)
  }
  await act(async () => store.push(stage))

  stage = reduce(stage, {
    ...first,
    status: "completed",
    said: "shipped the first result",
  })
  await act(async () => store.push(stage))

  expect(container.querySelector(".run-brief")?.getAttribute("data-run")).toBe("live-first")
  expect(container.querySelector(".run-brief-what")?.textContent).toBe(
    "shipped the first result",
  )
  await act(async () => {
    container.querySelector<HTMLElement>('[data-do="toggle-runs"]')!.click()
  })
  expect(container.querySelector('[data-run="live-3"]')).not.toBeNull()
  expect(container.querySelector('[data-run="live-12"]')).not.toBeNull()
})

test("an open drawer shows a question as soon as the task asks", async () => {
  const stage = setRuns(initialStage(TASK_ROWS), "board/chores", [DRAWER_RUN])
  const store = await render(stage)
  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })

  const begun = reduce(stage, {
    run_id: "asking-live",
    type: "run_started",
    data: { task: "chores", project: "board" },
  })
  const asking = reduce(begun, {
    run_id: "asking-live",
    type: "run_asking",
    data: { question: "Ship this?", choices: ["ship", "hold"] },
  })
  await act(async () => store.push(asking))

  expect(container.querySelector(".drawer-state")?.textContent).toBe("Needs your answer")
  expect(container.querySelector(".question")?.textContent).toContain("Ship this?")
})


// -- whose board this is ------------------------------------------------------


test("the bar names the project, so two boards are not the same board", async () => {
  await render(initialStage([]), { name: "night shift", root: "/home/k/chores", keeps_copies: true })

  const named = container.querySelector(".shell-project")!
  expect(named.textContent).toBe("night shift")
  // Two worktrees of one repository are two projects with the same folder
  // name; the path is what tells them apart once the names collide.
  expect(named.getAttribute("title")).toBe("/home/k/chores")
})


test("the tab says it too, because that is what two open boards show", async () => {
  await render(initialStage([]), { name: "night shift", root: "/home/k/chores", keeps_copies: true })
  expect(document.title).toContain("night shift")
})


test("a board that has not heard yet says nothing rather than guessing", async () => {
  await render(initialStage([]), null)
  expect(container.querySelector(".shell-project")).toBeNull()
})

// -- picking a project --------------------------------------------------------

const TWO: ProjectRow[] = [
  { name: "night shift", root: "/home/k/a", keeps_copies: true },
  { name: "day job", root: "/home/k/b", keeps_copies: true },
]

const MIXED: TaskRow[] = [
  { ...TASK_ROWS[0], project: "night shift" },
  { ...TASK_ROWS[1], project: "day job" },
]

const picker = () => container.querySelector<HTMLSelectElement>(".shell-project-pick")


test("one project is a name, not a thing to choose between", async () => {
  await render(initialStage(TASK_ROWS), { name: "night shift", root: "/home/k/a", keeps_copies: true })

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

test("make one like it opens the make panel already filled in", async () => {
  // Most new tasks are not blank pages: they are "like that one, but". The
  // drawer's card fold hands the three fields to the make panel, and the
  // person edits from there rather than from nothing.
  await render(replay(initialStage(TASK_ROWS), AGENT_RUN))

  const opener = container.querySelector<HTMLElement>(
    '[data-task="board/chores"] .basic-pick',
  )!
  await act(async () => opener.click())
  await act(async () => {
    container.querySelector<HTMLElement>(".card-open")!.click()
  })
  await act(async () => {
    container.querySelector<HTMLElement>('[data-do="make-alike"]')!.click()
  })

  // The drawer gave up the margin to the panel, prefilled -- and already
  // saying the one thing that must change: the seeded title is the original
  // task's, so the collision warning is up and save is held until a rename.
  expect(container.querySelector(".drawer")).toBeNull()
  expect(container.querySelector<HTMLInputElement>('input[name="name"]')!.value).toBe("Chores")
  expect(container.textContent).toContain("already has a task called")
  expect(container.querySelector<HTMLButtonElement>('[data-do="make-task"]')!.disabled).toBe(true)
  expect(container.querySelector<HTMLInputElement>('input[name="folder"]')!.value).toBe("../work")
  expect(container.querySelector<HTMLTextAreaElement>('textarea[name="prompt"]')!.value).toBe(
    "tidy",
  )

  await act(async () => container.querySelector<HTMLElement>(".make-close")!.click())
  expect(document.activeElement).toBe(opener)

  // `new task` from the rail afterwards is a blank page again: the seed
  // belongs to the press that asked for it, not to the panel.
  await act(async () => container.querySelector<HTMLElement>('[data-do="open-make"]')!.click())
  expect(container.querySelector<HTMLInputElement>('input[name="name"]')!.value).toBe("")
})

test("switching projects puts a seeded make panel away with its seed", async () => {
  // A seed's folder means something in the project it came from. Carried
  // across a switch it would offer that path against another project's tasks
  // folder -- the exact mistake the panel's own key comment promises against.
  await render(replay(initialStage(TASK_ROWS), AGENT_RUN), [
    { name: "board", root: "/home/k/chores", keeps_copies: true },
    { name: "other", root: "/home/k/other", keeps_copies: true },
  ])

  await act(async () => {
    container.querySelector<HTMLElement>('[data-task="board/chores"] .basic-pick')!.click()
  })
  await act(async () => container.querySelector<HTMLElement>(".card-open")!.click())
  await act(async () => {
    container.querySelector<HTMLElement>('[data-do="make-alike"]')!.click()
  })
  expect(container.querySelector<HTMLInputElement>('input[name="folder"]')!.value).toBe("../work")

  const picker = container.querySelector<HTMLSelectElement>(".shell-project-pick")!
  await act(async () => {
    picker.value = "other"
    picker.dispatchEvent(new Event("change", { bubbles: true }))
  })

  // The panel is gone, and so is the seed: opening `new task` in the other
  // project starts from a blank page, not from board's folder.
  expect(container.querySelector('input[name="folder"]')).toBeNull()
  await act(async () => container.querySelector<HTMLElement>('[data-do="open-make"]')!.click())
  expect(container.querySelector<HTMLInputElement>('input[name="folder"]')!.value).toBe("")
})
