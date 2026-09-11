import { expect, test } from "vitest"

import { learnerLoad, pageLength } from "./load"
import type { LearningPass, MemoryOverview } from "./types"

const PASS: LearningPass = {
  at: "2026-09-10T03:00:00+00:00",
  read: 3,
  upto: "c",
  kept: [],
  set_aside: [],
  dropped: [],
  error: null,
  page: null,
  let_go: [],
  prompt_chars: 1_500,
  prompt_tokens: 500,
  context: 8_000,
}

function overview(learner: MemoryOverview["learner"], learning: LearningPass[] = []): MemoryOverview {
  return {
    enabled: true,
    page: null,
    page_text: "",
    suggestion: null,
    stats: null,
    capabilities: { words: true, meaning: false, ask: false },
    graph: { nodes: [], edges: [], total_nodes: 0, total_edges: 0, truncated: false, edges_truncated: false },
    learning,
    learner,
  }
}

test("the next question is put in tokens using the last pass that counted", () => {
  const load = learnerLoad(overview({ prompt_chars: 3_000, entries: 12, model: "local/chat", context: 8_000 }, [PASS]))!

  expect(load.tokens).toBe(1_000)  // three characters a token, as that pass measured
  expect(load.measured).toBe(true)
  expect(load.context).toBe(8_000)
})

test("before any pass has counted, four characters a token is assumed and said so", () => {
  const load = learnerLoad(overview({ prompt_chars: 3_000, entries: 12, model: "local/chat", context: 8_000 }))!

  expect(load.tokens).toBe(750)
  expect(load.measured).toBe(false)
})

test("a pass that counted nothing is not a ratio", () => {
  const silent = { ...PASS, prompt_tokens: null }
  const load = learnerLoad(overview({ prompt_chars: 3_000, entries: 12, model: "local/chat", context: 8_000 }, [silent]))!

  expect(load.tokens).toBe(750)
  expect(load.measured).toBe(false)
})

test("a page's length is counted as a run reads it, without its comments", () => {
  expect(pageLength("<!-- a note to the editor -->\nNever push to main.")).toBe("Never push to main.".length)
  expect(pageLength("<!-- only a note -->")).toBe(0)
  expect(pageLength("  Dates are ISO.  ")).toBe("Dates are ISO.".length)
})
