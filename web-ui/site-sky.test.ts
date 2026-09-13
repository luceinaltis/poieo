import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { afterEach, expect, test, vi } from "vitest"

const SITE = resolve(process.cwd(), "../site")

afterEach(() => {
  window.dispatchEvent(new Event("pagehide"))
  vi.useRealTimers()
  vi.restoreAllMocks()
  localStorage.clear()
})

test("the landing sun and moon follow local time, survive sleep, and leave the chosen theme alone", () => {
  vi.useFakeTimers()
  vi.setSystemTime(new Date(2026, 8, 13, 5, 59, 30))
  const hidden = vi.spyOn(document, "hidden", "get").mockReturnValue(false)
  const page = new DOMParser().parseFromString(readFileSync(resolve(SITE, "index.html"), "utf8"), "text/html")
  const skyMarkup = page.getElementById("landing-sky")
  expect(skyMarkup).not.toBeNull()
  expect(skyMarkup!.hidden).toBe(true) // no incorrect sun or moon before the clock is read
  expect(page.querySelector('script[src="sky.js"]')).not.toBeNull()
  const script = readFileSync(resolve(SITE, "sky.js"), "utf8")

  // It is a landing illustration; loading the helper without it does nothing.
  document.body.innerHTML = ""
  new Function(script)()
  expect(vi.getTimerCount()).toBe(0)
  const docs = new DOMParser().parseFromString(readFileSync(resolve(SITE, "docs.html"), "utf8"), "text/html")
  expect(docs.querySelector('script[src="sky.js"], #landing-sky')).toBeNull()

  document.body.innerHTML = page.body.innerHTML
  document.documentElement.dataset.theme = "dark"
  localStorage.setItem("poieo.theme", "dark")
  new Function(script)()
  const sky = document.getElementById("landing-sky")!
  const rise = () => Number(sky.style.getPropertyValue("--sky-rise"))
  expect(sky.hidden).toBe(false)
  expect(sky.getAttribute("role")).toBe("img")
  expect(sky.dataset.period).toBe("night")
  expect(sky.getAttribute("aria-label")).toContain("05:59")
  expect(vi.getTimerCount()).toBe(1)

  // The boundary changes on the next clock minute, without a reload.
  vi.advanceTimersByTime(30_000)
  expect(sky.dataset.period).toBe("day")
  expect(sky.getAttribute("aria-label")).toBe("Sun at 06:00, your local time")
  const dawn = rise()
  vi.setSystemTime(new Date(2026, 8, 13, 12, 0))
  window.dispatchEvent(new Event("pageshow"))
  expect(sky.dataset.period).toBe("day")
  expect(rise()).toBeGreaterThan(dawn)
  expect(document.documentElement.dataset.theme).toBe("dark")
  expect(localStorage.getItem("poieo.theme")).toBe("dark")
  expect(vi.getTimerCount()).toBe(1)

  vi.setSystemTime(new Date(2026, 8, 13, 17, 59, 59))
  window.dispatchEvent(new Event("pageshow"))
  expect(sky.dataset.period).toBe("day")
  expect(rise()).toBeLessThan(0.01)
  vi.advanceTimersByTime(1_000)
  expect(sky.dataset.period).toBe("night")
  expect(sky.getAttribute("aria-label")).toBe("Moon at 18:00, your local time")

  // A light theme at midnight still shows the moon. This is not a theme switch.
  document.documentElement.dataset.theme = "light"
  localStorage.setItem("poieo.theme", "light")
  vi.setSystemTime(new Date(2026, 8, 14, 0, 0))
  window.dispatchEvent(new Event("pageshow"))
  expect(sky.dataset.period).toBe("night")
  expect(sky.getAttribute("aria-label")).toContain("00:00")
  expect(rise()).toBeGreaterThan(0.99)
  expect(document.documentElement.dataset.theme).toBe("light")
  expect(localStorage.getItem("poieo.theme")).toBe("light")

  // A hidden or cached page stops ticking and rereads the actual clock on return.
  hidden.mockReturnValue(true)
  document.dispatchEvent(new Event("visibilitychange"))
  expect(vi.getTimerCount()).toBe(0)
  vi.setSystemTime(new Date(2026, 8, 14, 9, 15))
  hidden.mockReturnValue(false)
  document.dispatchEvent(new Event("visibilitychange"))
  expect(sky.dataset.period).toBe("day")
  expect(sky.getAttribute("aria-label")).toContain("09:15")
  expect(vi.getTimerCount()).toBe(1)
  window.dispatchEvent(new Event("pagehide"))
  expect(vi.getTimerCount()).toBe(0)
  vi.setSystemTime(new Date(2026, 8, 14, 22, 0))
  window.dispatchEvent(new Event("pageshow"))
  expect(sky.dataset.period).toBe("night")
  expect(vi.getTimerCount()).toBe(1)

  // Use the browser's local clock even when its hour differs from UTC.
  vi.setSystemTime(new Date("2026-09-14T00:00:00Z"))
  vi.spyOn(Date.prototype, "getHours").mockReturnValue(9)
  vi.spyOn(Date.prototype, "getMinutes").mockReturnValue(0)
  window.dispatchEvent(new Event("pageshow"))
  expect(sky.dataset.period).toBe("day")
  expect(sky.getAttribute("aria-label")).toContain("09:00")
})
