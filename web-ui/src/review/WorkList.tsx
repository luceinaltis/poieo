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

function account(run: RunSummary, tracked: boolean): string {
  const outcome = outcomeOf(run, tracked)
  if (outcome === "failed") return run.error || "stopped early"
  if (outcome === "nothing") return "found nothing to do"
  if (run.change?.message) return run.change.message
  // A flow that keeps no private copy has no change to describe itself with.
  return `${run.steps} step${run.steps === 1 ? "" : "s"}`
}

export function WorkList({
  runs,
  selected,
  onSelect,
  tracked = true,
  controls,
}: {
  runs: RunSummary[]
  selected: string | null
  onSelect(runId: string): void
  tracked?: boolean
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

  const failed = runs.filter((run) => outcomeOf(run, tracked) === "failed")
  const shown = showFailed
    ? runs
    : runs.filter((run) => outcomeOf(run, tracked) !== "failed")

  return (
    <div className="work">
      <ol className="work-list">
        {shown.map((run) => (
          <li
            key={run.run_id}
            className="work-row"
            data-run={run.run_id}
            data-outcome={outcomeOf(run, tracked)}
            data-selected={String(run.run_id === selected)}
          >
            <button type="button" className="work-open" onClick={() => onSelect(run.run_id)}>
              <span className="work-when">{shortTime(run.started_at)}</span>
              <span className="work-what">{account(run, tracked)}</span>
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
