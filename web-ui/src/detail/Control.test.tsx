import { act } from "react"
import type { ComponentProps } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const pause = vi.hoisted(() => vi.fn<typeof import("../api").pause>())
const resume = vi.hoisted(() => vi.fn<typeof import("../api").resume>())
const runNow = vi.hoisted(() => vi.fn<typeof import("../api").runNow>())
vi.mock("../api", () => ({ pause, resume, runNow }))

import type { ControlAnswer } from "../api"
import { Control } from "./Control"

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  pause.mockReset()
  resume.mockReset()
  runNow.mockReset()
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

function render(props: Partial<ComponentProps<typeof Control>> = {}) {
  act(() => {
    root.render(<Control project="board" task="chores" status="waiting" onActed={() => {}} {...props} />)
  })
}

const button = (name: string) => container.querySelector<HTMLElement>(`[data-do="${name}"]`)

test("a waiting task offers pause, and the toggle sends it", async () => {
  pause.mockResolvedValue({ ok: true, status: "paused" })
  const acted = vi.fn()
  render({ onActed: acted })

  expect(button("resume")).toBeNull()
  await act(async () => button("pause")!.click())

  expect(pause).toHaveBeenCalledWith("board", "chores")
  expect(resume).not.toHaveBeenCalled()
  expect(acted).toHaveBeenCalledTimes(1)
})

test("a paused task offers resume, and the toggle sends it", async () => {
  resume.mockResolvedValue({ ok: true, status: "waiting" })
  render({ status: "paused" })

  expect(button("pause")).toBeNull()
  await act(async () => button("resume")!.click())

  expect(resume).toHaveBeenCalledWith("board", "chores")
  expect(pause).not.toHaveBeenCalled()
})

test("run now fires, and is disabled while the task is running", async () => {
  runNow.mockResolvedValue({ ok: true, status: "starting" })
  render()

  await act(async () => button("run-now")!.click())
  expect(runNow).toHaveBeenCalledWith("board", "chores")

  render({ status: "running" })
  expect(button("run-now")!.hasAttribute("disabled")).toBe(true)
})

test("pause stays offered while running -- it takes effect between runs", () => {
  render({ status: "running" })
  expect(button("pause")).not.toBeNull()
  expect(button("pause")!.hasAttribute("disabled")).toBe(false)
})

test("a refusal is shown, not swallowed", async () => {
  runNow.mockResolvedValue({ ok: false, error: "a run is in flight" })
  const acted = vi.fn()
  render({ onActed: acted })

  await act(async () => button("run-now")!.click())

  expect(container.textContent).toContain("a run is in flight")
  expect(acted).not.toHaveBeenCalled()
})

test("a double click cannot post twice", async () => {
  let release: (value: ControlAnswer) => void = () => {}
  pause.mockReturnValue(new Promise<ControlAnswer>((resolve) => (release = resolve)))
  render()

  await act(async () => button("pause")!.click())
  expect(button("pause")!.hasAttribute("disabled")).toBe(true)
  await act(async () => button("pause")!.click())

  expect(pause).toHaveBeenCalledTimes(1)
  await act(async () => release({ ok: true, status: "paused" }))
})

test("a task its card switched off offers no button, and says why", () => {
  // Every verb here is refused by the daemon on such a task, and a button that
  // is always refused is worse than no button.
  render({ status: "paused", enabled: false })

  expect(button("pause")).toBeNull()
  expect(button("resume")).toBeNull()
  expect(button("run-now")).toBeNull()
  expect(container.textContent).toContain("enabled: true")
})
