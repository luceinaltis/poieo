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
const expand = (name: string) => card(name).querySelector<HTMLElement>(".basic-toggle")!.click()

beforeEach(() => {
  host = document.createElement("div")
  document.body.append(host)
  handle = basic.mount(host, { onSelectTask: vi.fn() })
  handle.update(initialStage([source, task("Review"), task("Other")]))
})
afterEach(() => { handle.destroy(); host.remove(); vi.restoreAllMocks() })

test("a handoff joins the sending graph's output to the receiving graph's input", () => {
  expand("Draft")
  expand("Review")
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
  expand("Draft")
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
  // Panning the target into view moves the pointer off the old wire. Input
  // still has focus, so its incoming connection must remain visible.
  connection.dispatchEvent(new Event("pointerleave"))
  expect(connection.dataset.active).toBe("true")
  expect(card("Other").dataset.linked).toBe("false")
})

test("parallel handoffs share one route while retaining their authored priority", () => {
  const parallel = { ...source, then: [
    { to: "Review", label: "urgent" }, { to: "Other", label: "needs changes" },
    { to: "Review", label: "question" }, { to: null, label: "quiet" },
  ] }
  handle.update(initialStage([parallel, task("Review"), task("Other")]))
  expand("Draft")
  expect(host.querySelectorAll(".basic-connection")).toHaveLength(2)
  const sameTarget = host.querySelector('[data-from="demo/Draft"][data-to="demo/Review"]')!
  expect(sameTarget.textContent).toContain("1. urgent")
  expect(sameTarget.textContent).toContain("3. question")
  expect(card("Draft").textContent).toContain("4. quiet")
})

test("changing an upstream route updates an otherwise unchanged receiving card", () => {
  expand("Other")
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
  expand("Draft")
  const before = card("Draft").querySelector(".basic-node")
  const connection = host.querySelector(".basic-connection")
  const next = { ...stage, tasks: { ...stage.tasks, "demo/Other": { ...stage.tasks["demo/Other"], status: "running" as const } } }
  handle.update(next)
  expect(card("Draft").querySelector(".basic-node")).toBe(before)
  expect(host.querySelector(".basic-connection")).toBe(connection)
})

test("same-named tasks in another project never become the input of this connection", () => {
  handle.update(initialStage([source, { ...task("Review"), project: "elsewhere" }]))
  expect(host.querySelector(".basic-connection")).toBeNull()
  expect(host.querySelector('[data-task="elsewhere/Review"] [data-port="input"]')).toBeNull()
})

test("handoffs touch measured graph terminals after the board has been panned and zoomed", () => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (this: HTMLElement) {
    const root = this.closest<HTMLElement>(".basic-task")
    if (!root) return new DOMRect()
    const x = 120 + parseFloat(root.style.left) * 0.6
    const y = -45 + parseFloat(root.style.top) * 0.6
    if (this === root) return new DOMRect(x, y, parseFloat(root.style.width) * 0.6, 400 * 0.6)
    if (this.dataset.port === "output") return new DOMRect(x + 100 * 0.6, y + 300 * 0.6, 100 * 0.6, 44 * 0.6)
    if (this.dataset.port === "input") return new DOMRect(x + 50 * 0.6, y + 160 * 0.6, 60 * 0.6, 24 * 0.6)
    return new DOMRect()
  })
  card("Draft").querySelector<HTMLElement>(".basic-toggle")!.click()
  const socket = host.querySelector(".basic-socket")!
  expect(Number(socket.getAttribute("cx"))).toBeCloseTo(200)
  expect(Number(socket.getAttribute("cy"))).toBeCloseTo(322)
  const tip = host.querySelector(".basic-tip")!.getAttribute("d")!
    .match(/-?\d+(?:\.\d+)?/g)!.map(Number)
  expect(tip[2]).toBeCloseTo(parseFloat(card("Review").style.left) + 50)
  expect(tip[3]).toBeCloseTo(172)
})

test("a route beside a narrow card also clears wider cards in the same column", () => {
  const wide = task("Other")
  wide.then = [{ to: "Review", label: "Ready" }]
  wide.shape.nodes = [{ ...wide.shape.nodes[0], type: "router", branches: [
    { to: null, label: "approved" }, { to: null, label: "changes" }, { to: null, label: "question" },
  ] }]
  handle.update(initialStage([source, task("Review"), wide]))
  expand("Other")
  expect(parseFloat(card("Other").style.width)).toBeGreaterThan(parseFloat(card("Draft").style.width))
  const route = host.querySelector('.basic-connection[data-from="demo/Draft"]')!
  const lane = Number(route.querySelector(".basic-word")!.getAttribute("x"))
  expect(lane).toBeGreaterThan(parseFloat(card("Other").style.left) + parseFloat(card("Other").style.width))
  expect(lane).toBeLessThan(parseFloat(card("Review").style.left))
})

