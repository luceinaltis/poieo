import { act } from "react"
import { createRoot } from "react-dom/client"
import { expect, test } from "vitest"

import { ApplicationResult, applicationLabel } from "./ApplicationResult"

test("identical work and undone work have distinct recorded outcomes", () => {
  expect(applicationLabel({ status: "applied", accepted: 2, unchanged: true })).toBe("Already included")
  expect(applicationLabel({ status: "undone" })).toBe("Undone · task paused")
})

test("applied changes show the commands and the recorded verification result", () => {
  const host = document.createElement("div")
  const root = createRoot(host)
  act(() => root.render(<ApplicationResult result={{ status: "applied", accepted: 1,
    checks: [{ command: "python -m pytest", exit_code: 0, output: "12 passed" }] }} />))
  expect(host.textContent).toContain("Applied to project")
  expect(host.textContent).toContain("python -m pytest")
  expect(host.textContent).toContain("12 passed")
  act(() => root.unmount())
})

test("a blocked change explains the allowed-file boundary without claiming success", () => {
  const host = document.createElement("div")
  const root = createRoot(host)
  act(() => root.render(<ApplicationResult result={{ status: "blocked", outside_scope: ["private.txt"] }} />))
  expect(host.textContent).toContain("Needs your decision")
  expect(host.textContent).toContain("Outside the allowed files: private.txt")
  expect(host.textContent).not.toContain("passed")
  act(() => root.unmount())
})
