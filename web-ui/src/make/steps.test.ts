import { expect, test } from "vitest"
import { appendStep, graphOf, newStep, resultsFrom, stepProblems } from "./steps"

test("a command offers the output field recorded by the runtime", () => {
  const step = newStep([], "command", "echo ready")
  expect(resultsFrom([step])).toContainEqual({ value: "step_1.output", label: "Step 1 — output" })
})

test("conditions cannot read an answer from a step the run may have skipped", () => {
  let steps = [newStep([], "agent", "draft")]
  steps = appendStep(steps, "agent")
  steps[1].text = "review"
  steps = appendStep(steps, "router")
  steps[0].next = steps[2].id
  steps[2].conditions[0].to = steps[1].id
  expect(stepProblems(steps)).toContain("Step 2 must run before the condition in Step 3 can use its result.")
})

test("turning a prompt into steps keeps journal and memory input and its turn limit", () => {
  const graph = graphOf("tidy", [newStep([], "agent", "tidy up")])
  expect(graph.nodes[0]).toMatchObject({ max_turns: 40, system: expect.stringContaining("input.get('journal'") })
  expect(graph.nodes[0]).toMatchObject({ system: expect.stringContaining("input.get('memory'") })
})

test("an answer can flow through a condition into a later step", () => {
  let steps = [newStep([], "agent", "draft")]
  steps = appendStep(steps, "router")
  steps = appendStep(steps, "agent")
  steps[2].text = "review {{ step_1 }}"
  expect(stepProblems(steps)).toEqual([])
})

test("a human question ends the run and needs distinct choices", () => {
  let steps = [newStep([], "agent", "draft")]
  steps = appendStep(steps, "confirm")
  steps[1].text = "Continue?"
  expect(graphOf("review", steps).nodes[1]).toEqual({
    id: "step_2", type: "confirm", description: "Step 2", prompt: "Continue?", choices: ["Yes", "No"],
  })
  steps[1].choices = "Yes\nYes"
  expect(stepProblems(steps)).toContain("Give Step 2 at least two different choices.")
})
