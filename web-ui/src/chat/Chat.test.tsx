/**
 * Hearing the project's model, beside the board.
 *
 * The models panel says which models this project can reach; this panel is
 * where a person talks to one. The whole conversation goes with each message
 * because the page is the only thing holding it, the reply names the model
 * that answered, and nothing is written or run for it.
 */

import { act, useState } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const chat = vi.hoisted(() => vi.fn<typeof import("../api").chat>())
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  chat,
}))

import { Chat, TURNS_AT_MOST } from "./Chat"
import type { Turn } from "./Chat"

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  chat.mockReset()
  chat.mockResolvedValue({ ok: true, reply: "Four.", model: "fake/m1" })
  host = document.createElement("div")
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

/** The shell's half: it holds the thread, and this stands in for it. */
function Shell({
  initial = [],
  onTurns = () => {},
  onClose = () => {},
}: {
  initial?: Turn[]
  onTurns?: (turns: Turn[]) => void
  onClose?: () => void
}) {
  const [turns, setTurns] = useState<Turn[]>(initial)
  return (
    <Chat
      project="board"
      turns={turns}
      onTurns={(next) => {
        setTurns(next)
        onTurns(next)
      }}
      onClose={onClose}
    />
  )
}

function show(props: Parameters<typeof Shell>[0] = {}) {
  act(() => {
    root.render(<Shell {...props} />)
  })
}

const box = () => host.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')!
const sendButton = () => host.querySelector<HTMLButtonElement>('[data-do="chat-send"]')!

function say(text: string) {
  act(() => {
    const setter = Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!
    setter.call(box(), text)
    box().dispatchEvent(new Event("input", { bubbles: true }))
  })
}

async function send() {
  await act(async () => {
    sendButton().click()
  })
}

test("it is one of the panels on the right edge, not a third geometry", () => {
  show()
  expect(host.querySelector("aside")?.classList.contains("panel")).toBe(true)
  expect(host.textContent).toContain("nothing is kept")
})

test("a message goes with the conversation so far, and the reply is shown under it with its model named", async () => {
  const kept = vi.fn()
  show({ onTurns: kept })
  say("what is 2 + 2?")
  await send()

  expect(chat).toHaveBeenCalledWith("board", [{ role: "user", content: "what is 2 + 2?" }])
  expect(host.textContent).toContain("what is 2 + 2?")
  expect(host.textContent).toContain("Four.")
  expect(host.textContent).toContain("answered by fake/m1")
  // The box is empty again for the next message.
  expect(box().value).toBe("")
  expect(kept).toHaveBeenLastCalledWith([
    { role: "user", content: "what is 2 + 2?" },
    { role: "assistant", content: "Four.", model: "fake/m1" },
  ])

  chat.mockResolvedValue({ ok: true, reply: "Five.", model: "fake/m1" })
  say("and one more?")
  await send()
  expect(chat).toHaveBeenLastCalledWith("board", [
    { role: "user", content: "what is 2 + 2?" },
    { role: "assistant", content: "Four." },
    { role: "user", content: "and one more?" },
  ])
  expect(host.textContent).toContain("Five.")
})

test("a thread the shell hands over is drawn, so a visit elsewhere does not lose it", () => {
  show({
    initial: [
      { role: "user", content: "earlier" },
      { role: "assistant", content: "Yes, earlier.", model: "fake/m1" },
    ],
  })

  expect(host.textContent).toContain("earlier")
  expect(host.textContent).toContain("Yes, earlier.")
  expect(host.textContent).toContain("answered by fake/m1")
})

test("a refusal stays on screen and the message stays in the box", async () => {
  chat.mockResolvedValue({ ok: false, error: "the model did not answer" })
  show()
  say("hello?")
  await send()

  expect(host.querySelector('[role="alert"]')?.textContent).toContain("the model did not answer")
  expect(box().value).toBe("hello?")
  // Nothing was said in reply, so the next message is still the first turn.
  chat.mockResolvedValue({ ok: true, reply: "Hello.", model: "fake/m1" })
  await send()
  expect(chat).toHaveBeenLastCalledWith("board", [{ role: "user", content: "hello?" }])
  expect(host.querySelector('[role="alert"]')).toBeNull()
})

test("nothing is sent while the box is blank, and Enter sends what is there", async () => {
  show()
  expect(sendButton().disabled).toBe(true)
  say("   ")
  expect(sendButton().disabled).toBe(true)

  say("hello?")
  expect(sendButton().disabled).toBe(false)
  await act(async () => {
    box().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
  })
  expect(chat).toHaveBeenCalledTimes(1)

  // Shift+Enter is a new line, not a send; so is the Enter that commits an
  // input method's composition.
  say("more")
  await act(async () => {
    box().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", shiftKey: true, bubbles: true }))
  })
  await act(async () => {
    box().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", isComposing: true, bubbles: true }))
  })
  expect(chat).toHaveBeenCalledTimes(1)
})

test("a new conversation empties the thread, and the shell is told", async () => {
  const kept = vi.fn()
  show({ onTurns: kept })
  say("hello?")
  await send()
  expect(host.textContent).toContain("Four.")

  await act(async () => host.querySelector<HTMLButtonElement>('[data-do="chat-new"]')!.click())

  expect(host.textContent).not.toContain("Four.")
  expect(host.querySelector('[data-do="chat-new"]')).toBeNull()
  expect(kept).toHaveBeenLastCalledWith([])
})

test("at its longest a conversation asks for a new one and sends nothing more", () => {
  const long: Turn[] = Array.from({ length: TURNS_AT_MOST }, (_, i) => ({
    role: i % 2 ? "assistant" : "user",
    content: `turn ${i}`,
  }))
  show({ initial: long })

  expect(host.textContent).toContain("Start a new one")
  expect(box().disabled).toBe(true)
  expect(sendButton().disabled).toBe(true)
})

test("closing is the panel's own button", () => {
  const close = vi.fn()
  show({ onClose: close })
  act(() => host.querySelector<HTMLButtonElement>(".chat-close")!.click())
  expect(close).toHaveBeenCalled()
})

test("a reply that came back empty or cut short says so rather than showing a blank", async () => {
  chat.mockResolvedValue({ ok: true, reply: "", model: "fake/m1", cut_short: true })
  show()
  say("think hard about this")
  await send()

  expect(host.textContent).toContain("the model said nothing")
  expect(host.textContent).toContain("cut short at the model's token limit")

  // A whole answer carries no such note.
  chat.mockResolvedValue({ ok: true, reply: "Done thinking.", model: "fake/m1", cut_short: false })
  say("and now?")
  await send()
  expect(host.querySelectorAll(".chat-cut")).toHaveLength(1)
  expect(host.textContent).toContain("Done thinking.")
})
