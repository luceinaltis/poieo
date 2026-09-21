import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { afterEach, expect, test, vi } from "vitest"

const SITE = resolve(process.cwd(), "../site")

afterEach(() => {
  window.dispatchEvent(new Event("pagehide"))
  vi.useRealTimers()
  vi.restoreAllMocks()
  delete document.documentElement.dataset.theme
})

// theme.js writes data-theme; the sky watches that attribute, and jsdom delivers the change on the microtask queue.
const settle = () => Promise.resolve()

test("the sun belongs to a light page and the moon to a dark one, on an arc that keeps local time", async () => {
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

  // Without a theme on the page, the clock alone decides.
  document.body.innerHTML = page.body.innerHTML
  new Function(script)()
  const sky = document.getElementById("landing-sky")!
  const body = sky.querySelector("img")!
  const rise = () => Number(sky.style.getPropertyValue("--sky-rise"))
  const across = () => Number(sky.style.getPropertyValue("--sky-progress"))
  expect(sky.hidden).toBe(false)
  expect(sky.getAttribute("role")).toBe("img")
  expect(sky.dataset.period).toBe("night")
  expect(body.getAttribute("src")).toBe("img/moon.png")
  expect(sky.getAttribute("aria-label")).toContain("05:59")
  expect(vi.getTimerCount()).toBe(1)

  // The boundary changes on the next clock minute, without a reload.
  vi.advanceTimersByTime(30_000)
  expect(sky.dataset.period).toBe("day")
  expect(body.getAttribute("src")).toBe("img/sun.png")
  expect(sky.getAttribute("aria-label")).toBe("Sun at 06:00, your local time")
  const dawn = rise()
  // Movement follows seconds, not a frozen position between minute ticks.
  vi.advanceTimersByTime(15_000)
  expect(across()).toBeGreaterThan(0)
  expect(across()).toBeLessThan(0.001)
  expect(vi.getTimerCount()).toBe(1)
  vi.setSystemTime(new Date(2026, 8, 13, 9, 0))
  window.dispatchEvent(new Event("pageshow"))
  expect(across()).toBeCloseTo(0.25)
  const morning = rise()
  vi.setSystemTime(new Date(2026, 8, 13, 12, 0))
  window.dispatchEvent(new Event("pageshow"))
  expect(rise()).toBeGreaterThan(dawn)
  expect(rise()).toBeGreaterThan(morning)
  expect(across()).toBeCloseTo(0.5)
  expect(vi.getTimerCount()).toBe(1)

  // A page made dark at noon shows the moon where the sun was. The arc does not move.
  document.documentElement.dataset.theme = "dark"
  await settle()
  expect(sky.dataset.period).toBe("night")
  expect(body.getAttribute("src")).toBe("img/moon.png")
  expect(sky.getAttribute("aria-label")).toContain("Moon at 12:00, your local time")
  expect(across()).toBeCloseTo(0.5)
  expect(sky.classList.contains("sky-jump")).toBe(true) // swapped in place, not carried across the sky
  expect(vi.getTimerCount()).toBe(1)
  document.documentElement.dataset.theme = "light"
  await settle()
  expect(sky.dataset.period).toBe("day")
  expect(body.getAttribute("src")).toBe("img/sun.png")

  // A chosen light page keeps its sun into the evening, where it starts the evening arc.
  vi.setSystemTime(new Date(2026, 8, 13, 17, 59, 59))
  window.dispatchEvent(new Event("pageshow"))
  expect(rise()).toBeLessThan(0.01)
  expect(across()).toBeGreaterThan(0.99)
  vi.advanceTimersByTime(1_000)
  expect(sky.dataset.period).toBe("day")
  expect(sky.getAttribute("aria-label")).toBe("Sun at 18:00, your local time")
  expect(across()).toBe(0)

  // In Auto, theme.js darkens the page at 18:00 and the moon follows it.
  document.documentElement.dataset.theme = "dark"
  await settle()
  expect(sky.dataset.period).toBe("night")
  expect(sky.getAttribute("aria-label")).toContain("Moon at 18:00, your local time")
  expect(sky.classList.contains("sky-jump")).toBe(true)

  // A hidden or cached page stops ticking and rereads the clock on return; a dark page keeps its moon.
  hidden.mockReturnValue(true)
  document.dispatchEvent(new Event("visibilitychange"))
  expect(vi.getTimerCount()).toBe(0)
  vi.setSystemTime(new Date(2026, 8, 14, 9, 15))
  hidden.mockReturnValue(false)
  document.dispatchEvent(new Event("visibilitychange"))
  expect(sky.dataset.period).toBe("night")
  expect(sky.getAttribute("aria-label")).toContain("Moon at 09:15, your local time")
  expect(vi.getTimerCount()).toBe(1)
  window.dispatchEvent(new Event("pagehide"))
  expect(vi.getTimerCount()).toBe(0)
  vi.setSystemTime(new Date(2026, 8, 14, 22, 0))
  window.dispatchEvent(new Event("pageshow"))
  expect(sky.dataset.period).toBe("night")
  expect(vi.getTimerCount()).toBe(1)

  // The visible moon changes with the UTC date, independent of local time or theme choice.
  const phaseAt = (iso: string) => {
    vi.setSystemTime(new Date(iso))
    window.dispatchEvent(new Event("pageshow"))
    return Number(sky.style.getPropertyValue("--moon-light"))
  }
  // Independent NASA UT reference dates (not generated from the implementation's period).
  expect(phaseAt("2025-01-29T12:36:00Z")).toBeLessThan(0.01)
  expect(sky.dataset.phase).toBe("New moon")
  expect(phaseAt("2025-02-05T08:02:00Z")).toBeGreaterThan(0.4)
  expect(Number(sky.style.getPropertyValue("--moon-light"))).toBeLessThan(0.6)
  const maskPoints = () => [...body.style.clipPath.matchAll(/([\d.]+)% ([\d.]+)%/g)].map(m => [Number(m[1]), Number(m[2])])
  const area = () => {
    const points = maskPoints()
    return Math.abs(points.reduce((sum, p, i) => {
      const q = points[(i + 1) % points.length]
      return sum + p[0] * q[1] - p[1] * q[0]
    }, 0)) / 2 / (Math.PI * 34.2 ** 2)
  }
  const meanX = () => maskPoints().reduce((sum, p) => sum + p[0], 0) / maskPoints().length
  expect(area()).toBeCloseTo(Number(sky.style.getPropertyValue("--moon-light")), 2)
  expect(meanX()).toBeGreaterThan(50) // waxing: right side lit
  const waxingMask = body.style.clipPath
  expect(waxingMask).toMatch(/^polygon/)
  expect(phaseAt("2025-02-12T13:53:00Z")).toBeGreaterThan(0.98)
  expect(sky.dataset.phase).toBe("Full moon")
  expect(area()).toBeGreaterThan(0.98)
  expect(phaseAt("2025-02-20T17:33:00Z")).toBeGreaterThan(0.4)
  expect(Number(sky.style.getPropertyValue("--moon-light"))).toBeLessThan(0.6)
  expect(body.style.clipPath).not.toBe(waxingMask)
  expect(meanX()).toBeLessThan(50) // waning: left side lit
  expect(area()).toBeCloseTo(Number(sky.style.getPropertyValue("--moon-light")), 2)
  expect(phaseAt("2025-02-28T00:45:00Z")).toBeLessThan(0.01)
  expect(phaseAt("2024-12-30T22:27:00Z")).toBeLessThan(0.01) // before the epoch
  document.documentElement.dataset.theme = "light"
  await settle()
  expect(body.style.clipPath).toBe("")
  expect(sky.hasAttribute("data-phase")).toBe(false)

  // Use the browser's local clock even when its hour differs from UTC.
  delete document.documentElement.dataset.theme
  await settle()
  vi.setSystemTime(new Date("2026-09-14T00:00:00Z"))
  vi.spyOn(Date.prototype, "getHours").mockReturnValue(9)
  vi.spyOn(Date.prototype, "getMinutes").mockReturnValue(0)
  window.dispatchEvent(new Event("pageshow"))
  expect(sky.dataset.period).toBe("day")
  expect(sky.getAttribute("aria-label")).toContain("09:00")
})
