import { act } from "react"
import type { ComponentProps } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const answer = vi.hoisted(() => vi.fn<typeof import("../api").answer>())
vi.mock("../api", () => ({ answer }))

import { Question } from "./Question"
import type { Question as Asked } from "../types"

const ASKED = {
  run_id: "r9",
  question: "Merge #181? It changes a public interface.",
  choices: ["merge", "hold"],
} satisfies Asked

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  answer.mockReset()
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

function render(props: Partial<ComponentProps<typeof Question>> = {}) {
  act(() => {
    root.render(
      <Question
        project="board"
        task="review"
        asking={ASKED}
        onAnswered={() => {}}
        {...props}
      />,
    )
  })
}

const button = (name: string) => container.querySelector<HTMLElement>(`[data-do="${name}"]`)

test("a task waiting on nobody draws nothing at all", () => {
  render({ asking: null })

  expect(container.innerHTML).toBe("")
})

test("the question is shown with a button for each answer offered", () => {
  render()

  expect(container.textContent).toContain("Merge #181")
  expect(button("answer-merge")).not.toBeNull()
  expect(button("answer-hold")).not.toBeNull()
})

test("clicking an answer sends that one, and says the reader acted", async () => {
  answer.mockResolvedValue({ ok: true, status: "answered", answer: "hold" })
  const answered = vi.fn()
  render({ onAnswered: answered })

  await act(async () => button("answer-hold")!.click())

  expect(answer).toHaveBeenCalledWith("board", "review", "hold")
  expect(answered).toHaveBeenCalledTimes(1)
})

test("a refusal is shown, with the choices that were offered", async () => {
  // The page may be holding a list drawn before the run asked again.
  answer.mockResolvedValue({
    ok: false,
    error: "'merge' was not offered",
    choices: ["land", "hold"],
  })
  render()

  await act(async () => button("answer-merge")!.click())

  expect(container.textContent).toContain("was not offered")
  expect(container.textContent).toContain("land, hold")
})
