/**
 * A picture the model looked at is drawn small beside the call that showed it,
 * so a reader sees what the model saw -- on the call itself, and on the folded
 * line when the call is one of several.
 */

import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test } from "vitest"

import { Timeline } from "./Timeline"
import type { PoieoEvent } from "../types"

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  host = document.createElement("div")
  document.body.appendChild(host)
  root = createRoot(host)
})

afterEach(() => {
  act(() => root.unmount())
  host.remove()
})

const call = (data: Record<string, unknown>): PoieoEvent => ({
  run_id: "r 1",
  type: "node_tool_call",
  at: "2026-09-23T02:00:01Z",
  node_id: "work",
  data: { turn: 1, name: "view_image", purpose: "Look at the screenshot", result: "shot.png", error: false, ...data },
})

test("a picture the model looked at is drawn beside the call", () => {
  act(() => root.render(<Timeline events={[call({ preview: "seen-work-1-shot.png" })]} following={false} />))

  const picture = host.querySelector<HTMLImageElement>("img.drawer-preview")!
  expect(picture.getAttribute("src")).toBe("/api/runs/r%201/files/seen-work-1-shot.png")
  expect(picture.getAttribute("alt")).toBe("Look at the screenshot")
  // In the summary, so it shows with the call folded.
  expect(picture.closest("summary")).not.toBeNull()
})

test("a folded line of calls shows the pictures they looked at", () => {
  const events = [call({ preview: "seen-work-1-a.png" }), call({ name: "read_file", purpose: "Read notes" })]
  act(() => root.render(<Timeline events={events} following={false} />))

  const group = host.querySelector(".drawer-group > summary")!
  expect(group.querySelectorAll("img.drawer-preview")).toHaveLength(1)
})

test("a call that showed no picture draws none", () => {
  act(() => root.render(<Timeline events={[call({ name: "read_file" })]} following={false} />))

  expect(host.querySelector("img")).toBeNull()
})

test("the chat keeps what the model said between its steps; the drawer folds it into the calls", async () => {
  const { visibleTimelineEvents } = await import("./Timeline")
  const turn: PoieoEvent = {
    run_id: "r1",
    type: "node_turn",
    at: "2026-09-23T02:00:00Z",
    node_id: "work",
    data: { turn: 1, text: "Reading the notes first.", tool_call_count: 1 },
  }
  const events = [turn, call({ name: "read_file" })].map((event) => ({ ...event, run_id: "r1" }))

  expect(visibleTimelineEvents(events).map((event) => event.type)).toEqual(["node_tool_call"])
  expect(visibleTimelineEvents(events, { keepWords: true }).map((event) => event.type)).toEqual([
    "node_turn",
    "node_tool_call",
  ])
})

const asking = (extra: Record<string, unknown> = {}): PoieoEvent => ({
  run_id: "r1",
  type: "node_tool_asking",
  at: "2026-09-23T02:00:02Z",
  node_id: "work",
  data: { turn: 1, call_id: "c1", name: "write_file", kind: "edits", purpose: "Save the fix", ...extra },
})
const answered = (allowed: boolean): PoieoEvent => ({
  run_id: "r1",
  type: "node_tool_answered",
  at: "2026-09-23T02:00:05Z",
  node_id: "work",
  data: { turn: 1, call_id: "c1", allowed },
})

test("a call waiting on a person is offered to them, and their answer goes back by its id", async () => {
  const answers: [string, boolean][] = []
  act(() =>
    root.render(<Timeline events={[asking()]} following onAnswer={(call, allow) => answers.push([call, allow])} />),
  )

  const entry = host.querySelector('[data-kind="asking"]')!
  expect(entry.textContent).toContain("Save the fix")
  expect(entry.textContent).toContain("edit")
  await act(async () => entry.querySelector<HTMLButtonElement>('[data-do="allow"]')!.click())
  await act(async () => entry.querySelector<HTMLButtonElement>('[data-do="deny"]')!.click())
  expect(answers).toEqual([
    ["c1", true],
    ["c1", false],
  ])
})

test("an answered question says what was answered, and offers nothing", () => {
  act(() => root.render(<Timeline events={[asking(), answered(false)]} following onAnswer={() => {}} />))

  const entry = host.querySelector('[data-kind="asking"]')!
  expect(entry.textContent).toContain("not allowed")
  expect(entry.querySelector("button")).toBeNull()
  // The answer is folded into the question, not a line of its own.
  expect(host.querySelectorAll(".drawer-entry")).toHaveLength(1)
})

test("where nobody can answer, a waiting question says it waits", () => {
  act(() => root.render(<Timeline events={[asking()]} following={false} />))

  const entry = host.querySelector('[data-kind="asking"]')!
  expect(entry.textContent).toContain("waiting for a person")
  expect(entry.querySelector("button")).toBeNull()
})
