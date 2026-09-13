import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"
import { ThemeSwitch } from "./ThemeSwitch"

let host: HTMLDivElement
let root: Root

beforeEach(() => {
  Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true })
  localStorage.clear()
  document.head.innerHTML = '<meta name="theme-color" content="">'
  host = document.createElement("div")
  document.body.append(host)
  root = createRoot(host)
  vi.stubGlobal("matchMedia", () => ({ matches: false }))
})

afterEach(async () => {
  await act(async () => root.unmount())
  host.remove()
  localStorage.clear()
  delete document.documentElement.dataset.theme
  vi.restoreAllMocks()
  vi.unstubAllGlobals()
})

test("a saved choice wins over the system and switching it survives a remount", async () => {
  localStorage.setItem("poieo.theme", "dark")
  await act(async () => root.render(<ThemeSwitch />))
  expect(document.documentElement.dataset.theme).toBe("dark")
  expect(host.querySelector("button")?.getAttribute("aria-label")).toBe("Switch to light theme")
  await act(async () => host.querySelector("button")!.click())
  expect(document.documentElement.dataset.theme).toBe("light")
  expect(localStorage.getItem("poieo.theme")).toBe("light")
  expect(document.querySelector('meta[name="theme-color"]')?.getAttribute("content")).toBe("#f8f5ef")
  await act(async () => root.unmount())
  root = createRoot(host)
  await act(async () => root.render(<ThemeSwitch />))
  expect(host.querySelector("button")?.getAttribute("aria-label")).toBe("Switch to dark theme")
})

test("an invalid preference falls back to the system without overwriting it", async () => {
  localStorage.setItem("poieo.theme", "invalid")
  vi.stubGlobal("matchMedia", () => ({ matches: true }))
  await act(async () => root.render(<ThemeSwitch />))
  expect(document.documentElement.dataset.theme).toBe("dark")
  expect(localStorage.getItem("poieo.theme")).toBe("invalid")
})

test("switching still works when preference storage is unavailable", async () => {
  vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("blocked") })
  vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked") })
  await act(async () => root.render(<ThemeSwitch />))
  expect(document.documentElement.dataset.theme).toBe("light")
  await act(async () => host.querySelector("button")!.click())
  expect(document.documentElement.dataset.theme).toBe("dark")
})
