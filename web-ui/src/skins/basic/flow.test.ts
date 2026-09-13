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
const paths = () => [...host.querySelectorAll<SVGElement>(".basic-step-edge")]
const connections = () => paths().map(path => path.getAttribute("aria-label"))

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

test("a closed card draws directed connections, including the return path", () => {
  expect(host.querySelector("[data-task]")?.getAttribute("data-open")).toBe("false")
  expect(connections()).toEqual(expect.arrayContaining([
    "Start → Review", "Review → Ready to finish?", "Revise → Review",
  ]))
  for (const path of paths()) {
    expect(path.getAttribute("d")).toMatch(/^M.+L/)
    expect(path.parentElement?.querySelector(".basic-step-arrow")).not.toBeNull()
  }
})

test("every condition keeps its own named destination and otherwise can end the run", () => {
  const branches = structuredClone(task)
  branches.shape.nodes[1].branches = [
    { to: "revise", label: "result.needs_work" },
    { to: "revise", label: "result.too_long" },
  ]
  branches.shape.nodes[1].default = null
  handle.update(initialStage([branches]))

  const routes = paths().filter(path => path.dataset.from === "decide")
  expect(routes.map(path => path.getAttribute("aria-label"))).toEqual([
    "Ready to finish? → Revise: If result.needs_work", "Ready to finish? → Revise: If result.too_long",
    "Ready to finish? → End run: Otherwise",
  ])
  expect(new Set(routes.map(path => path.getAttribute("d"))).size).toBe(3)
})

test("one step shows both the start and the end without opening anything", () => {
  const single = structuredClone(task)
  single.shape.nodes = [{ ...single.shape.nodes[0], next: null }]
  handle.update(initialStage([single]))

  expect(connections()).toEqual(["Start → Review", "Review → End run"])
  expect(host.querySelector(".basic-step-start")?.textContent).toBe("Start")
  expect(host.querySelector(".basic-step-end")?.textContent).toBe("End run")
})

test("steps with the same description remain distinguishable at both ends of a connection", () => {
  const duplicate = structuredClone(task)
  duplicate.shape.nodes[2].description = "Review"
  handle.update(initialStage([duplicate]))

  expect(step("review").querySelector(".basic-node-name")?.textContent).toBe("Review (review)")
  expect(connections()).toContain("Review (revise) → Review (review)")
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
  expect(connections()).toContain(`Ready to finish? → End run: If ${condition}`)
  expect([...host.querySelectorAll(".basic-step-condition")].map(el => el.textContent))
    .toContain(`If ${condition}`)
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
  expect(connections()).toContain("Review → Revise")
  expect(connections()).not.toContain("Review → Ready to finish?")
  expect(host.querySelector(".basic-speck")).not.toBe(before)
})
