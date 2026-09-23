import { afterEach, beforeEach, expect, test, vi } from "vitest"

import { basic } from "./index"
import { initialStage } from "../../state/stage"
import type { TaskRow } from "../../types"

const task = (name: string): TaskRow => ({
  name, project: "demo", graph: name, trigger: "manual", status: "waiting",
  holding: false, held_because: null, enabled: true, stale: null, current_run_id: null,
  last_run: null, pending: 0, into: null, asking: null, then: [],
  shape: { entry: "check", nodes: [
    { id: "check", description: "Check the draft", type: "agent", next: "decide",
      default: null, branches: [], model: "mock", tools: [] },
    { id: "decide", description: "Ready to send?", type: "router", next: null,
      default: null, branches: [{ to: "check", label: "needs changes" }], model: null, tools: [] },
  ] },
})
const source = { ...task("Draft"), then: [{ to: "Review", label: "Ready for review" }] }
let host: HTMLElement
let handle: ReturnType<typeof basic.mount>
const card = (name: string) => host.querySelector<HTMLElement>(`[data-task="demo/${name}"]`)!
const toggle = (name: string) => card(name).querySelector<HTMLButtonElement>(".basic-toggle")!

beforeEach(() => {
  host = document.createElement("div")
  document.body.append(host)
  handle = basic.mount(host, { onSelectTask: vi.fn() })
  handle.update(initialStage([source, task("Review"), task("Other")]))
})

afterEach(() => { handle.destroy(); host.remove() })

test("cards start with a compact flow and keep their input and output connections", () => {
  for (const name of ["Draft", "Review", "Other"]) {
    expect(card(name).dataset.open).toBe("false")
    expect(card(name).querySelector(".basic-node")).toBeNull()
    expect(card(name).querySelector(".basic-step-condition")).toBeNull()
    expect(card(name).querySelector(".basic-inside")?.textContent).toContain("2 steps")
    expect(toggle(name).getAttribute("aria-label")).toBe(`Expand steps in ${name}`)
    expect(toggle(name).getAttribute("aria-expanded")).toBe("false")
    expect(card(name).querySelector(".basic-view-steps")?.closest("[hidden]")).not.toBeNull()
  }
  expect(card("Draft").querySelector('[data-port="output"]')).not.toBeNull()
  expect(card("Review").querySelector('[data-port="input"]')).not.toBeNull()
  expect(card("Other").querySelector(".basic-inside")?.textContent).toMatch(/Start.*2 steps.*End run/)
  expect(host.querySelector(".basic-connection")?.getAttribute("aria-label"))
    .toBe("Draft output → Review input: Ready for review")
})

test("expanding just one card reveals its full graph and collapsing restores the compact flow", () => {
  const compactWidth = card("Draft").style.width
  const wire = () => host.querySelector(".basic-wire")!.getAttribute("d")
  const compactWire = wire()
  toggle("Draft").focus()
  toggle("Draft").click()
  expect(toggle("Draft").getAttribute("aria-label")).toBe("Collapse steps in Draft")
  expect(toggle("Draft").getAttribute("aria-expanded")).toBe("true")
  expect(card("Draft").querySelectorAll(".basic-node")).toHaveLength(2)
  expect(card("Draft").querySelector(".basic-step-condition")?.textContent).toContain("needs changes")
  expect(card("Draft").querySelector(".basic-view-steps")?.closest("[hidden]")).toBeNull()
  expect(card("Review").querySelector(".basic-node")).toBeNull()
  expect(card("Other").querySelector(".basic-node")).toBeNull()
  expect(wire()).not.toBe(compactWire)

  toggle("Draft").click()
  expect(card("Draft").querySelector(".basic-node")).toBeNull()
  expect(card("Draft").style.width).toBe(compactWidth)
  expect(wire()).toBe(compactWire)
  expect(document.activeElement).toBe(toggle("Draft"))
})

test("a wide expanded graph gives its space back when collapsed", () => {
  const wide = structuredClone(source)
  wide.shape.nodes[1].branches = [
    { to: null, label: "approved" }, { to: null, label: "question" }, { to: "check", label: "retry" },
  ]
  handle.update(initialStage([wide, task("Review")]))
  const width = parseFloat(card("Draft").style.width)
  toggle("Draft").click()
  expect(parseFloat(card("Draft").style.width)).toBeGreaterThan(width)
  toggle("Draft").click()
  expect(parseFloat(card("Draft").style.width)).toBe(width)
})

test("live updates preserve each card's chosen detail level and reveal the current step on expansion", () => {
  toggle("Review").click()
  const before = card("Review").querySelector(".basic-node")
  const stage = initialStage([source, task("Review"), task("Other")])
  stage.tasks["demo/Draft"].status = "running"
  stage.tasks["demo/Draft"].currentNode = "decide"
  handle.update(stage)
  expect(card("Draft").querySelector(".basic-node")).toBeNull()
  expect(card("Draft").querySelector(".basic-now")?.textContent).toBe("Ready to send?")
  expect(card("Review").dataset.open).toBe("true")
  expect(card("Review").querySelector(".basic-node")).toBe(before)
  toggle("Draft").click()
  expect(card("Draft").querySelector('[data-node="decide"]')?.getAttribute("data-here")).toBe("true")
})

