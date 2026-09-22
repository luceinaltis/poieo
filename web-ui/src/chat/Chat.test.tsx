/**
 * The chat is a conversation with the project, and a conversation is a task:
 * each message starts one of its runs, and the runs that share a thread are
 * the conversation. So the thread is read from the task's own run records,
 * what the model does while it answers is that run's live timeline, and a
 * past conversation is there to go back to.
 */

import { act, useState } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const createChatCard = vi.hoisted(() => vi.fn<typeof import("../api").createChatCard>())
const runNow = vi.hoisted(() => vi.fn<typeof import("../api").runNow>())
const leaveDirection = vi.hoisted(() => vi.fn<typeof import("../api").leaveDirection>())
const fetchRunEvents = vi.hoisted(() => vi.fn<typeof import("../api").fetchRunEvents>())
vi.mock("../api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("../api")>()),
  createChatCard,
  runNow,
  leaveDirection,
  fetchRunEvents,
}))

import { Chat } from "./Chat"
import type { Steerable } from "./Chat"
import { initialStage } from "../state/stage"
import type { TaskState } from "../state/stage"
import type { PoieoEvent, RunSummary, TaskRow } from "../types"

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  createChatCard.mockReset()
  createChatCard.mockResolvedValue({ ok: true, task: "chat" })
  runNow.mockReset()
  runNow.mockResolvedValue({ ok: true, status: "starting" })
  leaveDirection.mockReset()
  leaveDirection.mockResolvedValue({ ok: true, status: "delivered" })
  fetchRunEvents.mockReset()
  fetchRunEvents.mockResolvedValue([])
  host = document.createElement("div")
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

const ROW: TaskRow = {
  name: "chat",
  project: "board",
  graph: "chat",
  trigger: "manual",
  status: "waiting",
  holding: false,
  held_because: null,
  enabled: true,
  stale: null,
  current_run_id: null,
  last_run: null,
  pending: 0,
  into: null,
  asking: null,
  then: [],
  shape: { entry: "", nodes: [] },
  chat: true,
}

function chatTask(changes: Partial<TaskState> = {}): TaskState {
  return { ...Object.values(initialStage([ROW]).tasks)[0], ...changes }
}

const ran = (run_id: string, thread: string, message: string, said: string, extra: Partial<RunSummary> = {}): RunSummary => ({
  run_id,
  task: "chat",
  project: "board",
  graph: "chat",
  status: "completed",
  started_at: `2026-09-23T0${run_id.slice(1)}:00:00Z`,
  finished_at: `2026-09-23T0${run_id.slice(1)}:00:05Z`,
  steps: 1,
  iteration: 1,
  trigger: "run now",
  usage: { input_tokens: 0, output_tokens: 0, cache_read_tokens: 0, cache_write_tokens: 0 },
  error: null,
  said,
  message,
  thread,
  ...extra,
})

const frame = (type: string, data: Record<string, unknown> = {}, run_id = "r9"): PoieoEvent => ({
  run_id,
  type,
  at: "2026-09-23T02:00:01Z",
  node_id: "work",
  data,
})

/** The shell's half: it holds which conversation is open. */
function Shell({
  task = null,
  steerable = [],
  initial = null,
  onThread = () => {},
}: {
  task?: TaskState | null
  steerable?: Steerable[]
  initial?: string | null
  onThread?: (thread: string | null) => void
}) {
  const [thread, setThread] = useState<string | null>(initial)
  return (
    <Chat
      project="board"
      chatTask={task}
      thread={thread}
      onThread={(next) => {
        setThread(next)
        onThread(next)
      }}
      onClose={() => {}}
      steerable={steerable}
    />
  )
}

function show(props: Parameters<typeof Shell>[0] = {}) {
  act(() => root.render(<Shell {...props} />))
}

const box = () => host.querySelector<HTMLTextAreaElement>('textarea[aria-label="Message"]')!
const sendButton = () => host.querySelector<HTMLButtonElement>('[data-do="chat-send"]')!
const conversations = () => host.querySelector<HTMLSelectElement>('select[aria-label="Conversation"]')!

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

