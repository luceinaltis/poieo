import { act } from "react"
import { createRoot } from "react-dom/client"
import { expect, test, vi } from "vitest"
import { Direction } from "./Direction"

test("direction is optional and saves for the next run", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "saved" }) })
  vi.stubGlobal("fetch", fetch)
  const host = document.createElement("div")
  const root = createRoot(host)
  try {
    await act(async () => root.render(<Direction project="board" task="chores" />))
    expect(fetch).not.toHaveBeenCalled()
    expect(host.querySelector("button")!.disabled).toBe(true)
    await act(async () => {
      const area = host.querySelector("textarea")!
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(area, "Keep the heading")
      area.dispatchEvent(new Event("input", { bubbles: true }))
    })
    await act(async () => host.querySelector("button")!.click())
    expect(fetch).toHaveBeenCalledTimes(1)
    expect(fetch.mock.calls[0][0]).toBe("/api/tasks/board/chores/note")
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ text: "Keep the heading" })
    expect(host.textContent).toContain("Saved for the next run")
  } finally {
    act(() => root.unmount())
    vi.unstubAllGlobals()
  }
})

test("direction given to a run in flight says it was delivered, not saved", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ status: "delivered" }) })
  vi.stubGlobal("fetch", fetch)
  const host = document.createElement("div")
  const root = createRoot(host)
  try {
    await act(async () => root.render(<Direction project="board" task="chores" />))
    await act(async () => {
      const area = host.querySelector("textarea")!
      Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(area, "Skip the drafts folder")
      area.dispatchEvent(new Event("input", { bubbles: true }))
    })
    await act(async () => host.querySelector("button")!.click())
    expect(host.textContent).toContain("Delivered to the run in flight")
    expect(host.textContent).not.toContain("Saved for the next run")
  } finally {
    act(() => root.unmount())
    vi.unstubAllGlobals()
  }
})

test("its fold opens like the panel's other folds", async () => {
  // It alone kept the browser's own triangle beside the others' chevron.
  const host = document.createElement("div")
  const root = createRoot(host)
  await act(async () => root.render(<Direction project="board" task="chores" />))
  expect(host.querySelector("details")!.classList.contains("drawer-card")).toBe(true)
  act(() => root.unmount())
})
