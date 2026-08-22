import { beforeEach, expect, test, vi } from "vitest"

import { forgetSpots, saveSpot, savedSpots } from "./placement"

beforeEach(() => {
  localStorage.clear()
})

test("a moved bench is remembered", () => {
  saveSpot("chores", { x: 120, y: 40 })
  expect(savedSpots()).toEqual({ chores: { x: 120, y: 40 } })
})

test("moving one bench leaves the others where they were", () => {
  saveSpot("chores", { x: 1, y: 2 })
  saveSpot("drafting", { x: 3, y: 4 })

  expect(savedSpots()).toEqual({
    chores: { x: 1, y: 2 },
    drafting: { x: 3, y: 4 },
  })
})

test("nonsense in storage is ignored, not rendered", () => {
  localStorage.setItem("poieo.atelier.benches.v2", '{"a": {"x": "left"}, "b": null}')
  expect(savedSpots()).toEqual({})
})

test("unreadable storage is not a crash", () => {
  localStorage.setItem("poieo.atelier.benches.v2", "{not json")
  expect(savedSpots()).toEqual({})

  const blocked = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("denied")
  })
  expect(() => saveSpot("a", { x: 0, y: 0 })).not.toThrow()
  blocked.mockRestore()
})

test("the arrangement can be forgotten", () => {
  saveSpot("chores", { x: 1, y: 2 })
  forgetSpots()
  expect(savedSpots()).toEqual({})
})


test("an arrangement from the tap-as-drag release is not carried over", () => {
  localStorage.setItem(
    "poieo.atelier.benches",
    JSON.stringify({ chores: { x: 40, y: 40 } }),
  )
  expect(savedSpots()).toEqual({})
})
