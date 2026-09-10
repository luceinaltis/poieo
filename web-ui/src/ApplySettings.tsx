import { useId, useState } from "react"

import type { ApplySpec } from "./types"
import "./application.css"

export interface ApplyDraft {
  mode: "review" | "auto"
  paths: string
  checks: string
  timeout: number
}

export function draftOf(spec?: ApplySpec): ApplyDraft {
  return {
    mode: spec?.mode ?? "review",
    paths: (spec?.paths ?? []).join("\n"),
    checks: (spec?.checks ?? []).join("\n"),
    timeout: spec?.timeout ?? 120,
  }
}

const lines = (text: string) => text.split("\n").map((line) => line.trim()).filter(Boolean)

export function applicationOf(draft: ApplyDraft): ApplySpec {
  return { mode: draft.mode, paths: lines(draft.paths), checks: lines(draft.checks), timeout: draft.timeout }
}

export function applicationReady(draft: ApplyDraft): boolean {
  return draft.mode === "review" || lines(draft.checks).length > 0
}

/** A task starts with review; automatic application is an explicit choice. */
export function ApplySettings({ value, onChange, disabled = false, keepsCopies = true }: {
  value: ApplyDraft
  onChange(value: ApplyDraft): void
  disabled?: boolean
  keepsCopies?: boolean
}) {
  const [open, setOpen] = useState(false)
  const id = useId()
  return (
    <details className="apply-settings" open={open}>
      <summary onClick={(event) => { event.preventDefault(); setOpen(!open) }}>
        Changes · {value.mode === "auto" ? "Apply automatically" : "Review before applying"}
      </summary>
      {open ? (
        <fieldset disabled={disabled}>
          <legend>How changes reach your project</legend>
          <label className="apply-choice">
            <input type="radio" name={id} value="review" checked={value.mode === "review"}
              onChange={() => onChange({ ...value, mode: "review" })} />
            Review before applying
          </label>
          <label className="apply-choice">
            <input type="radio" name={id} value="auto" checked={value.mode === "auto"}
              onChange={() => onChange({ ...value, mode: "auto" })} />
            Apply automatically
          </label>
          {!keepsCopies ? <p>Automatic application needs Git in the selected task folder. This is checked when you save.</p> : null}
          <p>{value.mode === "auto"
            ? "Apply within the allowed files when every check passes. If work cannot be combined, this task pauses for you."
            : "Keep each change for you to accept. The task continues working on its private copy."}</p>
          <label className="apply-field">
            Allowed files or folders
            <textarea name="application-paths" rows={2} value={value.paths}
              placeholder="Leave empty for the whole task folder"
              onChange={(event) => onChange({ ...value, paths: event.target.value })} />
            <span>One per line, relative to the task folder.</span>
          </label>
          <label className="apply-field">
            Verification commands{value.mode === "auto" ? " (required)" : " (optional)"}
            <textarea name="application-checks" rows={3} value={value.checks}
              placeholder="python -m pytest -q"
              onChange={(event) => onChange({ ...value, checks: event.target.value })} />
            <span>One command per line. Each must pass on the combined changes.</span>
          </label>
        </fieldset>
      ) : null}
    </details>
  )
}
