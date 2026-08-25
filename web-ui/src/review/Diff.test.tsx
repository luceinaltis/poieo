import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test, vi } from "vitest"

const fetchDiff = vi.hoisted(() => vi.fn())
vi.mock("../api", () => ({ fetchDiff }))

import { Diff, splitPatch } from "./Diff"

const PATCH = `diff --git a/one.py b/one.py
new file mode 100644
index 0000000..5dedc65
--- /dev/null
+++ b/one.py
@@ -0,0 +1 @@
+print(1)
diff --git a/notes.md b/notes.md
index 1111111..2222222 100644
--- a/notes.md
+++ b/notes.md
@@ -1,2 +1,2 @@
 keep me
-old line
+new line`

const REPORT = {
  run_id: "a",
  base: "aaa",
  head: "bbb",
  files: [
    { path: "one.py", status: "A", insertions: 1, deletions: 0 },
    { path: "notes.md", status: "M", insertions: 1, deletions: 1 },
  ],
  patch: PATCH,
  truncated: false,
}

let container: HTMLDivElement
let root: Root

beforeEach(() => {
  ;(globalThis as Record<string, unknown>).IS_REACT_ACT_ENVIRONMENT = true
  fetchDiff.mockReset()
  container = document.createElement("div")
  document.body.append(container)
  root = createRoot(container)
})

afterEach(() => {
  act(() => root.unmount())
  container.remove()
})

async function render(runId = "a") {
  await act(async () => {
    root.render(<Diff runId={runId} />)
  })
}

test("splitPatch keys each file's hunks by its path", () => {
  const byFile = splitPatch(PATCH)

  expect(Object.keys(byFile)).toEqual(["one.py", "notes.md"])
  expect(byFile["one.py"]).toContain("+print(1)")
  expect(byFile["notes.md"]).toContain("-old line")
  expect(byFile["one.py"]).not.toContain("notes.md")
})

test("splitPatch survives an empty or unfamiliar patch", () => {
  expect(splitPatch("")).toEqual({})
  expect(splitPatch("not a patch at all")).toEqual({})
})

test("files render folded, and clicking one opens its hunks", async () => {
  fetchDiff.mockResolvedValue(REPORT)
  await render()

  const files = container.querySelectorAll("[data-file]")
  expect(files).toHaveLength(2)
  expect(files[0].textContent).toContain("one.py")
  expect(files[0].textContent).toContain("+1")
  // folded: no hunk lines on screen yet
  expect(container.querySelector("[data-hunks]")).toBeNull()

  await act(async () => {
    container.querySelector<HTMLElement>('[data-file="one.py"] button')!.click()
  })

  const hunks = container.querySelector("[data-hunks]")!
  expect(hunks.textContent).toContain("+print(1)")
  expect(hunks.textContent).not.toContain("new line")
})

test("added and removed lines are marked, not just coloured by luck", async () => {
  fetchDiff.mockResolvedValue(REPORT)
  await render()
  await act(async () => {
    container.querySelector<HTMLElement>('[data-file="notes.md"] button')!.click()
  })

  const added = container.querySelectorAll('[data-line="added"]')
  const removed = container.querySelectorAll('[data-line="removed"]')
  expect(added).toHaveLength(1)
  expect(removed).toHaveLength(1)
})

test("a truncated patch says so instead of passing a fragment off as whole", async () => {
  fetchDiff.mockResolvedValue({ ...REPORT, truncated: true })
  await render()

  expect(container.textContent).toMatch(/too large/i)
  // the file list is still worth having
  expect(container.querySelectorAll("[data-file]")).toHaveLength(2)
})

test("work that changed no files says that, rather than showing an empty box", async () => {
  fetchDiff.mockResolvedValue({ run_id: "quiet", change: null })
  await render("quiet")

  expect(container.textContent).toMatch(/changed no files/i)
  expect(container.querySelectorAll("[data-file]")).toHaveLength(0)
})

test("a failed read offers a retry rather than a blank pane", async () => {
  fetchDiff.mockResolvedValue(null)
  await render()

  const retry = container.querySelector<HTMLElement>("[data-retry]")!
  expect(retry).not.toBeNull()
  expect(container.textContent).not.toBe("")

  fetchDiff.mockResolvedValue(REPORT)
  await act(async () => retry.click())

  expect(container.querySelectorAll("[data-file]")).toHaveLength(2)
})