test("a connected graph lets the board handle wheel navigation", () => {
  expand("Draft")
  const board = host.querySelector<HTMLElement>(".basic")!
  const before = board.style.transform
  const wheel = new WheelEvent("wheel", { deltaY: -200, cancelable: true, bubbles: true })
  card("Draft").querySelector(".basic-node")!.dispatchEvent(wheel)
  expect(wheel.defaultPrevented).toBe(true)
  expect(board.style.transform).not.toBe(before)
})

test("following a wide receiving graph brings its Input into a narrow viewport", () => {
  const viewport = host.querySelector<HTMLElement>(".basic-viewport")!
  Object.defineProperty(viewport, "clientWidth", { value: 390 })
  Object.defineProperty(viewport, "clientHeight", { value: 844 })
  const wide = task("Review")
  wide.shape.nodes = [{ ...wide.shape.nodes[0], type: "router", branches:
    Array.from({ length: 8 }, (_, index) => ({ to: null, label: `choice ${index}` })),
  }]
  handle.update(initialStage([source, wide]))
  expand("Review")
  expect(parseFloat(card("Review").style.width)).toBeGreaterThan(390 * 2)
  host.querySelector(".basic-connection")!.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
  const input = card("Review").querySelector<HTMLElement>('[data-port="input"]')!
  const transform = host.querySelector<HTMLElement>(".basic")!.style.transform.match(/-?\d+(?:\.\d+)?/g)!.map(Number)
  const x = transform[0] + (parseFloat(card("Review").style.left) + parseFloat(input.style.left)) * transform[2]
  expect(document.activeElement).toBe(input)
  expect(x).toBeGreaterThan(0)
  expect(x + parseFloat(input.style.width) * transform[2]).toBeLessThan(390)
})

test("leaving a hovered Output restores the connection to the focused Input", () => {
  handle.update(initialStage([source, { ...task("Review"), then: [{ to: "Other", label: "Approved" }] }, task("Other")]))
  card("Review").querySelector<HTMLElement>('[data-port="input"]')!.focus()
  card("Review").querySelector('[data-port="output"]')!.dispatchEvent(new Event("pointerover", { bubbles: true }))
  expect(card("Draft").dataset.linked).toBe("false")
  expect(card("Other").dataset.linked).toBe("true")
  card("Review").dispatchEvent(new Event("pointerleave"))
  expect(card("Draft").dataset.linked).toBe("true")
  expect(card("Other").dataset.linked).toBe("false")
})

test("a wire that skips a column runs straight across when nothing stands in its row", () => {
  // Every card is 150 tall here. Keep → Tell skips column 1, and the only card
  // in column 1 (Mend) is on the row above, so the way across is clear.
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(150)
  const route = (from: string, to: string) =>
    host.querySelector<SVGElement>(`.basic-connection[data-from="demo/${from}"][data-to="demo/${to}"]`)!.dataset.route
  handle.update(initialStage([
    { ...task("Watch"), then: [{ to: "Mend", label: "red" }] },
    { ...task("Mend"), then: [{ to: "Tell", label: "fixed" }] },
    task("Tell"),
    { ...task("Keep"), then: [{ to: "Tell", label: "done" }] },
  ]))

  expect(route("Watch", "Mend")).toBe("across")
  expect(route("Keep", "Tell")).toBe("across")
})

test("a wire that skips a column goes under the board when a card stands in its row", () => {
  vi.spyOn(HTMLElement.prototype, "offsetHeight", "get").mockReturnValue(150)
  const route = (from: string, to: string) =>
    host.querySelector<SVGElement>(`.basic-connection[data-from="demo/${from}"][data-to="demo/${to}"]`)!.dataset.route
  // Watch → Mend → Tell, and Watch → Tell too: Mend sits on Watch's row.
  handle.update(initialStage([
    { ...task("Watch"), then: [{ to: "Mend", label: "red" }, { to: "Tell", label: "green" }] },
    { ...task("Mend"), then: [{ to: "Tell", label: "fixed" }] },
    task("Tell"),
  ]))

  expect(route("Watch", "Tell")).toBe("under")
})

test("a wire says the board's own conditions in words, not as the expression", () => {
  handle.update(initialStage([
    { ...task("Draft"), then: [{ to: "Review", label: "true" }] },
    { ...task("Review"), then: [{ to: "Other", label: "run.status == 'failed'" }] },
    task("Other"),
  ]))
  const words = [...host.querySelectorAll(".basic-connection")].map((c) => c.getAttribute("aria-label"))

  expect(words).toEqual([
    "Draft output → Review input: always",
    "Review output → Other input: failed",
  ])
})

test("a word somebody chose is kept, even one that reads like the board's own condition", () => {
  // "if its answer says true": the label is the word, the condition is not
  // `true`, so the wire must not say "always".
  handle.update(initialStage([
    { ...task("Draft"), then: [{ to: "Review", label: "true", when: "'true' in str(run.outputs).lower()" }] },
    { ...task("Review"), then: [{ to: "Other", label: "true", when: "true" }] },
    task("Other"),
  ]))
  const words = [...host.querySelectorAll(".basic-connection")].map((c) => c.getAttribute("aria-label"))

  expect(words).toEqual([
    "Draft output → Review input: true",
    "Review output → Other input: always",
  ])
})