async function pick(select: HTMLSelectElement, value: string) {
  await act(async () => {
    select.value = value
    select.dispatchEvent(new Event("change", { bubbles: true }))
  })
}

test("it is one of the panels on the right edge, and says a conversation is kept", () => {
  show()
  expect(host.querySelector("aside")?.classList.contains("panel")).toBe(true)
  expect(host.textContent).toContain("kept")
})

test("the first message makes the project's chat, then asks it", async () => {
  const threads: (string | null)[] = []
  show({ onThread: (thread) => threads.push(thread) })

  say("what is in src?")
  await send()
  expect(createChatCard).toHaveBeenCalledWith("board")
  expect(runNow).not.toHaveBeenCalled()
  // Shown as said while the daemon is still picking the card up.
  expect(host.textContent).toContain("what is in src?")

  const [thread] = threads
  expect(thread).toMatch(/^[A-Za-z0-9_-]{1,64}$/)
  await act(async () => root.render(<Shell task={chatTask()} initial={thread} />))
  expect(runNow).toHaveBeenCalledWith("board", "chat", { message: "what is in src?", thread })
})

test("a message in an open conversation continues it", async () => {
  show({ task: chatTask({ runs: [ran("r1", "t-1", "what is here?", "a package")] }), initial: "t-1" })

  say("and the tests?")
  await send()

  expect(runNow).toHaveBeenCalledWith("board", "chat", { message: "and the tests?", thread: "t-1" })
  expect(box().value).toBe("")
})

test("a conversation reads back from its runs, oldest first, each side its own bubble", () => {
  const runs = [ran("r3", "t-1", "and then?", "then this"), ran("r2", "t-2", "other", "elsewhere"), ran("r1", "t-1", "first?", "first answer")]
  show({ task: chatTask({ runs }), initial: "t-1" })

  const turns = [...host.querySelectorAll(".chat-turn")].map((turn) => [
    turn.getAttribute("data-role"),
    turn.querySelector(".chat-said")?.textContent,
  ])
  expect(turns).toEqual([
    ["user", "first?"],
    ["assistant", "first answer"],
    ["user", "and then?"],
    ["assistant", "then this"],
  ])
})

test("past conversations are there to go back to, named by how they began", async () => {
  const runs = [ran("r3", "t-1", "and then?", "then this"), ran("r2", "t-2", "a new question", "an answer"), ran("r1", "t-1", "first?", "first answer")]
  show({ task: chatTask({ runs }) })

  expect([...conversations().options].map((option) => option.textContent)).toEqual([
    "new conversation",
    "first?",
    "a new question",
  ])
  await pick(conversations(), "t-2")
  expect(host.textContent).toContain("an answer")
  expect(host.textContent).not.toContain("first answer")

  await pick(conversations(), "")
  expect(host.querySelector(".chat-turn")).toBeNull()
})

test("while it answers, the reader watches what it says and does, never what it thinks", () => {
  const activity = [
    frame("run_started", { task: "chat", project: "board", input: { message: "look at src", thread: "t-1" } }),
    frame("node_turn", { turn: 1, text: "Reading the package first.", thinking: "hmm", tool_call_count: 1 }),
    frame("node_tool_call", { turn: 1, name: "list_dir", purpose: "See what src holds", result: "a.py", error: false }),
  ]
  show({ task: chatTask({ status: "running", activity, activityRunId: "r9" }), initial: "t-1" })

  expect(host.querySelector('.chat-turn[data-role="user"] .chat-said')?.textContent).toBe("look at src")
  expect(host.textContent).toContain("Reading the package first.")
  expect(host.textContent).toContain("See what src holds")
  expect(host.textContent).not.toContain("hmm")
  expect(host.querySelector('[role="status"]')?.textContent).toContain("working")
})

