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
const leaveDirection = vi.hoisted(() => vi.fn<typeof import("../api").leaveDirection>())
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  chat,
  leaveDirection,
}))

import { Chat, TURNS_AT_MOST } from "./Chat"
import type { Steerable, Turn } from "./Chat"
import type { PoieoEvent } from "../types"

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  chat.mockReset()
  chat.mockResolvedValue({ ok: true, reply: "Four.", model: "fake/m1" })
  leaveDirection.mockReset()
  leaveDirection.mockResolvedValue({ ok: true, status: "delivered" })
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
  steerable = [],
}: {
  initial?: Turn[]
  onTurns?: (turns: Turn[]) => void
  onClose?: () => void
  steerable?: Steerable[]
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
      steerable={steerable}
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

  expect(chat).toHaveBeenCalledWith("board", [{ role: "user", content: "what is 2 + 2?" }], expect.any(Function))
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
  expect(chat).toHaveBeenLastCalledWith(
    "board",
    [
      { role: "user", content: "what is 2 + 2?" },
      { role: "assistant", content: "Four." },
      { role: "user", content: "and one more?" },
    ],
    expect.any(Function),
  )
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
  expect(chat).toHaveBeenLastCalledWith("board", [{ role: "user", content: "hello?" }], expect.any(Function))
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

test("the reply is read as it is written, and the model's thinking is never shown", async () => {
  let release!: () => void
  const next = () => new Promise<void>((resolve) => (release = resolve))
  chat.mockImplementation(async (_project, _messages, onPiece) => {
    onPiece?.({ thinking: "Let me see." })
    await next()
    onPiece?.({ text: "Fo" })
    await next()
    onPiece?.({ text: "ur." })
    await next()
    return { ok: true, reply: "Four.", thinking: "Let me see.", model: "fake/m1" }
  })
  show()
  say("what is 2 + 2?")
  await send()

  // Thinking, and nothing else yet: the reader hears that it is thinking,
  // not what it thinks.
  const arriving = () => host.querySelector<HTMLElement>(".chat-arriving")!
  expect(arriving()).not.toBeNull()
  expect(arriving().querySelector(".chat-thinking")!.textContent).toBe("thinking…")
  expect(arriving().textContent).not.toContain("Let me see.")
  expect(arriving().querySelector(".chat-said")).toBeNull()

  // The first words replace the line and start the bubble.
  await act(async () => release())
  expect(arriving().querySelector(".chat-thinking")).toBeNull()
  expect(arriving().querySelector(".chat-said")!.textContent).toBe("Fo")
  await act(async () => release())
  expect(arriving().querySelector(".chat-said")!.textContent).toBe("Four.")

  // Whole: the turn lands as its words alone.
  await act(async () => release())
  expect(host.querySelector(".chat-arriving")).toBeNull()
  const landed = host.querySelectorAll(".chat-turn")[1]
  expect(landed.querySelector(".chat-said")!.textContent).toBe("Four.")
  expect(landed.querySelector("details")).toBeNull()
  expect(landed.textContent).not.toContain("Let me see.")
})

test("each side has its own bubble", async () => {
  show()
  say("hello?")
  await send()

  const [mine, theirs] = host.querySelectorAll(".chat-turn")
  expect(mine.getAttribute("data-role")).toBe("user")
  expect(theirs.getAttribute("data-role")).toBe("assistant")
})

const running = (activity: PoieoEvent[] = []): Steerable => ({ name: "chores", title: "chores", activity })
const frame = (type: string, data: Record<string, unknown> = {}): PoieoEvent => ({
  run_id: "r1",
  type,
  at: "2026-08-26T02:00:01Z",
  node_id: "work",
  data,
})

test("nothing runs, nothing to pick: the box speaks to the model", () => {
  show()
  expect(host.querySelector(".chat-target")).toBeNull()
})

test("a running task can be spoken to: its timeline is the thread, and the box sends direction", async () => {
  const activity = [
    frame("run_started", { task: "chores", project: "board" }),
    frame("node_turn", { turn: 1, text: "", tool_call_count: 1 }),
    frame("node_tool_call", { turn: 1, name: "read_file", purpose: "Read the notes", arguments: { path: "notes.md" }, result: "", error: false }),
  ]
  show({ steerable: [running(activity)] })
  const picker = host.querySelector<HTMLSelectElement>(".chat-target")!
  expect([...picker.options].map((option) => option.textContent)).toEqual(["this project's model", "chores · running"])

  await act(async () => {
    picker.value = "chores"
    picker.dispatchEvent(new Event("change", { bubbles: true }))
  })
  expect(host.textContent).toContain("its run, live")
  expect(host.textContent).toContain("Read the notes")
  expect(host.querySelector(".chat-turns")).toBeNull()

  say("Skip the drafts folder.")
  await send()
  expect(leaveDirection).toHaveBeenCalledWith("board", "chores", "Skip the drafts folder.")
  expect(chat).not.toHaveBeenCalled()
  expect(box().value).toBe("")
})

test("a run's timeline in the chat shows what the model said and did, not what it thought", async () => {
  const activity = [
    frame("run_started", { task: "chores", project: "board" }),
    frame("node_turn", { turn: 1, text: "Reading the notes first.", thinking: "Hmm, where are they?" }),
    frame("node_turn", { turn: 2, text: "", thinking: "Only thinking this turn." }),
  ]
  show({ steerable: [running(activity)] })
  const picker = host.querySelector<HTMLSelectElement>(".chat-target")!
  await act(async () => {
    picker.value = "chores"
    picker.dispatchEvent(new Event("change", { bubbles: true }))
  })
  expect(host.textContent).toContain("Reading the notes first.")
  expect(host.textContent).not.toContain("Hmm, where are they?")
  expect(host.textContent).not.toContain("Only thinking this turn.")
  expect(host.querySelector(".drawer-thinking")).toBeNull()
})

test("a run that has only thought so far reads as nothing yet, not a blank", async () => {
  const activity = [
    frame("run_started", { task: "chores", project: "board" }),
    frame("node_turn", { turn: 1, text: "", thinking: "Where to begin?" }),
  ]
  show({ steerable: [running(activity)] })
  const picker = host.querySelector<HTMLSelectElement>(".chat-target")!
  await act(async () => {
    picker.value = "chores"
    picker.dispatchEvent(new Event("change", { bubbles: true }))
  })
  expect(host.textContent).toContain("Nothing yet from this run.")
})

test("a refused direction stays on screen with the words still in the box", async () => {
  leaveDirection.mockResolvedValue({ ok: false, error: "this task has no card to keep direction with" })
  show({ steerable: [running()] })
  const picker = host.querySelector<HTMLSelectElement>(".chat-target")!
  await act(async () => {
    picker.value = "chores"
    picker.dispatchEvent(new Event("change", { bubbles: true }))
  })
  say("Stop.")
  await send()
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("no card")
  expect(box().value).toBe("Stop.")
})

test("when the run it was speaking to ends, the box goes back to the model", async () => {
  act(() => root.render(<Shell steerable={[running()]} />))
  const picker = host.querySelector<HTMLSelectElement>(".chat-target")!
  await act(async () => {
    picker.value = "chores"
    picker.dispatchEvent(new Event("change", { bubbles: true }))
  })
  expect(host.textContent).toContain("its run, live")

  act(() => root.render(<Shell steerable={[]} />))
  await act(async () => {})
  expect(host.querySelector(".chat-target")).toBeNull()
  expect(host.textContent).not.toContain("its run, live")
  expect(host.textContent).toContain("nothing is kept")
})

test("a direction still on its way when its run ends is not drawn as a bubble in the model thread", async () => {
  let land: (answer: { ok: true; status: "delivered" | "saved" }) => void = () => {}
  leaveDirection.mockReturnValue(new Promise((resolve) => { land = resolve }))
  act(() => root.render(<Shell steerable={[running()]} />))
  const picker = host.querySelector<HTMLSelectElement>(".chat-target")!
  await act(async () => {
    picker.value = "chores"
    picker.dispatchEvent(new Event("change", { bubbles: true }))
  })
  say("Skip the drafts folder.")
  await send()
  expect(sendButton().textContent).toBe("sending…")

  act(() => root.render(<Shell steerable={[]} />))
  await act(async () => {})
  expect(host.querySelector(".chat-target")).toBeNull()
  expect(host.querySelector(".chat-turns")?.textContent ?? "").not.toContain("Skip the drafts folder.")
  expect(host.querySelector('.chat-turn[data-role="user"]')).toBeNull()

  await act(async () => land({ ok: true, status: "saved" }))
  expect(box().value).toBe("")
  expect(host.querySelector('.chat-turn[data-role="user"]')).toBeNull()
})
