import { afterEach, beforeEach, expect, test, vi } from "vitest"

import { basic } from "./index"
import { initialStage } from "../../state/stage"
import type { TaskRow } from "../../types"

const task: TaskRow = {
  name: "Review a draft", project: "demo", graph: "review", trigger: "every 1h",
  status: "waiting", holding: false, enabled: true, stale: null,
  current_run_id: null, last_run: null, pending: 0, into: null, asking: null, then: [],
  shape: { entry: "review", nodes: [
    { id: "review", description: "Review", type: "agent", next: "decide", default: null,
      branches: [], model: "mock", tools: [] },
    { id: "decide", description: "Ready to finish?", type: "router", next: null, default: "revise",
      branches: [{ to: null, label: "approved" }], model: null, tools: [] },
    { id: "revise", description: "Revise", type: "agent", next: "review", default: null,
      branches: [], model: "mock", tools: [] },
  ] },
}

let host: HTMLDivElement
let handle: ReturnType<typeof basic.mount>
const step = (id: string) => host.querySelector<HTMLElement>(`.basic-node[data-node="${id}"]`)!

beforeEach(() => {
  host = document.createElement("div")
  document.body.append(host)
  handle = basic.mount(host, { onSelectTask: vi.fn() })
  handle.update(initialStage([task]))
})

afterEach(() => {
  handle.destroy()
  host.remove()
})

test("a closed card names where each step comes from and goes next, including the return path", () => {
  expect(host.querySelector("[data-task]")?.getAttribute("data-open")).toBe("false")
  expect(step("review").querySelector(".basic-step-input")?.textContent).toBe("FromStart · Revise")
  expect(step("review").querySelector(".basic-step-output")?.textContent).toBe("NextReady to finish?")
  expect(step("decide").querySelector(".basic-step-input")?.textContent).toBe("FromReview")
  expect(step("revise").querySelector(".basic-step-output")?.textContent).toBe("NextReview")
})

test("every condition keeps its own named destination and otherwise can end the run", () => {
  const branches = structuredClone(task)
  branches.shape.nodes[1].branches = [
    { to: "revise", label: "result.needs_work" },
    { to: "revise", label: "result.too_long" },
  ]
  branches.shape.nodes[1].default = null
  handle.update(initialStage([branches]))

  const routes = [...step("decide").querySelectorAll(".basic-step-output")].map(el => el.textContent)
  expect(routes).toEqual(["If result.needs_workRevise", "If result.too_longRevise", "OtherwiseEnd run"])
  // Two conditions are alternatives from one step, not two previous steps.
  expect(step("revise").querySelector(".basic-step-input")?.textContent).toBe("FromReady to finish?")
})

test("one step shows both the start and the end without opening anything", () => {
  const single = structuredClone(task)
  single.shape.nodes = [{ ...single.shape.nodes[0], next: null }]
  handle.update(initialStage([single]))

  expect(step("review").querySelector(".basic-step-input")?.textContent).toBe("FromStart")
  expect(step("review").querySelector(".basic-step-output")?.textContent).toBe("NextEnd run")
})

test("steps with the same description remain distinguishable at both ends of a connection", () => {
  const duplicate = structuredClone(task)
  duplicate.shape.nodes[2].description = "Review"
  handle.update(initialStage([duplicate]))

  expect(step("review").querySelector(".basic-node-name")?.textContent).toBe("Review (review)")
  expect(step("review").querySelector(".basic-step-input")?.textContent).toContain("Review (revise)")
  expect(step("revise").querySelector(".basic-step-output")?.textContent).toContain("Review (review)")
})

test("long names and conditions stay available on the card, in reading order from the start", () => {
  const long = structuredClone(task)
  const name = "Read the incoming request and collect everything needed for a reply"
  const condition = "state.priority == 'urgent' and state.category == 'support'"
  long.shape.nodes[0].description = name
  long.shape.nodes[1].branches[0].label = condition
  long.shape.nodes.reverse()
  handle.update(initialStage([long]))

  expect([...host.querySelectorAll(".basic-node")].map(el => el.getAttribute("data-node")))
    .toEqual(["review", "decide", "revise"])
  expect(step("review").querySelector(".basic-node-name")?.textContent).toBe(name)
  expect(step("decide").querySelector(".basic-step-output")?.textContent).toBe(`If ${condition}End run`)
})

test("scrolling the steps belongs to the card and does not zoom the board", () => {
  const board = host.querySelector<HTMLElement>(".basic")!
  const before = board.style.transform
  const inside = host.querySelector<HTMLElement>(".basic-inside")!
  inside.scrollTop = 80
  const wheel = new WheelEvent("wheel", { deltaY: 120, bubbles: true, cancelable: true })
  inside.dispatchEvent(wheel)
  expect(board.style.transform).toBe(before)
  expect(wheel.defaultPrevented).toBe(false)

  const running = initialStage([task])
  running.tasks["demo/Review a draft"].status = "running"
  running.tasks["demo/Review a draft"].currentNode = "revise"
  handle.update(running)
  expect(inside.scrollTop).toBe(80)
  expect(step("revise").dataset.here).toBe("true")
})

test("live updates keep the step being read and its text selection", () => {
  const before = step("review")
  const selection = window.getSelection()!
  const range = document.createRange()
  range.selectNodeContents(before.querySelector(".basic-node-name")!)
  selection.removeAllRanges()
  selection.addRange(range)

  const running = initialStage([task])
  running.tasks["demo/Review a draft"].status = "running"
  running.tasks["demo/Review a draft"].currentNode = "decide"
  handle.update(running)
  expect(step("review")).toBe(before)
  expect(selection.toString()).toBe("Review")
  expect(step("decide").dataset.here).toBe("true")
  selection.removeAllRanges()
})

test("changed connections replace the old destinations and lay out the board again", () => {
  const before = host.querySelector(".basic-speck")
  const changed = structuredClone(task)
  changed.shape.nodes[0].next = "revise"
  handle.update(initialStage([changed]))
  expect(step("review").querySelector(".basic-step-output")?.textContent).toBe("NextRevise")
  expect(host.querySelector(".basic-speck")).not.toBe(before)
})
