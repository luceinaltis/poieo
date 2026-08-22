/**
 * What happened last night, one row per piece of work.
 *
 * The reader is here to decide, so the row leads with what the run said it
 * did. Failed work is collapsed by default: a night with two crashes and six
 * good pieces should read as six good pieces, not as a wall of red.
 */

import { useState } from "react"

import { outcomeOf } from "./rollup"
import type { RunSummary } from "../types"
import "./review.css"

function shortTime(iso: string): string {
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? iso : at.toLocaleTimeString()
}

function size(run: RunSummary): string {
  const change = run.change
  if (!change) return ""
  const files = change.files.length
  return `+${change.insertions} / -${change.deletions} · ${files} file${files === 1 ? "" : "s"}`
}

function account(run: RunSummary): string {
  const outcome = outcomeOf(run)
  if (outcome === "succeeded") return run.change?.message || "made a change"
  if (outcome === "nothing") return "found nothing to do"
  return run.error || "stopped early"
}

export function WorkList({
  runs,
  selected,
  onSelect,
  controls,
}: {
  runs: RunSummary[]
  selected: string | null
  onSelect(runId: string): void
  controls?: (run: RunSummary) => React.ReactNode
}) {
  const [showFailed, setShowFailed] = useState(false)

  if (runs.length === 0) {
    return (
      <p className="work-empty">
        Nothing has run yet. When it does, what it did shows up here.
      </p>
    )
  }

  const failed = runs.filter((run) => outcomeOf(run) === "failed")
  const shown = showFailed ? runs : runs.filter((run) => outcomeOf(run) !== "failed")

  return (
    <div className="work">
      <ol className="work-list">
        {shown.map((run) => (
          <li
            key={run.run_id}
            className="work-row"
            data-run={run.run_id}
            data-outcome={outcomeOf(run)}
            data-selected={String(run.run_id === selected)}
          >
            <button type="button" className="work-open" onClick={() => onSelect(run.run_id)}>
              <span className="work-when">{shortTime(run.started_at)}</span>
              <span className="work-what">{account(run)}</span>
              <span className="work-size">{size(run)}</span>
            </button>
            {controls ? <div className="work-controls">{controls(run)}</div> : null}
          </li>
        ))}
      </ol>

      {failed.length > 0 && !showFailed ? (
        <button
          type="button"
          className="work-failed"
          data-failed-toggle="true"
          onClick={() => setShowFailed(true)}
        >
          {failed.length} failed
        </button>
      ) : null}
    </div>
  )
}
