import { act } from "react"
import type { ComponentProps } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const fetchCard = vi.hoisted(() => vi.fn<typeof import("../api").fetchCard>())
const connect = vi.hoisted(() => vi.fn<typeof import("../api").connect>())
vi.mock("../api", () => ({ fetchCard, connect }))

import type { Card } from "../api"
import { Next } from "./Next"

let container: HTMLDivElement
let root: Root

const OTHERS = [
  { name: "mend", title: "Mend the suite" },
  { name: "tell", title: "Tell me" },
]

function card(then: Card["then"]): Card {
  return { task: "watch", text: "", name: "watch", folder: "..", prompt: "x", plain: false, enabled: true, then }
}

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  fetchCard.mockReset()
  connect.mockReset()
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

async function open(props: Partial<ComponentProps<typeof Next>> = {}) {
  act(() => {
    root.render(<Next project="board" task="watch" others={OTHERS} {...props} />)
  })
  await act(async () => container.querySelector<HTMLElement>("summary")!.click())
}

const pick = (name: string, value: string) =>
  act(() => {
    const field = container.querySelector<HTMLSelectElement | HTMLInputElement>(`[name="${name}"]`)!
    const setter = Object.getOwnPropertyDescriptor(Object.getPrototypeOf(field), "value")!.set!
    setter.call(field, value)
    field.dispatchEvent(new Event(field.tagName === "SELECT" ? "change" : "input", { bubbles: true }))
  })

const press = (name: string, index = 0) =>
  act(async () => container.querySelectorAll<HTMLButtonElement>(`[data-do="${name}"]`)[index].click())

test("a connection reads as the task it starts and when, in words", async () => {
  fetchCard.mockResolvedValue(card([{ when: "run.status == 'failed'", to: "mend", label: "failed" }]))
  await open()

  expect(fetchCard).toHaveBeenCalledWith("board", "watch")
  const row = container.querySelector(".next-row")!
  expect(row.textContent).toContain("Mend the suite")
  expect(row.textContent).toContain("if it failed")
})

test("connecting sends every connection, the new one last, with a word to draw", async () => {
  fetchCard.mockResolvedValue(card([{ when: "true", to: "tell", label: null }]))
  connect.mockResolvedValue({ ok: true, task: "watch", live: true })
  const connected = vi.fn()
  await open({ onConnected: connected })

  pick("next-task", "mend")
  pick("next-when", "says")
  pick("next-word", "RED")
  await press("connect")

  expect(connect).toHaveBeenCalledWith("board", "watch", [
    { when: "true", to: "tell", label: null },
    { when: "'red' in str(run.outputs).lower()", to: "mend", label: "red" },
  ])
  expect(connected).toHaveBeenCalledTimes(1)
  expect(container.querySelectorAll(".next-row")).toHaveLength(2)
})

test("connect waits for a task, and for a word when the condition needs one", async () => {
  fetchCard.mockResolvedValue(card([]))
  await open()
  const connectButton = () => container.querySelector<HTMLButtonElement>('[data-do="connect"]')!

  expect(connectButton().disabled).toBe(true)
  pick("next-task", "mend")
  expect(connectButton().disabled).toBe(false)
  pick("next-when", "says")
  expect(connectButton().disabled).toBe(true)
  pick("next-word", "done")
  expect(connectButton().disabled).toBe(false)
})

test("the task itself is not offered as the next one", async () => {
  fetchCard.mockResolvedValue(card([]))
  await open({ others: [...OTHERS, { name: "watch", title: "Watch" }] })

  const options = [...container.querySelectorAll('[name="next-task"] option')].map((o) => o.getAttribute("value"))
  expect(options).not.toContain("watch")
  expect(options).toContain("mend")
})

test("removing one sends the rest, and a condition the form does not know is kept as it was", async () => {
  const custom = { when: "'GREEN' in summary", to: "tell", label: "green again" }
  fetchCard.mockResolvedValue(card([{ when: "true", to: "mend", label: null }, custom]))
  connect.mockResolvedValue({ ok: true, task: "watch", live: true })
  await open()

  expect(container.querySelectorAll(".next-row")[1].textContent).toContain("green again")
  await press("disconnect", 0)

  expect(connect).toHaveBeenCalledWith("board", "watch", [custom])
  expect(container.querySelectorAll(".next-row")).toHaveLength(1)
})

test("a refusal is said and the connections stay as they were", async () => {
  fetchCard.mockResolvedValue(card([]))
  connect.mockResolvedValue({ ok: false, error: "this project has no task 'mend' to start" })
  await open()

  pick("next-task", "mend")
  await press("connect")

  expect(container.textContent).toContain("no task 'mend'")
  expect(container.querySelectorAll(".next-row")).toHaveLength(0)
})
