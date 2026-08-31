/// <reference types="node" />

import { readFileSync } from "node:fs"
import { act } from "react"
import { createRoot } from "react-dom/client"
import type { Root } from "react-dom/client"
import { afterEach, beforeEach, expect, test } from "vitest"

import { RunList } from "./RunList"
import type { RunSummary } from "../types"

const REVIEW_CSS = readFileSync("src/review/review.css", "utf8")

const USAGE = {
  input_tokens: 0,
  output_tokens: 0,
  cache_read_tokens: 0,
  cache_write_tokens: 0,
}

function run(over: Partial<RunSummary> = {}): RunSummary {
  return {
    run_id: "r",
    task: "chores",
    project: "chores",
    graph: "agent-task",
    status: "completed",
    started_at: "2026-08-22T02:14:00+00:00",
    finished_at: "2026-08-22T02:14:09+00:00",
    steps: 1,
    iteration: 1,
    trigger: "cron 0 2 * * *",
    usage: USAGE,
    error: null,
    said: "did the thing",
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
      <RunList runs={runs} selected={null} tracked={tracked} onSelect={() => {}} />,
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

test("time and spend share a ledger line above the run's account", () => {
  render([
    run({
      run_id: "wide",
      said: "x".repeat(600),
      usage: { ...USAGE, input_tokens: 160_360, output_tokens: 6_578 },
    }),
  ])

  const row = rows()[0]
  const meta = row.querySelector<HTMLElement>(".run-meta")!
  const account = row.querySelector<HTMLElement>(".run-what")!
  expect(meta.querySelector(".run-when")).not.toBeNull()
  expect(meta.querySelector(".run-size")?.textContent).toContain("160,360 sent")
  expect(meta.nextElementSibling).toBe(account)
  expect(REVIEW_CSS).toMatch(/\.run-open\s*\{[^}]*grid-template-columns:\s*minmax\(0,\s*1fr\)/s)
  expect(REVIEW_CSS).toMatch(/\.run-what\s*\{[^}]*overflow-wrap:\s*anywhere/s)
})

test("a run that found nothing to do says so, and is not a failure", () => {
  render([FOUND_NOTHING])

  const row = rows()[0]
  expect(row.getAttribute("data-outcome")).toBe("nothing")
  expect(row.textContent).toMatch(/nothing to do/i)
})

test("failed runs are collapsed behind one line until asked for", () => {
  render([DID_SOMETHING, BROKE, run({ run_id: "d", status: "failed" })])

  // the good runs are not buried under the noise
  expect(rows()).toHaveLength(1)
  const toggle = container.querySelector<HTMLElement>("[data-failed-toggle]")!
  expect(toggle.textContent).toContain("2 failed")

  act(() => toggle.click())

  expect(rows()).toHaveLength(3)
  expect(container.textContent).toContain("the tool went missing")
})

test("the rendered run list uses none of the forbidden words", () => {
  render([DID_SOMETHING, FOUND_NOTHING, BROKE])
  act(() => container.querySelector<HTMLElement>("[data-failed-toggle]")!.click())

  // The reader is here to see runs and changes, not to be taught a tool's
  // vocabulary. The one licensed exception lives on the accept button.
  // "work" is forbidden for the opposite reason: it is a second name for a
  // run, and DESIGN principle 7 allows each thing exactly one.
  const forbidden = /\b(commit|commits|sha|branch|worktree|ref|refs|merge|merged|HEAD|run id|work|works)\b/i
  expect(container.textContent ?? "").not.toMatch(forbidden)
})

test("the selected run is marked", () => {
  act(() => {
    root.render(
      <RunList runs={[DID_SOMETHING]} selected="a" tracked onSelect={() => {}} />,
    )
  })

  expect(rows()[0].getAttribute("data-selected")).toBe("true")
})

test("clicking a row selects that run", () => {
  const picked: string[] = []
  act(() => {
    root.render(
      <RunList
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


test("a task with no private copy is not accused of finding nothing to do", () => {
  render([FOUND_NOTHING], false)

  const row = rows()[0]
  expect(row.getAttribute("data-outcome")).toBe("succeeded")
  expect(row.textContent).not.toMatch(/nothing to do/i)
  // it still says what the run amounted to -- in the run's own words
  expect(row.textContent).toContain("did the thing")
})


test("a run with no change to describe says what it said", () => {
  // A task that keeps no private copy has no change message, so every row read
  // "3 steps" -- the graph's shape, identical down the list. The run's own
  // closing sentence is the part that differs.
  render([run({ run_id: "a", steps: 3, said: "tidied the docs folder" })], false)

  expect(rows()[0].textContent).toContain("tidied the docs folder")
  expect(rows()[0].textContent).not.toContain("3 steps")
})


test("a run with a long answer is cut to its first line", () => {
  // A model that wrote six paragraphs must not push the next nine runs off
  // the screen; the drawer's timeline is where the whole of it belongs.
  render(
    [run({ run_id: "a", said: "wrote the file\nand then explained itself at length" })],
    false,
  )

  expect(rows()[0].textContent).toContain("wrote the file")
  expect(rows()[0].textContent).not.toContain("at length")
})


test("a run that said nothing at all still says what it cost", () => {
  render([run({ run_id: "a", steps: 3, said: "" })], false)

  expect(rows()[0].textContent).toContain("3 steps")
  expect(rows()[0].textContent).toContain("9s")
})

test("a run says what it spent when it changed nothing to count", () => {
  // The lines-changed column is empty for a task with no copy, and tokens are
  // the other thing a run costs.
  render(
    [run({ run_id: "a", usage: { ...USAGE, output_tokens: 128 } })],
    false,
  )

  expect(rows()[0].textContent).toContain("128")
})

test("a run says how much it sent, which is the number that explains a failure", () => {
  // A run that died reading twenty files spent 160,360 tokens to produce
  // 6,578, and the row said "6578 tokens" -- the small half of the story, and
  // not the half that says why it stopped.
  render(
    [
      run({
        run_id: "a",
        usage: { ...USAGE, input_tokens: 160360, output_tokens: 6578 },
      }),
    ],
    false,
  )

  expect(rows()[0].textContent).toContain("160,360")
})

test("a run that was mostly answered from cache says so", () => {
  // Resending a whole conversation every turn looks ruinous until you see how
  // much of it the endpoint already had.
  render(
    [
      run({
        run_id: "a",
        usage: {
          ...USAGE,
          input_tokens: 660598,
          output_tokens: 58072,
          cache_read_tokens: 633344,
        },
      }),
    ],
    false,
  )

  expect(rows()[0].textContent).toContain("96% cached")
})

test("an older Claude run reconstructs its prompt total from split counters", () => {
  render(
    [
      run({
        run_id: "a",
        usage: {
          ...USAGE,
          input_tokens: 108,
          output_tokens: 3,
          cache_read_tokens: 2_502_763,
          cache_write_tokens: 5_000,
        },
      }),
    ],
    false,
  )

  expect(rows()[0].textContent).toContain("2,507,871 sent")
  expect(rows()[0].textContent).toContain("100% cached")
  expect(rows()[0].textContent).not.toContain("2317373%")
})

test("a failed run still leads with why, not with how long", () => {
  render([BROKE], false)
  // Failed runs stay collapsed until asked for; the point here is what the row
  // says once it is, not whether it is shown.
  act(() => container.querySelector<HTMLElement>("[data-failed-toggle]")!.click())

  expect(rows()[0].textContent).toContain("the tool went missing")
  expect(rows()[0].textContent).not.toContain("step")
})

test("the list says how the night went before listing it", () => {
  // The question a reader opens this with is whether the thing has been
  // working, and ten rows do not answer it as fast as one line does.
  render([DID_SOMETHING, FOUND_NOTHING, BROKE])

  const summary = container.querySelector(".run-summary")!
  expect(summary.textContent).toContain("3 runs")
  expect(summary.textContent).toContain("1 failed")
})
