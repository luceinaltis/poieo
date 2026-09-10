import { readFileSync } from "node:fs"
import { resolve } from "node:path"
import { afterEach, expect, test, vi } from "vitest"

const SCRIPT = readFileSync(resolve(process.cwd(), "../site/theme.js"), "utf8")

afterEach(() => {
  localStorage.clear()
  vi.unstubAllGlobals()
})

test("the saved theme controls the page, browser colour, and named toggle", () => {
  document.head.innerHTML = '<meta name="theme-color" content="">'
  document.body.innerHTML = '<button id="theme-flip" type="button">Theme</button>'
  localStorage.setItem("poieo.theme", "light")
  vi.stubGlobal("matchMedia", () => ({ matches: false }))

  new Function(SCRIPT)()
  document.dispatchEvent(new Event("DOMContentLoaded", { bubbles: true }))

  const button = document.getElementById("theme-flip")!
  expect(document.documentElement.dataset.theme).toBe("light")
  expect(button.getAttribute("aria-label")).toBe("Switch to dark theme")
  expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe("#f3f5f2")

  button.click()
  expect(document.documentElement.dataset.theme).toBe("dark")
  expect(localStorage.getItem("poieo.theme")).toBe("dark")
  expect(button.getAttribute("aria-label")).toBe("Switch to light theme")
  expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe("#14221b")
})
