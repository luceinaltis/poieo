/**
 * What happened last night, one row per run.
 *
 * The reader is here to decide, so the row leads with what the run said it
 * did. Failed runs are collapsed by default: a night with two crashes and six
 * good runs should read as six good runs, not as a wall of red.
 */

import { useState } from "react"

import { outcomeOf } from "./rollup"
import type { RunSummary } from "../types"
import { shortTime } from "../when"
import "./review.css"

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

export function RunList({
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
      <p className="run-empty">
        Nothing has run yet. When it does, what it did shows up here.
      </p>
    )
  }

  const failed = runs.filter((run) => outcomeOf(run, tracked) === "failed")
  const shown = showFailed
    ? runs
    : runs.filter((run) => outcomeOf(run, tracked) !== "failed")

  return (
    <div className="run">
      <ol className="run-list">
        {shown.map((run) => (
          <li
            key={run.run_id}
            className="run-row"
            data-run={run.run_id}
            data-outcome={outcomeOf(run, tracked)}
            data-selected={String(run.run_id === selected)}
          >
            <button type="button" className="run-open" onClick={() => onSelect(run.run_id)}>
              <span className="run-when">{shortTime(run.started_at)}</span>
              <span className="run-what">{account(run, tracked)}</span>
              <span className="run-size">{size(run)}</span>
            </button>
            {controls ? <div className="run-controls">{controls(run)}</div> : null}
          </li>
        ))}
      </ol>

      {failed.length > 0 && !showFailed ? (
        <button
          type="button"
          className="run-failed"
          data-failed-toggle="true"
          onClick={() => setShowFailed(true)}
        >
          {failed.length} failed
        </button>
      ) : null}
    </div>
  )
}
