import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { afterEach, expect, test, vi } from "vitest"

const SCRIPT = readFileSync(resolve(process.cwd(), "../site/theme.js"), "utf8")

afterEach(() => {
  window.dispatchEvent(new Event("pagehide"))
  vi.useRealTimers()
  vi.restoreAllMocks()
  localStorage.clear()
  vi.unstubAllGlobals()
})

test("the saved theme controls the page and browser colour, while Auto follows the local day", () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date(2026, 8, 13, 5, 59, 30))
  const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false)
  document.head.innerHTML = '<meta name="theme-color" content="">'
  for (const file of ["index.html", "docs.html"]) {
    const page = new DOMParser().parseFromString(readFileSync(resolve(process.cwd(), "../site", file), "utf8"), "text/html")
    const picker = page.querySelector<HTMLSelectElement>("#theme-mode")!
    expect(picker).not.toBeNull()
    expect(picker.getAttribute("aria-label")).toBe("Color theme")
    expect(Array.from(picker.options, option => [option.value, option.text])).toEqual([
      ["auto", "Auto"], ["light", "Light"], ["dark", "Dark"],
    ])
    document.body.innerHTML = page.body.innerHTML
  }
  localStorage.setItem("poieo.theme", "light")
  vi.advanceTimersByTime(0)
  vi.stubGlobal("matchMedia", () => ({ matches: false }))

  new Function(SCRIPT)()
  document.dispatchEvent(new Event("DOMContentLoaded", { bubbles: true }))

  const picker = document.getElementById("theme-mode") as HTMLSelectElement
  const choose = (mode: string) => {
    picker.value = mode
    picker.dispatchEvent(new Event("change"))
    vi.advanceTimersByTime(0)
  }
  expect(document.documentElement.dataset.theme).toBe("light")
  expect(picker.value).toBe("light")
  expect(picker.hidden).toBe(false)
  expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe("#f8f5ef")

  choose("dark")
  expect(document.documentElement.dataset.theme).toBe("dark")
  expect(localStorage.getItem("poieo.theme")).toBe("dark")
  expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe("#100e0c")
  expect(vi.getTimerCount()).toBe(0)

  choose("auto")
  expect(localStorage.getItem("poieo.theme")).toBe("auto")
  expect(document.documentElement.dataset.theme).toBe("dark")
  expect(vi.getTimerCount()).toBe(1)
  vi.advanceTimersByTime(30_000)
  expect(document.documentElement.dataset.theme).toBe("light")
  expect(picker.value).toBe("auto")
  expect(vi.getTimerCount()).toBe(1)

  vi.setSystemTime(new Date(2026, 8, 13, 17, 59, 59))
  window.dispatchEvent(new Event("pageshow"))
  expect(document.documentElement.dataset.theme).toBe("light")
  vi.advanceTimersByTime(1_000)
  expect(document.documentElement.dataset.theme).toBe("dark")

  hidden.mockReturnValue(true)
  document.dispatchEvent(new Event("visibilitychange"))
  expect(vi.getTimerCount()).toBe(0)
  vi.setSystemTime(new Date(2026, 8, 14, 12, 0))
  hidden.mockReturnValue(false)
  document.dispatchEvent(new Event("visibilitychange"))
  expect(document.documentElement.dataset.theme).toBe("light")
  window.dispatchEvent(new Event("pagehide"))
  expect(vi.getTimerCount()).toBe(0)
  vi.setSystemTime(new Date(2026, 8, 14, 22, 0))
  window.dispatchEvent(new Event("pageshow"))
  expect(document.documentElement.dataset.theme).toBe("dark")
  expect(vi.getTimerCount()).toBe(1)

  // A choice made in another page is reflected here, including returning to Auto.
  localStorage.setItem("poieo.theme", "light")
  window.dispatchEvent(new StorageEvent("storage", { key: "poieo.theme" }))
  vi.advanceTimersByTime(0)
  expect(picker.value).toBe("light")
  expect(document.documentElement.dataset.theme).toBe("light")
  expect(vi.getTimerCount()).toBe(0)
  localStorage.clear()
  window.dispatchEvent(new StorageEvent("storage", { key: null }))
  vi.advanceTimersByTime(0)
  expect(picker.value).toBe("auto")
  expect(document.documentElement.dataset.theme).toBe("dark")

  // Missing, invalid, or unavailable storage uses Auto; manual selection still works.
  localStorage.setItem("poieo.theme", "invalid")
  window.dispatchEvent(new StorageEvent("storage", { key: "poieo.theme" }))
  expect(picker.value).toBe("auto")
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked") })
  window.dispatchEvent(new StorageEvent("storage", { key: "poieo.theme" }))
  expect(picker.value).toBe("auto")
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked") })
  choose("light")
  expect(document.documentElement.dataset.theme).toBe("light")
  expect(picker.value).toBe("light")
  vi.setSystemTime(new Date(2026, 8, 15, 1, 0))
  window.dispatchEvent(new Event("pageshow"))
  expect(document.documentElement.dataset.theme).toBe("light")
})
