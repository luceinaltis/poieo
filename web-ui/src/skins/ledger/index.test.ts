import { afterEach, beforeEach, expect, test, vi } from "vitest"

import { ledger } from "./index"
import { AGENT_RUN } from "../../state/fixtures"
import { initialStage, reduce, replay } from "../../state/stage"
import type { FlowRow } from "../../types"

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
    then: [],
    shape: { entry: "", nodes: [] },
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
    shape: { entry: "", nodes: [] },
  },
]

let el: HTMLDivElement

beforeEach(() => {
  el = document.createElement("div")
  document.body.append(el)
})

afterEach(() => {
  el.remove()
})

test("a frame for one flow does not rebuild the other flows' cards", () => {
  const handle = ledger.mount(el, { onSelectWorker: vi.fn() })
  const stage = replay(initialStage(FLOWS), AGENT_RUN)
  handle.update(stage)

  // The chores card carries tool items from the replayed run.
  const tool = el.querySelector('[data-flow="chores"] .ledger-tool')
  expect(tool).not.toBeNull()

  // An event for the other flow arrives; chores was not touched, and the
  // reducer keeps its object identity, so its DOM must survive untouched.
  const next = reduce(stage, {
    run_id: "rr",
    type: "run_started",
    data: { flow: "revision" },
  })
  handle.update(next)

  expect(el.querySelector('[data-flow="chores"] .ledger-tool')).toBe(tool)
  // The flow the frame was for did repaint.
  expect(el.querySelector('[data-flow="revision"]')!.getAttribute("data-status")).toBe(
    "running",
  )
  handle.destroy()
})
