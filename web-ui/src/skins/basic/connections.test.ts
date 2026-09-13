import { afterEach, beforeEach, expect, test, vi } from "vitest"

import { basic } from "./index"
import { initialStage } from "../../state/stage"
import type { TaskRow } from "../../types"

const task = (name: string): TaskRow => ({
  name, project: "demo", graph: name, trigger: "manual", status: "waiting",
  holding: false, held_because: null, enabled: true, stale: null, current_run_id: null,
  last_run: null, pending: 0, into: null, asking: null, then: [],
  shape: { entry: "work", nodes: [{ id: "work", description: `${name} work`, type: "agent",
    next: null, default: null, branches: [], model: "mock", tools: [] }] },
})
const source = { ...task("Draft"), then: [{ to: "Review", label: "Ready for review" }] }
let host: HTMLElement
let handle: ReturnType<typeof basic.mount>
const card = (name: string) => host.querySelector<HTMLElement>(`[data-task="demo/${name}"]`)!

beforeEach(() => {
  host = document.createElement("div")
  document.body.append(host)
  handle = basic.mount(host, { onSelectTask: vi.fn() })
  handle.update(initialStage([source, task("Review"), task("Other")]))
})
afterEach(() => { handle.destroy(); host.remove() })

test("a handoff joins the sending graph's output to the receiving graph's input", () => {
  expect(card("Draft").querySelector('[data-port="output"]')?.textContent).toContain("Output")
  expect(card("Review").querySelector('[data-port="input"]')?.textContent).toContain("Input")
  const outgoing = [...card("Draft").querySelectorAll(".basic-step-edge")].map(e => e.getAttribute("aria-label"))
  expect(outgoing).toContain("End run → Output")
  expect(card("Review").querySelector(".basic-step-edge")?.getAttribute("aria-label")).toBe("Input → Review work")
  expect(host.querySelector('.basic-connection')?.getAttribute("aria-label"))
    .toBe("Draft output → Review input: Ready for review")
  expect(card("Draft").dataset.connected).toBe("true")
  expect(card("Review").dataset.connected).toBe("true")
  expect(card("Other").dataset.connected).toBe("false")
})

test("all possible endings feed the completed run output, not one guessed last step", () => {
  const branching = structuredClone(source)
  branching.shape.nodes = [{ ...branching.shape.nodes[0], type: "router", branches: [
    { to: null, label: "approved" },
  ] }]
  handle.update(initialStage([branching, task("Review")]))
  expect(card("Draft").querySelectorAll('[data-port="output"]')).toHaveLength(1)
  expect([...card("Draft").querySelectorAll(".basic-step-edge")].filter(e => e.getAttribute("aria-label") === "End run → Output"))
    .toHaveLength(2)
})

test("following a connection highlights both ends and lets a keyboard user reach its target", () => {
  const connection = host.querySelector<SVGElement>(".basic-connection")!
  expect(connection).not.toBeNull()
  connection.dispatchEvent(new FocusEvent("focus"))
  expect(card("Draft").dataset.linked).toBe("true")
  expect(card("Review").dataset.linked).toBe("true")
  expect(card("Other").dataset.linked).toBe("false")
  connection.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
  expect(document.activeElement).toBe(card("Review").querySelector('[data-port="input"]'))
})

test("parallel handoffs share one route while retaining their authored priority", () => {
  const parallel = { ...source, then: [
    { to: "Review", label: "urgent" }, { to: "Other", label: "needs changes" },
    { to: "Review", label: "question" }, { to: null, label: "quiet" },
  ] }
  handle.update(initialStage([parallel, task("Review"), task("Other")]))
  expect(host.querySelectorAll(".basic-connection")).toHaveLength(2)
  const sameTarget = host.querySelector('[data-from="demo/Draft"][data-to="demo/Review"]')!
  expect(sameTarget.textContent).toContain("1. urgent")
  expect(sameTarget.textContent).toContain("3. question")
  expect(card("Draft").textContent).toContain("4. quiet")
})

test("changing an upstream route updates an otherwise unchanged receiving card", () => {
  const before = card("Other").querySelector(".basic-node")
  const changed = { ...source, then: [{ to: "Other", label: "Send elsewhere" }] }
  handle.update(initialStage([changed, task("Review"), task("Other")]))
  expect(card("Review").querySelector('[data-port="input"]')).toBeNull()
  expect(card("Other").querySelector('[data-port="input"]')).not.toBeNull()
  expect(card("Other").querySelector(".basic-node")).not.toBe(before)
  expect(host.querySelector(".basic-connection")?.getAttribute("aria-label"))
    .toBe("Draft output → Other input: Send elsewhere")
})

test("unrelated live updates preserve the graph and connection being read", () => {
  const stage = initialStage([source, task("Review"), task("Other")])
  handle.update(stage)
  const before = card("Draft").querySelector(".basic-node")
  const connection = host.querySelector(".basic-connection")
  const next = { ...stage, tasks: { ...stage.tasks, "demo/Other": { ...stage.tasks["demo/Other"], status: "running" } } }
  handle.update(next)
  expect(card("Draft").querySelector(".basic-node")).toBe(before)
  expect(host.querySelector(".basic-connection")).toBe(connection)
})

test("same-named tasks in another project never become the input of this connection", () => {
  handle.update(initialStage([source, { ...task("Review"), project: "elsewhere" }]))
  expect(host.querySelector(".basic-connection")).toBeNull()
  expect(host.querySelector('[data-task="elsewhere/Review"] [data-port="input"]')).toBeNull()
})
