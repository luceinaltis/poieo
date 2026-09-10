import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const createTask = vi.hoisted(() => vi.fn<typeof import("../api").createTask>())
vi.mock("../api", async (original) => ({
  ...(await original<typeof import("../api")>()), createTask,
}))

import { MakeTask } from "./MakeTask"

let host: HTMLDivElement
let root: Root
beforeEach(() => {
  createTask.mockReset().mockResolvedValue({ ok: true, task: "review" })
  host = document.createElement("div")
  document.body.append(host)
  root = createRoot(host)
  act(() => root.render(<MakeTask project="board" keepsCopies onClose={() => {}} />))
})
afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

function button(label: string) {
  const found = [...host.querySelectorAll("button")].find(b => b.textContent === label)
  expect(found, `button: ${label}`).toBeTruthy()
  return found!
}

async function click(label: string) {
  await act(async () => button(label).click())
}

function fill(selector: string, value: string) {
  const field = host.querySelector<HTMLInputElement | HTMLTextAreaElement | HTMLSelectElement>(selector)!
  expect(field, selector).toBeTruthy()
  act(() => {
    const prototype = field instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype
      : field instanceof HTMLSelectElement ? HTMLSelectElement.prototype : HTMLInputElement.prototype
    Object.getOwnPropertyDescriptor(prototype, "value")!.set!.call(field, value)
    field.dispatchEvent(new Event(field instanceof HTMLSelectElement ? "change" : "input", { bubbles: true }))
  })
}

async function start() {
  fill('[name="name"]', "review")
  fill('[name="folder"]', "../work")
  fill('[name="prompt"]', "Draft an answer")
  await click("Write as steps")
}

test("a prompt grows into connected steps without retyping it", async () => {
  await start()
  await click("Add step")
  fill('[aria-label="Instructions for Step 2"]', "Review the draft")
  await click("Insert result from Step 1")
  await click("save without starting")
  expect(createTask).toHaveBeenCalledWith("board", "review", "../work", expect.objectContaining({
    entry: "step_1",
    nodes: [
      expect.objectContaining({ id: "step_1", type: "agent", prompt: "Draft an answer", next: "step_2" }),
      expect.objectContaining({ id: "step_2", prompt: "Review the draft\n\n{{ step_1 }}", output: { as: "step_2" } }),
    ],
  }), false)
  expect(host.textContent).toContain("switched off")
})

test("a condition is written by picking a result, comparison, and next step", async () => {
  await start()
  await click("Add condition")
  fill('[aria-label="Comparison for condition 1 in Step 2"]', "in")
  fill('[aria-label="Value for condition 1 in Step 2"]', 'try "again"')
  fill('[aria-label="Next step for condition 1 in Step 2"]', "step_1")
  await click("save without starting")
  expect(createTask).toHaveBeenCalledWith("board", "review", "../work", expect.objectContaining({
    max_steps: 100,
    nodes: expect.arrayContaining([expect.objectContaining({
      type: "router", branches: [{ when: '"try \\"again\\"" in step_1', to: "step_1" }], default: null,
    })]),
  }), false)
})

test("command success compares the numeric exit code, not the output text", async () => {
  await start()
  await click("Add command")
  fill('[aria-label="Command for Step 2"]', "npm test")
  await click("Add condition")
  await click("save without starting")
  expect(createTask).toHaveBeenCalledWith("board", "review", "../work", expect.objectContaining({
    nodes: expect.arrayContaining([expect.objectContaining({
      type: "router", branches: [{ when: "step_2.exit_code == 0", to: null }],
    })]),
  }), false)
})

test("a missing instruction blocks saving and explains which step needs it", async () => {
  await start()
  await click("Add step")
  expect(button("save and start").disabled).toBe(true)
  expect(host.textContent).toContain("Write instructions for Step 2")
  expect(createTask).not.toHaveBeenCalled()
})

test("removing a result used by a condition requires fixing the condition", async () => {
  await start()
  await click("Add command")
  fill('[aria-label="Command for Step 2"]', "npm test")
  await click("Add condition")
  await click("Remove Step 2")
  expect(button("save and start").disabled).toBe(true)
  expect(host.textContent).toContain("Choose a result for the condition in Step 3")
})

test("a refused save keeps every step and condition for another attempt", async () => {
  createTask.mockResolvedValue({ ok: false, error: "the folder is gone" })
  await start()
  await click("Add condition")
  fill('[aria-label="Value for condition 1 in Step 2"]', "approved")
  await click("save without starting")
  expect(host.querySelector<HTMLTextAreaElement>('[aria-label="Instructions for Step 1"]')!.value)
    .toBe("Draft an answer")
  expect(host.querySelector<HTMLInputElement>('[aria-label="Value for condition 1 in Step 2"]')!.value)
    .toBe("approved")
  expect(host.querySelector('[role="alert"]')!.textContent).toContain("folder is gone")
})

test("steps cannot be changed or saved twice while saving", async () => {
  let finish!: (value: { ok: boolean; task: string }) => void
  createTask.mockReturnValue(new Promise(resolve => { finish = resolve }))
  await start()
  await click("Add condition")
  await click("save without starting")
  expect(button("Add step").disabled).toBe(true)
  expect(button("save without starting").disabled).toBe(true)
  expect(host.querySelector<HTMLInputElement>('[aria-label="Value for condition 1 in Step 2"]')!.disabled).toBe(true)
  await act(async () => finish({ ok: true, task: "review" }))
})
