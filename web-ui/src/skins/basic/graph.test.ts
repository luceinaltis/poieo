import { afterEach, beforeEach, expect, test, vi } from "vitest"

import { basic } from "./index"
import { initialStage } from "../../state/stage"
import type { TaskRow } from "../../types"

const task: TaskRow = {
  name: "Review a draft", project: "demo", graph: "review", trigger: "every 1h",
  status: "waiting", holding: false, enabled: true, stale: null,
  current_run_id: null, last_run: null, pending: 0, into: null, asking: null, then: [],
  shape: { entry: "step_1", nodes: [
    { id: "step_1", description: "Review", type: "agent", next: "step_2", default: null,
      branches: [], model: "mock-model", tools: ["files"] },
    { id: "step_2", description: "Ready to finish?", type: "router", next: null, default: "step_3",
      branches: [{ to: null, label: "approved" }], model: null, tools: [] },
    { id: "step_3", description: "Revise", type: "agent", next: "step_1", default: null,
      branches: [], model: "mock-model", tools: [] },
  ] },
}

let host: HTMLDivElement
let handle: ReturnType<typeof basic.mount>
const nativeDialog = Object.getOwnPropertyDescriptors(HTMLDialogElement.prototype)

function button(root: Element, name: string): HTMLButtonElement {
  const found = [...root.querySelectorAll("button")].find(b => (b.getAttribute("aria-label") || b.textContent) === name)
  expect(found, `button named ${name}`).toBeTruthy()
  return found!
}

beforeEach(() => {
  host = document.createElement("div")
  document.body.append(host)
  // jsdom does not provide the native dialog lifecycle.
  Object.defineProperties(HTMLDialogElement.prototype, {
    showModal: { configurable: true, value(this: HTMLDialogElement) { this.open = true } },
    close: { configurable: true, value(this: HTMLDialogElement) {
      this.open = false
      this.dispatchEvent(new Event("close"))
    } },
  })
  handle = basic.mount(host, { onSelectTask: vi.fn() })
  handle.update(initialStage([task]))
})

afterEach(() => {
  handle.destroy()
  host.remove()
  vi.restoreAllMocks()
  for (const name of ["showModal", "close"]) {
    if (nativeDialog[name]) Object.defineProperty(HTMLDialogElement.prototype, name, nativeDialog[name])
    else Reflect.deleteProperty(HTMLDialogElement.prototype, name)
  }
})

test("the graph shows authored names while unnamed steps keep their ids", () => {
  expect(host.querySelector('[data-node="step_1"]')?.textContent).toContain("Review")
  const plain = structuredClone(task)
  delete plain.shape.nodes[0].description
  handle.update(initialStage([plain]))
  expect(host.querySelector('[data-node="step_1"]')?.textContent).toContain("step_1")
})

test("steps open at reading size, can be enlarged, and close back to their opener", () => {
  const opener = button(host, "View steps in Review a draft")
  opener.click()
  const dialog = host.querySelector<HTMLDialogElement>('dialog[open][aria-label="Steps in Review a draft"]')!
  expect(dialog).not.toBeNull()
  for (const name of ["Review", "Ready to finish?", "Revise", "End run"]) expect(dialog.textContent).toContain(name)
  expect(dialog.querySelector('[role="status"]')?.textContent).toBe("100%")
  button(dialog, "Zoom in").click()
  expect(dialog.querySelector('[role="status"]')?.textContent).toBe("125%")
  button(dialog, "Close steps").click()
  expect((dialog as HTMLDialogElement).open).toBe(false)
  expect(document.activeElement).toBe(opener)
})

test("the running step lights up in both views without losing the chosen zoom", () => {
  button(host, "View steps in Review a draft").click()
  const dialog = host.querySelector<HTMLDialogElement>("dialog[open]")!
  button(dialog, "Zoom in").click()
  const before = dialog.querySelector('[data-node="step_1"]')
  const stage = initialStage([task])
  stage.tasks["demo/Review a draft"].status = "running"
  stage.tasks["demo/Review a draft"].currentNode = "step_3"
  handle.update(stage)
  expect(host.querySelector('.basic-node[data-node="step_3"]')?.getAttribute("data-here")).toBe("true")
  expect(dialog.querySelector('[data-node="step_3"]')?.getAttribute("data-here")).toBe("true")
  expect(dialog.querySelector('[data-node="step_1"]')).toBe(before)
  expect(dialog.querySelector('[role="status"]')?.textContent).toBe("125%")
})

test("a removed task closes its steps instead of leaving a stale picture", () => {
  button(host, "View steps in Review a draft").click()
  handle.update(initialStage([]))
  expect(host.querySelector("dialog[open]")).toBeNull()
})
