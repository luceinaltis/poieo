import { beforeEach, expect, test, vi } from "vitest"

import { forgetSpots, saveSpot, savedSpots } from "./placement"

const KEY = "poieo.atelier.benches.v3"

beforeEach(() => {
  localStorage.clear()
})

test("a moved bench remembers its square", () => {
  saveSpot("chores", { col: 1, row: 2 })
  expect(savedSpots()).toEqual({ chores: { col: 1, row: 2 } })
})

test("moving one bench leaves the others where they were", () => {
  saveSpot("chores", { col: 0, row: 0 })
  saveSpot("drafting", { col: 1, row: 0 })

  expect(savedSpots()).toEqual({
    chores: { col: 0, row: 0 },
    drafting: { col: 1, row: 0 },
  })
})

test("anything that is not a pair of whole squares is ignored", () => {
  localStorage.setItem(KEY, JSON.stringify({ a: { col: 1.5, row: 0 }, b: null, c: { col: "x" } }))
  expect(savedSpots()).toEqual({})
})

test("arrangements from the earlier releases are not carried over", () => {
  // One stored loose floor coordinates; the other collected squares nobody
  // meant to choose, because a tap counted as a drag.
  localStorage.setItem("poieo.atelier.benches", JSON.stringify({ a: { x: 4, y: 4 } }))
  localStorage.setItem("poieo.atelier.benches.v2", JSON.stringify({ a: { x: 4, y: 4 } }))
  expect(savedSpots()).toEqual({})
})

test("unreadable storage is not a crash", () => {
  localStorage.setItem(KEY, "{not json")
  expect(savedSpots()).toEqual({})

  const blocked = vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
    throw new Error("denied")
  })
  expect(() => saveSpot("a", { col: 0, row: 0 })).not.toThrow()
  blocked.mockRestore()
})

test("the arrangement can be forgotten", () => {
  saveSpot("chores", { col: 1, row: 1 })
  forgetSpots()
  expect(savedSpots()).toEqual({})
})