test("following a connection focuses the receiving input without expanding its card", () => {
  host.querySelector(".basic-connection")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
  expect(document.activeElement).toBe(card("Review").querySelector('[data-port="input"]'))
  expect(card("Review").dataset.open).toBe("false")
  expect(card("Review").querySelector(".basic-node")).toBeNull()
})

test("a graph edited while collapsed updates its count and opens the latest steps", () => {
  const changed = structuredClone(source)
  changed.shape.nodes = [{ ...changed.shape.nodes[0], next: null, description: "Write a reply" }]
  handle.update(initialStage([changed, task("Review")]))
  expect(card("Draft").querySelector(".basic-inside")?.textContent).toContain("1 step")
  expect(card("Draft").querySelector(".basic-node")).toBeNull()
  toggle("Draft").click()
  expect(card("Draft").querySelectorAll(".basic-node")).toHaveLength(1)
  expect(card("Draft").querySelector(".basic-node-name")?.textContent).toBe("Write a reply")
})

test("a compact independent flow belongs to board navigation", () => {
  const viewport = host.querySelector<HTMLElement>(".basic-viewport")!
  Object.defineProperty(viewport, "clientWidth", { value: 900 })
  Object.defineProperty(viewport, "clientHeight", { value: 600 })
  const board = host.querySelector<HTMLElement>(".basic")!
  const before = board.style.transform
  const wheel = new WheelEvent("wheel", { deltaY: -200, cancelable: true, bubbles: true })
  card("Other").querySelector(".basic-inside")!.dispatchEvent(wheel)
  expect(wheel.defaultPrevented).toBe(true)
  expect(board.style.transform).not.toBe(before)
})

test("expansion controls follow the visible card title, including a title edited while open", () => {
  const titled = { ...source, title: "Prepare a reply" }
  handle.update(initialStage([titled, task("Review")]))
  expect(toggle("Draft").getAttribute("aria-label")).toBe("Expand steps in Prepare a reply")
  expect(card("Draft").querySelector(".basic-inside")?.getAttribute("aria-label"))
    .toBe("Step connections in Prepare a reply")
  toggle("Draft").click()
  handle.update(initialStage([{ ...titled, title: "Polish the reply" }, task("Review")]))
  expect(toggle("Draft").getAttribute("aria-label")).toBe("Collapse steps in Polish the reply")
  expect(card("Draft").querySelector(".basic-inside")?.getAttribute("aria-label"))
    .toBe("Step connections in Polish the reply")
  expect(card("Draft").querySelectorAll(".basic-node")).toHaveLength(2)
  toggle("Draft").click()
  expect(toggle("Draft").getAttribute("aria-label")).toBe("Expand steps in Polish the reply")
})

test.each([false, true])("editing a card title preserves its focused input (expanded: %s)", open => {
  if (open) toggle("Review").click()
  const input = card("Review").querySelector<HTMLElement>('[data-port="input"]')!
  const scene = card("Review").querySelector(".basic-step-scene")
  input.focus()
  handle.update(initialStage([source, { ...task("Review"), title: "Check before sending" }, task("Other")]))
  expect(card("Review").querySelector('[data-port="input"]')).toBe(input)
  expect(card("Review").querySelector(".basic-step-scene")).toBe(scene)
  expect(document.activeElement).toBe(input)
  expect(card("Draft").dataset.linked).toBe("true")
  expect(card("Review").dataset.linked).toBe("true")
  expect(card("Other").dataset.linked).toBe("false")
  expect(card("Review").querySelector(".basic-inside")?.getAttribute("aria-label"))
    .toBe("Step connections in Check before sending")
})

test.each([false, true])("a focused wire still follows its connection after a title edit (expanded: %s)", open => {
  if (open) toggle("Review").click()
  const wire = () => host.querySelector<SVGElement>(".basic-connection")!
  wire().focus()
  expect(document.activeElement).toBe(wire())
  handle.update(initialStage([source, { ...task("Review"), title: "Check before sending" }, task("Other")]))
  expect(document.activeElement).toBe(wire())
  expect(wire().dataset.active).toBe("true")
  expect(card("Draft").dataset.linked).toBe("true")
  expect(card("Other").dataset.linked).toBe("false")
  document.activeElement!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
  expect(document.activeElement).toBe(card("Review").querySelector('[data-port="input"]'))
  expect(card("Review").dataset.open).toBe(String(open))
})

test("a one-step task nothing is connected to leaves out the picture that says only that", () => {
  // "Start → 1 step → End run" on every quiet card said the same thing eleven
  // times and made each card half again as tall. Expanded, it is still there.
  const single = task("Single")
  single.shape.nodes = [{ ...single.shape.nodes[0], next: null }]
  handle.update(initialStage([source, task("Review"), task("Other"), single]))

  expect(card("Single").querySelector<HTMLElement>(".basic-inside")!.hidden).toBe(true)
  // Connected, the picture holds the ends its wires attach to; several steps
  // are worth the summary.
  expect(card("Draft").querySelector<HTMLElement>(".basic-inside")!.hidden).toBe(false)
  expect(card("Other").querySelector<HTMLElement>(".basic-inside")!.hidden).toBe(false)

  toggle("Single").click()
  expect(card("Single").querySelector<HTMLElement>(".basic-inside")!.hidden).toBe(false)
})
