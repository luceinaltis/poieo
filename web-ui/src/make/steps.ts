/** Form drafts compile to the graph schema the ordinary runtime already reads. */

export type StepKind = "agent" | "command" | "router" | "confirm"
export type Comparison = "==" | "!=" | "in" | "not in" | ">" | "<"
export interface Condition {
  source: string
  comparison: Comparison
  value: string
  to: string | null
}
export interface StepDraft {
  id: string
  name: string
  kind: StepKind
  text: string
  role: string
  tools: boolean
  next: string | null
  conditions: Condition[]
  choices: string
}
export interface TaskGraph {
  name: string
  entry: string
  max_steps: number
  nodes: {
    id: string
    type: StepKind
    description: string
    prompt?: string
    system?: string
    max_turns?: number
    role?: string
    tools?: string[]
    command?: string
    choices?: string[]
    output?: { as: string }
    next?: string | null
    branches?: { when: string; to: string | null }[]
    default?: string | null
  }[]
}

export function resultsFrom(steps: StepDraft[]) {
  return steps.flatMap(step => step.kind === "agent"
    ? [{ value: step.id, label: `${step.name} — answer` }]
    : step.kind === "command" ? [
      { value: `${step.id}.exit_code`, label: `${step.name} — exit code` },
      { value: `${step.id}.stdout`, label: `${step.name} — output` },
    ] : [])
}

export function newCondition(steps: StepDraft[]): Condition {
  const source = resultsFrom(steps.filter(s => s.kind === "agent" || s.kind === "command").slice(-1))[0]?.value ?? ""
  return { source, comparison: "==", value: source.endsWith(".exit_code") ? "0" : "", to: null }
}

export function newStep(steps: StepDraft[], kind: StepKind, text = ""): StepDraft {
  const number = Math.max(0, ...steps.map(s => Number(s.id.slice(5)))) + 1
  return {
    id: `step_${number}`, name: `Step ${number}`, kind, text, role: "", tools: true,
    next: null, conditions: kind === "router" ? [newCondition(steps)] : [], choices: "Yes\nNo",
  }
}

export function appendStep(steps: StepDraft[], kind: StepKind): StepDraft[] {
  const added = newStep(steps, kind)
  return [...steps.map((step, i) => i === steps.length - 1 && step.kind !== "confirm" && step.next === null
    ? { ...step, next: added.id } : step), added]
}

export function removeStep(steps: StepDraft[], id: string): StepDraft[] {
  const removed = steps.find(s => s.id === id)!
  const successor = removed.kind === "router" || removed.next === id ? null : removed.next
  return steps.filter(s => s.id !== id).map(step => ({
    ...step,
    next: step.next === id ? successor : step.next,
    conditions: step.conditions.map(c => ({ ...c, to: c.to === id ? successor : c.to })),
  }))
}

function expression(condition: Condition): string {
  const value = condition.source.endsWith(".exit_code")
    ? String(Number(condition.value)) : JSON.stringify(condition.value)
  return condition.comparison === "in" || condition.comparison === "not in"
    ? `${value} ${condition.comparison} ${condition.source}`
    : `${condition.source} ${condition.comparison} ${value}`
}

export function graphOf(name: string, steps: StepDraft[]): TaskGraph {
  return {
    name, entry: steps[0]?.id ?? "", max_steps: 100,
    nodes: steps.map(step => ({
      id: step.id, type: step.kind, description: step.name,
      ...(step.kind === "agent" ? {
        prompt: step.text, ...(step.role.trim() ? { role: step.role.trim() } : {}),
        system: "Project memory:\n{{ input.get('memory') or '' }}\n\nEarlier runs and your notes:\n{{ input.get('journal') or '' }}",
        max_turns: 40,
        tools: step.tools ? ["files", "shell"] : [], output: { as: step.id }, next: step.next,
      } : step.kind === "command" ? {
        command: step.text, output: { as: step.id }, next: step.next,
      } : step.kind === "confirm" ? {
        prompt: step.text, choices: step.choices.split("\n").map(s => s.trim()).filter(Boolean),
      } : {
        branches: step.conditions.map(c => ({ when: expression(c), to: c.to })), default: step.next,
      }),
    })),
  }
}

export function stepProblems(steps: StepDraft[]): string[] {
  const problems: string[] = []
  const ids = new Set(steps.map(s => s.id))
  const results = new Set(resultsFrom(steps).map(r => r.value))
  for (const step of steps) {
    if (!step.name.trim()) problems.push("Give each step a name.")
    if (step.kind !== "router" && !step.text.trim()) {
      problems.push(`${step.kind === "command" ? "Write a command" : step.kind === "confirm" ? "Write a question" : "Write instructions"} for ${step.name}.`)
    }
    if (step.kind === "command" && step.text.trim().includes("\n")) {
      problems.push(`Use one command for ${step.name}; add another step for another command.`)
    }
    for (const match of step.text.matchAll(/\{\{\s*(step_\d+)\b/g)) {
      if (!ids.has(match[1])) problems.push(`Instructions for ${step.name} refer to a removed result.`)
    }
    if (step.kind === "confirm") {
      const choices = step.choices.split("\n").map(s => s.trim()).filter(Boolean)
      if (new Set(choices).size < 2 || new Set(choices).size !== choices.length) {
        problems.push(`Give ${step.name} at least two different choices.`)
      }
    }
    for (const condition of step.conditions) {
      if (!results.has(condition.source)) problems.push(`Choose a result for the condition in ${step.name}.`)
      if (condition.source.endsWith(".exit_code") && !/^-?\d+$/.test(condition.value.trim())) {
        problems.push(`Use a whole number for the exit code in ${step.name}.`)
      }
    }
  }
  const reached = new Set<string>()
  const visit = (id: string | null) => {
    if (id === null || reached.has(id)) return
    reached.add(id)
    const step = steps.find(s => s.id === id)
    if (!step) { problems.push("Choose an existing next step."); return }
    if (step.kind !== "confirm") visit(step.next)
    for (const c of step.conditions) visit(c.to)
  }
  if (steps[0]) visit(steps[0].id)
  for (const step of steps) {
    if (!reached.has(step.id)) problems.push(`${step.name} cannot be reached. Choose it as a next step.`)
    const references = [
      ...step.conditions.map(c => ({ id: c.source.split(".")[0], use: "the condition" })),
      ...[...step.text.matchAll(/\{\{\s*(step_\d+)\b/g)].map(m => ({ id: m[1], use: "instructions" })),
    ]
    for (const reference of references) {
      const source = steps.find(s => s.id === reference.id)
      if (!source) continue
      // A result is available only if every path to its reader first passes
      // its writer. Looking for a path with the writer removed also handles
      // loops, without assuming the form's row order is execution order.
      const bypass = new Set<string>()
      const walk = (id: string | null) => {
        if (id === null || id === source.id || bypass.has(id)) return
        bypass.add(id)
        const node = steps.find(s => s.id === id)
        if (node && node.kind !== "confirm") walk(node.next)
        node?.conditions.forEach(c => walk(c.to))
      }
      walk(steps[0]?.id ?? null)
      if (source.id === step.id || bypass.has(step.id)) {
        problems.push(`${source.name} must run before ${reference.use} in ${step.name} can use its result.`)
      }
    }
  }
  return [...new Set(problems)]
}
