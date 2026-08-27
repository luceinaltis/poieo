/**
 * What happened last night, one row per run.
 *
 * The reader is here to decide, so the row leads with what the run said it
 * did. Failed runs are collapsed by default: a night with two crashes and six
 * good runs should read as six good runs, not as a wall of red.
 */

import { useState } from "react"

import { outcomeOf, rollup } from "./rollup"
import type { RunSummary } from "../types"
import { shortTime } from "../when"
import "./review.css"

/** How long a run took, in the coarsest unit that still says something. */
function took(run: RunSummary): string {
  const ms = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
  if (!Number.isFinite(ms) || ms < 0) return ""
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`
  const minutes = Math.floor(ms / 60_000)
  return `${minutes}m ${Math.round((ms % 60_000) / 1000)}s`
}

function size(run: RunSummary): string {
  const change = run.change
  if (change) {
    const files = change.files.length
    return `+${change.insertions} / -${change.deletions} · ${files} file${files === 1 ? "" : "s"}`
  }
  // Nothing changed to count, so the other thing a run spends. Local models
  // make this free, which is exactly when a reader stops watching it -- but a
  // bound cloud model makes it the number they came for.
  const out = run.usage?.output_tokens ?? 0
  return out > 0 ? `${out} tokens` : ""
}

function account(run: RunSummary, tracked: boolean): string {
  const outcome = outcomeOf(run, tracked)
  if (outcome === "failed") return run.error || "stopped early"
  if (outcome === "nothing") return "found nothing to do"
  if (run.change?.message) return run.change.message
  // A task that keeps no private copy has no change to describe itself with,
  // so every row read the same "3 steps" and a list of ten said nothing. How
  // long it took is the one thing always true of a run and always different.
  const steps = `${run.steps} step${run.steps === 1 ? "" : "s"}`
  const spent = took(run)
  return spent ? `${steps} · ${spent}` : steps
}

/**
 * How it has been going, before the list of when.
 *
 * The question a reader opens this with is whether the thing has been working,
 * and ten rows do not answer that as fast as one line does.
 */
function Summary({ runs, tracked }: { runs: RunSummary[]; tracked: boolean }) {
  const sum = rollup(runs, tracked)
  const parts = [`${sum.runs} run${sum.runs === 1 ? "" : "s"}`]
  if (sum.nothingToDo) parts.push(`${sum.nothingToDo} found nothing`)
  if (sum.failed) parts.push(`${sum.failed} failed`)
  const last = runs[0]?.finished_at
  if (last) parts.push(`last ${shortTime(last)}`)

  return (
    <p className="run-summary" data-failing={String(sum.failed > 0)}>
      {parts.join(" · ")}
    </p>
  )
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
      <Summary runs={runs} tracked={tracked} />
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
