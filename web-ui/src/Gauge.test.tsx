import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { readFileSync } from "node:fs"
import { afterEach, beforeEach, expect, test } from "vitest"

import { compact, Gauge, gaugeLevel } from "./Gauge"

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

test("a gauge's level follows how close the value is to its limit", () => {
  expect(gaugeLevel(100, 1_000)).toBe("ok")
  expect(gaugeLevel(800, 1_000)).toBe("near")
  expect(gaugeLevel(1_000, 1_000)).toBe("over")
  expect(gaugeLevel(1_500, 1_000)).toBe("over")
  // No limit is not a limit of zero: nothing to compare against.
  expect(gaugeLevel(1_500, null)).toBe("unbounded")
  expect(gaugeLevel(1_500, 0)).toBe("unbounded")
})

test("numbers read compact only once they are large", () => {
  expect(compact(1_284)).toBe("1,284")
  expect(compact(12_900)).toBe("12.9k")
  expect(compact(12_000)).toBe("12k")
  expect(compact(1_200_000)).toBe("1.2M")
})

test("a gauge says its state in words as well as colour", async () => {
  await act(async () => root.render(<Gauge label="page" used={11_000} limit={12_000} unit="chars" />))

  const gauge = container.querySelector<HTMLElement>('[data-gauge="page"]')!
  expect(gauge.dataset.level).toBe("near")
  expect(gauge.textContent).toContain("11k / 12k chars")
  expect(gauge.textContent).toContain("near the limit")
  expect(gauge.getAttribute("aria-label")).toBe("page: 11k of 12k chars, near the limit")
  expect(container.querySelector<HTMLElement>(".gauge-fill")!.style.width).toBe("92%")
})

test("an estimate is marked, and an unknown limit draws no track", async () => {
  await act(async () =>
    root.render(
      <>
        <Gauge label="learner" used={390} limit={8_000} unit="tokens" estimate />
        <Gauge label="bare" used={1_550} limit={null} unit="chars" />
      </>,
    ),
  )

  const learner = container.querySelector<HTMLElement>('[data-gauge="learner"]')!
  expect(learner.textContent).toContain("≈390 / 8,000 tokens")
  expect(learner.getAttribute("aria-label")).toBe("learner: about 390 of 8,000 tokens")
  const bare = container.querySelector<HTMLElement>('[data-gauge="bare"]')!
  expect(bare.dataset.level).toBe("unbounded")
  expect(bare.querySelector(".gauge-track")).toBeNull()
  expect(bare.textContent).toContain("1,550 chars")
})

test("a gauge wraps its parts in a narrow place instead of running out of the box", () => {
  // The drawer clipped "near the limit" mid-word at the first look; the parts
  // stay whole and the word drops a line.
  const css = readFileSync("src/gauge.css", "utf8")
  const rule = css.slice(css.indexOf(".gauge {"), css.indexOf("}", css.indexOf(".gauge {")))
  expect(rule).toContain("flex-wrap: wrap")
  expect(rule).not.toContain("white-space: nowrap")
  expect(css).toMatch(/\.gauge > span \{[^}]*white-space: nowrap/)
})
