import { useLayoutEffect, useRef } from "react"

import type { Comparison, StepDraft, StepKind } from "./steps"
import { appendStep, newCondition, removeStep, resultsFrom } from "./steps"
import "./steps.css"

const kinds: Record<StepKind, string> = {
  agent: "Model instructions", command: "Run a command", router: "Choose what happens next", confirm: "Ask a person",
}

export function StepEditor({ steps, onChange, disabled }: {
  steps: StepDraft[]
  onChange(steps: StepDraft[]): void
  disabled: boolean
}) {
  const list = useRef<HTMLOListElement>(null)
  const previous = useRef<string[]>([])
  useLayoutEffect(() => {
    const added = steps.find(step => !previous.current.includes(step.id))
    previous.current = steps.map(step => step.id)
    if (added) {
      list.current?.querySelector<HTMLElement>(`[data-step="${added.id}"] textarea, [data-step="${added.id}"] select`)?.focus()
    }
  }, [steps])
  const update = (id: string, patch: Partial<StepDraft>) =>
    onChange(steps.map(s => s.id === id ? { ...s, ...patch } : s))
  const target = (label: string, value: string | null, change: (value: string | null) => void) => (
    <select aria-label={label} value={value ?? ""} disabled={disabled}
      onChange={e => change(e.target.value || null)}>
      <option value="">End run</option>
      {steps.map(s => <option key={s.id} value={s.id}>{s.name}</option>)}
    </select>
  )

  return (
    <section className="step-editor" aria-label="Task steps">
      <p className="step-intro">Start with the first step. Choose what runs next, or add a condition.</p>
      <ol className="step-list" ref={list}>
        {steps.map((step, index) => {
          const sources = resultsFrom(steps.slice(0, index))
          return (
            <li className="step-item" key={step.id} data-step={step.id}>
              <header className="step-head">
                <span className="step-number" aria-hidden="true">{index + 1}</span>
                <div><span className="step-kind">{kinds[step.kind]}</span>
                  <input className="step-title" aria-label={`Name for ${step.name}`} value={step.name}
                    disabled={disabled} onChange={e => update(step.id, { name: e.target.value })} /></div>
                <button type="button" className="step-remove" disabled={disabled || steps.length === 1}
                  onClick={() => onChange(removeStep(steps, step.id))}>Remove {step.name}</button>
              </header>

              {step.kind !== "router" && (
                <label className="step-field">
                  {step.kind === "command" ? "Command" : step.kind === "confirm" ? "Question" : "Instructions"}
                  <textarea rows={step.kind === "command" ? 2 : 4}
                    aria-label={`${step.kind === "command" ? "Command" : step.kind === "confirm" ? "Question" : "Instructions"} for ${step.name}`}
                    value={step.text} disabled={disabled} onChange={e => update(step.id, { text: e.target.value })} />
                </label>
              )}
              {step.kind === "agent" && <>
                {sources.length > 0 && <div className="step-results">
                  <span>Use an earlier result</span>
                  {steps.slice(0, index).filter(s => s.kind === "agent" || s.kind === "command").map(s => (
                    <button type="button" key={s.id} disabled={disabled} onClick={() => update(step.id, {
                      text: `${step.text}${step.text ? "\n\n" : ""}{{ ${s.id}${s.kind === "command" ? ".output" : ""} }}`,
                    })}>Insert result from {s.name}</button>
                  ))}
                </div>}
                <details className="step-options"><summary>Model and tools</summary>
                  <label className="step-field">Model role
                    <input aria-label={`Model role for ${step.name}`} placeholder="Project default" value={step.role}
                      disabled={disabled} onChange={e => update(step.id, { role: e.target.value })} />
                  </label>
                  <label className="step-check"><input type="checkbox" checked={step.tools} disabled={disabled}
                    onChange={e => update(step.id, { tools: e.target.checked })} />Allow file and command tools</label>
                </details>
              </>}
              {step.kind === "confirm" && <>
                <label className="step-field">Choices, one per line
                  <textarea aria-label={`Choices for ${step.name}`} value={step.choices} disabled={disabled}
                    onChange={e => update(step.id, { choices: e.target.value })} />
                </label>
                <p className="step-hint">This ends the run and waits for your answer on the board.</p>
              </>}

              {step.kind === "router" && <>
                <p className="step-hint">The first matching condition wins.</p>
                {step.conditions.map((condition, i) => {
                  const edit = (patch: Partial<typeof condition>) => update(step.id, {
                    conditions: step.conditions.map((c, n) => n === i ? { ...c, ...patch } : c),
                  })
                  const numeric = condition.source.endsWith(".exit_code")
                  const comparisons: [Comparison, string][] = [
                    ["==", "is"], ["!=", "is not"],
                    ...(numeric ? [[">", "is greater than"], ["<", "is less than"]] : [["in", "contains"], ["not in", "does not contain"]]) as [Comparison, string][],
                  ]
                  return <fieldset className="step-condition" key={i}>
                    <legend>If</legend>
                    <select aria-label={`Result for condition ${i + 1} in ${step.name}`} value={condition.source} disabled={disabled}
                      onChange={e => edit({ source: e.target.value, comparison: "==", value: e.target.value.endsWith(".exit_code") ? "0" : "" })}>
                      <option value="">Choose a result</option>
                      {!sources.some(s => s.value === condition.source) && condition.source &&
                        <option value={condition.source}>Choose another result</option>}
                      {sources.map(s => <option key={s.value} value={s.value}>{s.label}</option>)}
                    </select>
                    <div className="step-comparison">
                      <select aria-label={`Comparison for condition ${i + 1} in ${step.name}`} value={condition.comparison}
                        disabled={disabled} onChange={e => edit({ comparison: e.target.value as Comparison })}>
                        {comparisons.map(([value, label]) => <option key={value} value={value}>{label}</option>)}
                      </select>
                      <input aria-label={`Value for condition ${i + 1} in ${step.name}`} value={condition.value}
                        placeholder={numeric ? "0" : "approved"} disabled={disabled}
                        onChange={e => edit({ value: e.target.value })} />
                    </div>
                    <label className="step-field">Then
                      {target(`Next step for condition ${i + 1} in ${step.name}`, condition.to, to => edit({ to }))}
                    </label>
                    {step.conditions.length > 1 && <button type="button" disabled={disabled}
                      onClick={() => update(step.id, { conditions: step.conditions.filter((_, n) => n !== i) })}>Remove condition {i + 1}</button>}
                  </fieldset>
                })}
                <button type="button" className="step-add-condition" disabled={disabled}
                  onClick={() => update(step.id, { conditions: [...step.conditions, newCondition(steps.slice(0, index))] })}>Add another condition</button>
              </>}

              {step.kind !== "confirm" && <label className="step-field step-next">
                {step.kind === "router" ? "Otherwise" : "Then"}
                {target(`Next step after ${step.name}`, step.next, next => update(step.id, { next }))}
              </label>}
            </li>
          )
        })}
      </ol>
      <div className="step-add" aria-label="Add to the task">
        {([["agent", "Add step"], ["router", "Add condition"], ["command", "Add command"], ["confirm", "Ask a person"]] as const).map(([kind, label]) =>
          <button type="button" key={kind} disabled={disabled} onClick={() => onChange(appendStep(steps, kind))}>{label}</button>)}
      </div>
      <p className="step-hint">A run stops after at most 100 steps, including repeats.</p>
    </section>
  )
}
