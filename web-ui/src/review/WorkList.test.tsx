import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test } from "vitest"

import { WorkList } from "./WorkList"
import type { RunSummary } from "../types"

const USAGE = {
  input_tokens: 0,
  output_tokens: 0,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
}

function run(over: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: "r",
    flow: "chores",
    graph: "agent-task",
    status: "completed",
    started_at: "2026-08-22T02:14:00+00:00",
    finished_at: "2026-08-22T02:14:09+00:00",
    steps: 1,
    iteration: 1,
    trigger: "cron 0 2 * * *",
    usage: USAGE,
    error: null,
    ...over,
  }
}

const DID_SOMETHING = run({
  run_id: "a",
  change: {
    base: "aaa",
    head: "bbb",
    files: ["exports.py", "tests.py", "notes.md"],
    insertions: 42,
    deletions: 11,
    message: "tidied the exports",
  },
})
const FOUND_NOTHING = run({ run_id: "b" })
const BROKE = run({ run_id: "c", status: "failed", error: "the tool went missing" })

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

function render(runs: RunSummary[], tracked = true) {
  act(() => {
    root.render(
      <WorkList runs={runs} selected={null} tracked={tracked} onSelect={() => {}} />,
    )
  })
}

function rows() {
  return Array.from(container.querySelectorAll("[data-run]"))
}

test("an empty night is an invitation, not an error", () => {
  render([])

  expect(container.textContent).toMatch(/nothing/i)
  expect(container.textContent).not.toMatch(/error|failed/i)
})

test("a row reads time, size, and the run's own account of itself", () => {
  render([DID_SOMETHING])

  const text = rows()[0].textContent ?? ""
  expect(text).toContain("tidied the exports")
  expect(text).toContain("+42")
  expect(text).toContain("11")
  expect(text).toContain("3 files")
})

test("a run that found nothing to do says so, and is not a failure", () => {
  render([FOUND_NOTHING])

  const row = rows()[0]
  expect(row.getAttribute("data-outcome")).toBe("nothing")
  expect(row.textContent).toMatch(/nothing to do/i)
})

test("failed work is collapsed behind one line until asked for", () => {
  render([DID_SOMETHING, BROKE, run({ run_id: "d", status: "failed" })])

  // the good work is not buried under the noise
  expect(rows()).toHaveLength(1)
  const toggle = container.querySelector<HTMLElement>("[data-failed-toggle]")!
  expect(toggle.textContent).toContain("2 failed")

  act(() => toggle.click())

  expect(rows()).toHaveLength(3)
  expect(container.textContent).toContain("the tool went missing")
})

test("the rendered work list uses none of the forbidden words", () => {
  render([DID_SOMETHING, FOUND_NOTHING, BROKE])
  act(() => container.querySelector<HTMLElement>("[data-failed-toggle]")!.click())

  // The reader is here to see work and changes, not to be taught a tool's
  // vocabulary. The one licensed exception lives on the accept button.
  const forbidden = /\b(commit|commits|sha|branch|worktree|ref|refs|merge|merged|HEAD|run id)\b/i
  expect(container.textContent ?? "").not.toMatch(forbidden)
})

test("the selected piece of work is marked", () => {
  act(() => {
    root.render(
      <WorkList runs={[DID_SOMETHING]} selected="a" tracked onSelect={() => {}} />,
    )
  })

  expect(rows()[0].getAttribute("data-selected")).toBe("true")
})

test("clicking a row selects that piece of work", () => {
  const picked: string[] = []
  act(() => {
    root.render(
      <WorkList
        runs={[DID_SOMETHING]}
        selected={null}
        tracked
        onSelect={(id) => picked.push(id)}
      />,
    )
  })

  act(() => container.querySelector<HTMLElement>("[data-run] button")!.click())

  expect(picked).toEqual(["a"])
})


test("a flow with no private copy is not accused of finding nothing to do", () => {
  render([FOUND_NOTHING], false)

  const row = rows()[0]
  expect(row.getAttribute("data-outcome")).toBe("succeeded")
  expect(row.textContent).not.toMatch(/nothing to do/i)
  // it still says what the run amounted to
  expect(row.textContent).toMatch(/step/i)
})
