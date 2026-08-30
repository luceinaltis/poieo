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
      <MakeTask
        project="board"
        keepsCopies={props.keepsCopies ?? true}
        onClose={props.onClose ?? (() => {})}
      />,
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

test("it says the work can be thrown away, where that is true", () => {
  show({ keepsCopies: true })
  type("folder", "../work")

  // The reassuring half, and it is not decoration: it is what makes the
  // other half legible as the exception it is.
  expect(host.textContent).toContain("private copy")
  expect(host.textContent).not.toContain("no undo")
})

test("it says there is nothing to undo, before the button that starts it", () => {
  show({ keepsCopies: false })
  type("folder", "../work")

  // The board says this too, on the card -- but by then the task exists and
  // has been running. This is the moment the reader chooses, and until now
  // the only place to find out was afterwards.
  expect(host.textContent).toContain("no undo")
  expect(host.textContent).toContain("not a git repository")
  expect(host.textContent).not.toContain("private copy")
})

test("a saved card is sent as the three things, and says so in place", async () => {
  show()
  type("name", "tidy up")
  type("folder", "../work")
  type("prompt", "look around")

  await act(async () => {
    save().click()
  })

  expect(createTask).toHaveBeenCalledWith("board", "tidy up", "../work", "look around")
  // Said here, not by closing. Closing was the first shape, and it unmounted
  // the panel in the same batch that set the confirmation -- so a save gave
  // no sign at all that anything had happened.
  expect(host.textContent).toContain("tidy-up")
  // And cleared, because the next card is a different card.
  expect(field("prompt").value).toBe("")
})

test("a refusal is shown and the form keeps what was typed", async () => {
  createTask.mockResolvedValue({ ok: false, error: "the folder it would work in is not there" })
  show()
  type("name", "tidy up")
  type("folder", "../gone")
  type("prompt", "look around")

  await act(async () => {
    save().click()
  })

  expect(host.textContent).toContain("is not there")
  // Retyping three fields to fix one of them is the refusal happening twice.
  expect(field("prompt").value).toBe("look around")
})


test("an answer with no task is a refusal, not a card", async () => {
  // A 2xx whose body did not parse arrives as {ok: true} and nothing else.
  // Taken as made it would clear the form over a card that may not exist, and
  // the next press would either duplicate it or be refused.
  createTask.mockResolvedValue({ ok: true })
  show()
  type("name", "tidy up")
  type("folder", "../work")
  type("prompt", "look around")

  await act(async () => {
    save().click()
  })

  expect(host.textContent).toContain("not with a task")
  expect(field("prompt").value).toBe("look around")
})

test("a relative folder says which folder it is relative to", async () => {
  // The server reads it from the project's tasks folder, not the project
  // root. The sentence naming whose files change has to say which `work`.
  show()
  type("folder", "work")
  expect(host.textContent).toContain("tasks folder")

  type("folder", "/tmp/elsewhere")
  expect(host.textContent).not.toContain("tasks folder")
})
