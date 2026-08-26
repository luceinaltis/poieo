import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

import { useAct } from "./useAct"
import type { Act } from "./useAct"

interface Reply {
  ok: boolean
  error?: string
}

let container: HTMLDivElement
let root: Root
let latest: Act<Reply>

/** A component that does nothing but hand the hook's value back out. */
function Probe({ onDone }: { onDone(): void }) {
  latest = useAct<Reply>(onDone)
  return null
}

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

function render(onDone: () => void = () => {}) {
  act(() => {
    root.render(<Probe onDone={onDone} />)
  })
}

test("a successful answer reports done and keeps no refusal", async () => {
  const done = vi.fn()
  render(done)

  let sent = false
  await act(async () => {
    sent = await latest.act(async () => ({ ok: true }))
  })

  expect(sent).toBe(true)
  expect(done).toHaveBeenCalledTimes(1)
  expect(latest.refused).toBeNull()
  expect(latest.busy).toBe(false)
})

test("a refusal is kept and done is not called", async () => {
  const done = vi.fn()
  render(done)

  await act(async () => {
    await latest.act(async () => ({ ok: false, error: "a run is in flight" }))
  })

  expect(done).not.toHaveBeenCalled()
  expect(latest.refused).toEqual({ ok: false, error: "a run is in flight" })
})

test("busy is true while the request is out, and blocks a second one", async () => {
  render()

  let release: (value: Reply) => void = () => {}
  const pending = new Promise<Reply>((resolve) => (release = resolve))

  let first: Promise<boolean>
  act(() => {
    first = latest.act(() => pending)
  })
  expect(latest.busy).toBe(true)

  // The second caller is told it did not go out -- which is what lets Decide
  // leave its confirmation step open rather than closing it on a no-op.
  let second = true
  await act(async () => {
    second = await latest.act(async () => ({ ok: true }))
  })
  expect(second).toBe(false)

  await act(async () => {
    release({ ok: true })
    await first
  })
  expect(latest.busy).toBe(false)
})

test("a later success clears an earlier refusal", async () => {
  render()

  await act(async () => {
    await latest.act(async () => ({ ok: false, error: "no" }))
  })
  expect(latest.refused).not.toBeNull()

  await act(async () => {
    await latest.act(async () => ({ ok: true }))
  })
  expect(latest.refused).toBeNull()
})
