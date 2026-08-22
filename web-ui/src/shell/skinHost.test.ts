import { beforeEach, expect, test, vi } from "vitest"

import { createSkinHost, readSkinPreference, writeSkinPreference } from "./skinHost"
import { initialStage } from "../state/stage"
import type { Skin, SkinHandle } from "../skins/contract"
import type { FlowRow } from "../types"

const FLOWS: FlowRow[] = [
  {
    name: "chores",
    graph: "agent-task",
    trigger: "loop",
    status: "waiting",
    current_run_id: null,
    last_run: null,
    pending: 0,
    into: null,
  },
]

function fakeSkin(id: string) {
  const destroy = vi.fn()
  const update = vi.fn()
  const skin: Skin = {
    id,
    label: id,
    mount: vi.fn((): SkinHandle => ({ update, destroy })),
  }
  return { skin, destroy, update }
}

beforeEach(() => {
  localStorage.clear()
})

test("switching skins destroys the old handle exactly once", () => {
  const a = fakeSkin("a")
  const b = fakeSkin("b")
  const host = createSkinHost(document.createElement("div"), { onSelectWorker: () => {} }, (id) =>
    id === "b" ? b.skin : a.skin,
  )

  host.show("a")
  host.show("b")
  expect(a.destroy).toHaveBeenCalledTimes(1)
  expect(b.destroy).not.toHaveBeenCalled()

  host.destroy()
  expect(b.destroy).toHaveBeenCalledTimes(1)
})

test("showing the same skin again does not remount it", () => {
  const a = fakeSkin("a")
  const host = createSkinHost(document.createElement("div"), { onSelectWorker: () => {} }, () => a.skin)

  host.show("a")
  host.show("a")
  expect(a.skin.mount).toHaveBeenCalledTimes(1)
  expect(a.destroy).not.toHaveBeenCalled()
})

test("a skin mounted mid-run is handed the current stage at once", () => {
  const a = fakeSkin("a")
  const b = fakeSkin("b")
  const host = createSkinHost(document.createElement("div"), { onSelectWorker: () => {} }, (id) =>
    id === "b" ? b.skin : a.skin,
  )
  const stage = initialStage(FLOWS)

  host.show("a")
  host.update(stage)
  host.show("b")

  // Otherwise the new skin sits blank until the next event, which on a quiet
  // flow can be minutes away.
  expect(b.update).toHaveBeenCalledWith(stage)
})

test("the skin preference survives a reload and an unknown value", () => {
  expect(readSkinPreference()).toBe("ledger")

  writeSkinPreference("atelier")
  expect(readSkinPreference()).toBe("atelier")

  localStorage.setItem("poieo.skin", "kitchen")
  // readSkinPreference reports what is stored; the registry decides whether it
  // resolves -- an unknown id lands on the fallback rather than blanking.
  expect(readSkinPreference()).toBe("kitchen")
})

test("a hostile storage does not take the page down", () => {
  const boom = vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
    throw new Error("denied")
  })
  expect(readSkinPreference()).toBe("ledger")
  boom.mockRestore()
})
