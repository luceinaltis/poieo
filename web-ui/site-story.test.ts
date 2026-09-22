import { afterEach, expect, it } from "vitest"
import { readFileSync } from "node:fs"
import { resolve } from "node:path"

const site = resolve(process.cwd(), "../site")

function load(enhance = true) {
  const page = new DOMParser().parseFromString(readFileSync(resolve(site, "index.html"), "utf8"), "text/html")
  document.body.innerHTML = page.body.innerHTML
  if (enhance) {
    expect(page.querySelector('script[src="story.js"][defer]')).not.toBeNull()
    new Function(readFileSync(resolve(site, "story.js"), "utf8"))()
  }
}

afterEach(() => { document.body.innerHTML = "" })

it("keeps the complete example readable when JavaScript is unavailable", () => {
  load(false)
  const panels = [...document.querySelectorAll<HTMLElement>(".story-panel")]
  expect(panels).toHaveLength(3)
  expect(panels.every(panel => !panel.hidden)).toBe(true)
  expect(document.querySelector<HTMLElement>(".story-tabs")?.hidden).toBe(true)
  expect(document.querySelector("#story")?.textContent).toContain("Scripted example")
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
