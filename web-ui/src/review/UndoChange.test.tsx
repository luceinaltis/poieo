import { act } from "react"
import { createRoot } from "react-dom/client"
import { expect, test, vi } from "vitest"
import { UndoChange } from "./UndoChange"

test("undo identifies the applied run and reports a conflict without claiming success", async () => {
  const fetch = vi.fn().mockResolvedValue({ ok: false, json: async () => ({ conflict: ["later.txt"] }) })
  vi.stubGlobal("fetch", fetch)
  const host = document.createElement("div")
  const root = createRoot(host)
  const onDone = vi.fn()
  try {
    await act(async () => root.render(<UndoChange project="board" task="chores" runId="r1" onDone={onDone} />))
    await act(async () => host.querySelector("button")!.click())
    expect(fetch.mock.calls[0][0]).toBe("/api/tasks/board/chores/undo")
    expect(JSON.parse(fetch.mock.calls[0][1].body)).toEqual({ run_id: "r1" })
    expect(host.textContent).toContain("later.txt")
    expect(onDone).not.toHaveBeenCalled()
  } finally {
    act(() => root.unmount())
    vi.unstubAllGlobals()
  }
})