test("a message while it answers is heard at its next turn", async () => {
  const activity = [frame("run_started", { task: "chat", project: "board", input: { message: "go", thread: "t-1" } })]
  show({ task: chatTask({ status: "running", activity, activityRunId: "r9" }), initial: "t-1" })

  say("skip the tests")
  await send()

  expect(leaveDirection).toHaveBeenCalledWith("board", "chat", "skip the tests")
  expect(runNow).not.toHaveBeenCalled()
})

test("what a past answer did is opened on request, from its run's record", async () => {
  fetchRunEvents.mockResolvedValue([
    frame("node_tool_call", { turn: 1, name: "read_file", purpose: "Read the readme", result: "", error: false }, "r1"),
  ])
  show({ task: chatTask({ runs: [ran("r1", "t-1", "what is this?", "a tool")] }), initial: "t-1" })

  const work = host.querySelector<HTMLDetailsElement>("details.chat-work")!
  await act(async () => {
    work.open = true
    work.dispatchEvent(new Event("toggle"))
  })

  expect(fetchRunEvents).toHaveBeenCalledWith("r1")
  expect(work.textContent).toContain("Read the readme")
})

test("an answer that came back empty, or a run that failed, says so", () => {
  const runs = [
    ran("r2", "t-1", "again", "", { status: "failed", error: "the model did not answer" }),
    ran("r1", "t-1", "hello", ""),
  ]
  show({ task: chatTask({ runs }), initial: "t-1" })

  expect(host.textContent).toContain("the model said nothing")
  expect(host.textContent).toContain("the model did not answer")
})

test("a refusal stays on screen and the message stays in the box", async () => {
  runNow.mockResolvedValue({ ok: false, error: "a run is in flight" })
  show({ task: chatTask(), initial: "t-1" })

  say("hello?")
  await send()

  expect(host.querySelector('[role="alert"]')?.textContent).toContain("in flight")
  expect(box().value).toBe("hello?")
})

test("a chat card that cannot be made says why, and keeps the message", async () => {
  createChatCard.mockResolvedValue({ ok: false, error: "this project already has a task called 'chat'" })
  show()

  say("hello?")
  await send()

  expect(host.querySelector('[role="alert"]')?.textContent).toContain("already has a task")
  expect(box().value).toBe("hello?")
})

test("nothing is sent while the box is blank, and Enter sends what is there", async () => {
  show({ task: chatTask(), initial: "t-1" })
  expect(sendButton().disabled).toBe(true)

  say("hi")
  await act(async () => {
    box().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true }))
  })
  expect(runNow).toHaveBeenCalledWith("board", "chat", { message: "hi", thread: "t-1" })
})

// -- speaking to another running task ------------------------------------------

const running = (activity: PoieoEvent[] = []): Steerable => ({ name: "chores", title: "chores", activity })

test("a running task can be spoken to: its timeline is the thread, and the box sends direction", async () => {
  const activity = [
    frame("run_started", { task: "chores", project: "board" }),
    frame("node_tool_call", { turn: 1, name: "read_file", purpose: "Read the notes", result: "", error: false }),
  ]
  show({ task: chatTask(), steerable: [running(activity)] })
  const target = host.querySelector<HTMLSelectElement>(".chat-target")!
  expect([...target.options].map((option) => option.textContent)).toEqual(["this conversation", "chores · running"])

  await pick(target, "chores")
  expect(host.textContent).toContain("Read the notes")
  expect(conversations()).toBeNull()

  say("Skip the drafts folder.")
  await send()
  expect(leaveDirection).toHaveBeenCalledWith("board", "chores", "Skip the drafts folder.")
  expect(runNow).not.toHaveBeenCalled()
})

test("when the run it was speaking to ends, the box goes back to the conversation", async () => {
  act(() => root.render(<Shell task={chatTask()} steerable={[running()]} />))
  await pick(host.querySelector<HTMLSelectElement>(".chat-target")!, "chores")

  act(() => root.render(<Shell task={chatTask()} steerable={[]} />))
  await act(async () => {})
  expect(host.querySelector(".chat-target")).toBeNull()
  expect(conversations()).not.toBeNull()
})
