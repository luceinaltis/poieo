/**
 * Saying the work in one's own words, and getting a card back.
 *
 * The form asks for a name, a folder and a prompt, and a reader who has
 * never written a card does not know what goes in any of them. This is the
 * conversation above the fields: the person describes the work, a model
 * answers, and when it proposes a card the person can put that card on the
 * form -- where it is read, changed, and saved through the same save as
 * before. The conversation writes nothing and is kept nowhere.
 */

import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const draftTask = vi.hoisted(() => vi.fn<typeof import("../api").draftTask>())
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  draftTask,
}))

import { Describe } from "./Describe"
import type { TaskDraft } from "../api"

let host: HTMLDivElement
let root: Root
const card: TaskDraft = { name: "nightly test fix", folder: "../src", prompt: "Run the tests.", schedule: "0 2 * * *" }

beforeEach(() => {
  draftTask.mockReset()
  draftTask.mockResolvedValue({ ok: true, reply: "Which folder should it work in?", draft: null, model: "fake/m1" })
  host = document.createElement("div")
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

function show(onDraft: (draft: TaskDraft) => void = () => {}) {
  act(() => {
    root.render(<Describe project="board" onDraft={onDraft} />)
  })
}

const box = () => host.querySelector<HTMLTextAreaElement>('textarea[aria-label="Describe the work"]')!
const ask = () => host.querySelector<HTMLButtonElement>('[data-do="describe"]')!

function say(text: string) {
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!
    setter.call(box(), text)
    box().dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function send() {
  await act(async () => {
    ask().click()
  })
}

test("a message goes to the daemon with the conversation so far, and the reply is shown", async () => {
  show()
  say("every night run the tests and fix one failure")
  await send()

  expect(draftTask).toHaveBeenCalledWith("board", [
    { role: "user", content: "every night run the tests and fix one failure" },
  ])
  expect(host.textContent).toContain("every night run the tests and fix one failure")
  expect(host.textContent).toContain("Which folder should it work in?")
  // The box is empty again for the next message.
  expect(box().value).toBe("")

  say("src")
  await send()
  expect(draftTask).toHaveBeenLastCalledWith("board", [
    { role: "user", content: "every night run the tests and fix one failure" },
    { role: "assistant", content: "Which folder should it work in?" },
    { role: "user", content: "src" },
  ])
  expect(host.textContent).toContain("fake/m1")
})

test("a reply carrying a card offers it, and pressing it hands the card over", async () => {
  draftTask.mockResolvedValue({ ok: true, reply: "Here is a card for that.", draft: card, model: "fake/m1" })
  const taken = vi.fn()
  show(taken)
  say("fix the tests in src every night")
  await send()

  const use = host.querySelector<HTMLButtonElement>('[data-do="use-draft"]')!
  expect(use).not.toBeNull()
  expect(host.textContent).toContain("nightly test fix")
  expect(host.textContent).toContain("Run the tests.")
  await act(async () => use.click())
  expect(taken).toHaveBeenCalledWith(card)
})

test("a reply without a card offers nothing to press", async () => {
  show()
  say("help")
  await send()

  expect(host.querySelector('[data-do="use-draft"]')).toBeNull()
})

test("a refusal stays on screen and the message stays in the box", async () => {
  draftTask.mockResolvedValue({ ok: false, error: "task_writer could not answer" })
  show()
  say("fix the tests")
  await send()

  expect(host.querySelector('[role="alert"]')?.textContent).toContain("task_writer could not answer")
  expect(box().value).toBe("fix the tests")
  // Nothing was said in reply, so the next message is still the first turn.
  draftTask.mockResolvedValue({ ok: true, reply: "Now I can.", draft: null, model: "fake/m1" })
  await send()
  expect(draftTask).toHaveBeenLastCalledWith("board", [{ role: "user", content: "fix the tests" }])
  expect(host.querySelector('[role="alert"]')).toBeNull()
})

test("nothing is sent while the box is blank, and Enter sends what is there", async () => {
  show()
  expect(ask().disabled).toBe(true)
  say("   ")
  expect(ask().disabled).toBe(true)

  say("tidy the docs")
  expect(ask().disabled).toBe(false)
  await act(async () => {
    box().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
  })
  expect(draftTask).toHaveBeenCalledTimes(1)

  // Shift+Enter is a new line, not a send.
  say("more")
  await act(async () => {
    box().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }))
  })
  expect(draftTask).toHaveBeenCalledTimes(1)
})
