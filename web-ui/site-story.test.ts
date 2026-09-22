import { afterEach, beforeEach, expect, it, vi } from "vitest"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

const site = resolve(process.cwd(), "../site")
let motion: EventTarget & { matches: boolean }

beforeEach(() => {
  vi.useFakeTimers()
  motion = Object.assign(new EventTarget(), { matches: false })
  vi.stubGlobal("matchMedia", () => motion)
})

function load(enhance = true) {
  const page = new DOMParser().parseFromString(readFileSync(resolve(site, "index.html"), "utf8"), "text/html")
  document.body.innerHTML = page.body.innerHTML
  if (enhance) {
    expect(page.querySelector('script[src="story.js"][defer]')).not.toBeNull()
    new Function(readFileSync(resolve(site, "story.js"), "utf8"))()
  }
}

afterEach(() => {
  window.dispatchEvent(new Event("pagehide"))
  document.body.innerHTML = ""
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

it("keeps the complete example readable when JavaScript is unavailable", () => {
  load(false)
  const panels = [...document.querySelectorAll<HTMLElement>(".story-panel")]
  expect(panels).toHaveLength(3)
  expect(panels.every(panel => !panel.hidden)).toBe(true)
  expect(document.querySelector<HTMLElement>(".story-tabs")?.hidden).toBe(true)
  expect(document.querySelector<HTMLElement>(".story-playback")?.hidden).toBe(true)
  expect(document.querySelector("#story")?.textContent).toContain("Scripted example")
})

const play = () => document.querySelector<HTMLButtonElement>(".story-play")!
const selectedPanel = () => document.querySelector('[role="tab"][aria-selected="true"]')?.getAttribute("aria-controls")
const revealedRecords = () => [...document.querySelectorAll<HTMLLIElement>(".run-record li")].filter(row => !row.hasAttribute("data-pending"))

it("plays one finite scripted example on request, reveals its records, and can replay without moving focus", () => {
  load()
  vi.advanceTimersByTime(30000)
  expect(selectedPanel()).toBe("story-task")
  play().focus()
  play().click()
  expect(play().textContent).toContain("Stop example")
  vi.advanceTimersByTime(2400)
  expect(selectedPanel()).toBe("story-run")
  expect(revealedRecords()).toHaveLength(1)
  vi.advanceTimersByTime(1800)
  expect(revealedRecords()).toHaveLength(2)
  vi.advanceTimersByTime(1800)
  expect(revealedRecords()).toHaveLength(3)
  vi.advanceTimersByTime(2400)
  expect(selectedPanel()).toBe("story-change")
  expect(play().textContent).toContain("Replay example")
  expect(document.querySelector('[role="status"]')?.textContent).toContain("Ready to review")
  expect(document.activeElement).toBe(play())
  expect(vi.getTimerCount()).toBe(0)
  play().click()
  expect(selectedPanel()).toBe("story-task")
  vi.advanceTimersByTime(2400)
  expect(revealedRecords()).toHaveLength(1)
})

it.each(["stop", "tab", "keyboard", "content", "hidden", "pagehide"])("cancels playback on %s and leaves the example readable", action => {
  load()
  play().click()
  vi.advanceTimersByTime(2400)
  if (action === "stop") play().click()
  if (action === "tab") document.getElementById("tab-task")!.click()
  if (action === "keyboard") document.getElementById("tab-run")!.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight" }))
  if (action === "content") document.getElementById("story-run")!.focus()
  if (action === "hidden") {
    vi.spyOn(document, "hidden", "get").mockReturnValue(true)
    document.dispatchEvent(new Event("visibilitychange"))
  }
  if (action === "pagehide") window.dispatchEvent(new Event("pagehide"))
  const stoppedAt = selectedPanel()
  vi.advanceTimersByTime(30000)
  expect(selectedPanel()).toBe(stoppedAt)
  expect(play().textContent).toContain("Replay example")
  expect(revealedRecords()).toHaveLength(3)
  expect(vi.getTimerCount()).toBe(0)
})

it("lets reduced-motion visitors advance at their own pace, including when the preference changes during playback", () => {
  motion.matches = true
  load()
  expect(play().textContent).toContain("Next step")
  play().click()
  expect(selectedPanel()).toBe("story-run")
  expect(revealedRecords()).toHaveLength(3)
  vi.advanceTimersByTime(30000)
  expect(selectedPanel()).toBe("story-run")
  play().click()
  expect(selectedPanel()).toBe("story-change")
  play().click()
  expect(selectedPanel()).toBe("story-task")
  motion.matches = false
  motion.dispatchEvent(new Event("change"))
  play().click()
  vi.advanceTimersByTime(2400)
  motion.matches = true
  motion.dispatchEvent(new Event("change"))
  expect(play().textContent).toContain("Next step")
  expect(revealedRecords()).toHaveLength(3)
  expect(vi.getTimerCount()).toBe(0)
})

it("switches between the task, run and change with matching accessible tabs", () => {
  load()
  const tabs = [...document.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
  expect(tabs).toHaveLength(3)
  for (const tab of tabs) {
    tab.click()
    expect(tabs.filter(t => t.getAttribute("aria-selected") === "true")).toEqual([tab])
    expect(tabs.filter(t => t.tabIndex === 0)).toEqual([tab])
    const panels = [...document.querySelectorAll<HTMLElement>('[role="tabpanel"]')]
    expect(panels.filter(panel => !panel.hidden).map(panel => panel.id)).toEqual([tab.getAttribute("aria-controls")])
    // Inactive panels keep their layout space, but must never accept input.
    expect(panels.filter(panel => !panel.inert).map(panel => panel.id)).toEqual([tab.getAttribute("aria-controls")])
    expect(document.getElementById(tab.getAttribute("aria-controls")!)?.getAttribute("aria-labelledby")).toBe(tab.id)
  }
})

it("supports arrow keys, Home and End without moving focus outside the example", () => {
  load()
  const tabs = [...document.querySelectorAll<HTMLButtonElement>('[role="tab"]')]
  tabs[0].focus()
  const key = (value: string) => document.activeElement?.dispatchEvent(new KeyboardEvent("keydown", { key: value, bubbles: true }))
  key("ArrowLeft")
  expect(document.activeElement).toBe(tabs[2])
  expect(tabs[2].getAttribute("aria-selected")).toBe("true")
  key("ArrowRight")
  expect(document.activeElement).toBe(tabs[0])
  key("End")
  expect(document.activeElement).toBe(tabs[2])
  key("Home")
  expect(document.activeElement).toBe(tabs[0])
  key("ArrowRight")
  expect(document.activeElement).toBe(tabs[1])
  const pageHome = new KeyboardEvent("keydown", { key: "Home", ctrlKey: true, bubbles: true, cancelable: true })
  tabs[1].dispatchEvent(pageHome)
  expect(pageHome.defaultPrevented).toBe(false)
  expect(tabs[1].getAttribute("aria-selected")).toBe("true")
})
