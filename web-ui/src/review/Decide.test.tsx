import { act } from "react"
import type { ComponentProps } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const accept = vi.hoisted(() => vi.fn<typeof import("../api").accept>())
const discard = vi.hoisted(() => vi.fn<typeof import("../api").discard>())
vi.mock("../api", () => ({ accept, discard }))

import type { Decision } from "../api"
import { Decide } from "./Decide"

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  accept.mockReset()
  discard.mockReset()
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

function render(props: Partial<ComponentProps<typeof Decide>> = {}) {
  act(() => {
    root.render(
      <Decide project="board"
        task="chores" pending={3} into="main" runId={null} onDone={() => {}} {...props} />,
    )
  })
}

const button = (name: string) => container.querySelector<HTMLElement>(`[data-do="${name}"]`)!

test("the accept preview says what it would add to", () => {
  render()

  // The one place the tool's own words are allowed: this line is about the
  // reader's repository, not about poieo.
  expect(button("accept").textContent).toContain("adds 3 commits to main")
})

test("accept posts once and reports back", async () => {
  accept.mockResolvedValue({ ok: true, accepted: 3 })
  const done = vi.fn()
  render({ onDone: done })

  await act(async () => button("accept").click())

  expect(accept).toHaveBeenCalledTimes(1)
  expect(accept).toHaveBeenCalledWith("board", "chores", undefined)
  expect(done).toHaveBeenCalledTimes(1)
})

test("a double click cannot post twice", async () => {
  let release: (value: Decision) => void = () => {}
  accept.mockReturnValue(new Promise<Decision>((resolve) => (release = resolve)))
  render()

  await act(async () => button("accept").click())
  expect(button("accept").hasAttribute("disabled")).toBe(true)
  await act(async () => button("accept").click())

  expect(accept).toHaveBeenCalledTimes(1)
  await act(async () => release({ ok: true, accepted: 3 }))
})

test("a dirty project is explained, and nothing is claimed to have happened", async () => {
  accept.mockResolvedValue({ ok: false, dirty: ["README.md", "notes.md"] })
  const done = vi.fn()
  render({ onDone: done })

  await act(async () => button("accept").click())

  expect(container.textContent).toContain("README.md")
  expect(container.textContent).toContain("notes.md")
  expect(done).not.toHaveBeenCalled()
})

test("a conflict names the files and offers no resolve button", async () => {
  accept.mockResolvedValue({ ok: false, conflict: ["shared.py"] })
  render()

  await act(async () => button("accept").click())

  expect(container.textContent).toContain("shared.py")
  expect(container.textContent).toMatch(/you changed/i)
  // Resolving belongs in the reader's own tools, not in a review page.
  expect(container.textContent).not.toMatch(/resolve/i)
})

test("discard asks first, and does not promise the change is gone forever", async () => {
  discard.mockResolvedValue({ ok: true, discarded: 3 })
  render()

  await act(async () => button("discard").click())
  expect(discard).not.toHaveBeenCalled()
  expect(container.textContent).toMatch(/throw/i)
  expect(container.textContent).not.toMatch(/forever|permanent|cannot be undone/i)

  await act(async () => button("discard-confirm").click())
  expect(discard).toHaveBeenCalledWith("board", "chores", undefined)
})

test("the per-run controls act from and up to that run", async () => {
  accept.mockResolvedValue({ ok: true, accepted: 1 })
  render({ runId: "r7", pending: 0, into: null })

  expect(button("accept").textContent).toMatch(/up to/i)
  expect(button("discard").textContent).toMatch(/from/i)

  await act(async () => button("accept").click())
  expect(accept).toHaveBeenCalledWith("board", "chores", "r7")
})

test("the buttons call a run a run", () => {
  // DESIGN principle 7: one word for one thing. These buttons used to say
  // "this work" for what the files, the CLI and the log all call a run.
  render()
  expect(button("accept").textContent).toContain("accept this run")
  expect(button("discard").textContent).toContain("discard this run")

  render({ runId: "r7", pending: 0, into: null })
  expect(button("accept").textContent).toContain("up to this run")
  expect(button("discard").textContent).toContain("from this run onward")
  expect(container.textContent ?? "").not.toMatch(/\bwork\b/i)
})

test("nothing waiting means nothing to decide", () => {
  render({ pending: 0 })
  expect(container.querySelector('[data-do="accept"]')).toBeNull()
})
