/**
 * The form that writes a card.
 *
 * Three fields and no fourth, which is DESIGN.md's second principle: a name,
 * the folder it works in, and its prompt. What these defend is the folder --
 * it is required, it is never filled in, and the moment before saving says
 * plainly whose files are about to change. That sentence is principle 7's one
 * exception to hiding the machinery, and it is the whole reason a card may be
 * created already running.
 */

import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const createTask = vi.hoisted(() => vi.fn())
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<Record<string, unknown>>()),
  createTask,
}))

import { MakeTask } from "./MakeTask"

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  createTask.mockReset()
  createTask.mockResolvedValue({ ok: true, task: "tidy-up" })
  host = document.createElement("div")
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

function show(props: Partial<Parameters<typeof MakeTask>[0]> = {}) {
  act(() => {
    root.render(
      <MakeTask project="board" onClose={props.onClose ?? (() => {})} onMade={props.onMade ?? (() => {})} />,
    )
  })
}

const field = (name: string) => host.querySelector<HTMLInputElement>(`[name="${name}"]`)!
const save = () => host.querySelector<HTMLButtonElement>('[data-do="make-task"]')!

function type(name: string, value: string) {
  const input = field(name)
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(
      input instanceof HTMLTextAreaElement ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype,
      "value",
    )!.set!
    setter.call(input, value)
    input.dispatchEvent(new Event("input", { bubbles: true }))
  })
}

test("it asks for a name, a folder and a prompt, and nothing else", () => {
  show()
  const named = [...host.querySelectorAll("[name]")].map((node) => node.getAttribute("name"))
  expect(named.sort()).toEqual(["folder", "name", "prompt"])
})

test("saving is refused until the folder has been named", () => {
  show()
  type("name", "tidy up")
  type("prompt", "look around")
  expect(save().disabled).toBe(true)

  type("folder", "../work")
  expect(save().disabled).toBe(false)
})

test("it says whose files are about to change before the button is pressed", () => {
  show()
  type("folder", "../work")
  // Principle 7's one exception: the machinery stays hidden, the moment the
  // reader's own files are about to change does not.
  expect(host.textContent).toContain("../work")
  expect(host.textContent?.toLowerCase()).toContain("files")
})

test("a saved card is sent as the three things and closes the form", async () => {
  const onMade = vi.fn()
  show({ onMade })
  type("name", "tidy up")
  type("folder", "../work")
  type("prompt", "look around")

  await act(async () => {
    save().click()
  })

  expect(createTask).toHaveBeenCalledWith("board", "tidy up", "../work", "look around")
  expect(onMade).toHaveBeenCalledWith("tidy-up")
})

test("a refusal is shown and the form keeps what was typed", async () => {
  createTask.mockResolvedValue({ ok: false, error: "the folder it would work in is not there" })
  const onMade = vi.fn()
  show({ onMade })
  type("name", "tidy up")
  type("folder", "../gone")
  type("prompt", "look around")

  await act(async () => {
    save().click()
  })

  expect(host.textContent).toContain("is not there")
  expect(onMade).not.toHaveBeenCalled()
  // Retyping three fields to fix one of them is the refusal happening twice.
  expect(field("prompt").value).toBe("look around")
})
