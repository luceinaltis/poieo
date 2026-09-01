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
export function durationOf(run: RunSummary): string {
  const ms = new Date(run.finished_at).getTime() - new Date(run.started_at).getTime()
  if (!Number.isFinite(ms) || ms < 0) return ""
  if (ms < 1000) return `${ms}ms`
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`
  const minutes = Math.floor(ms / 60_000)
  return `${minutes}m ${Math.round((ms % 60_000) / 1000)}s`
}

export function sizeOf(run: RunSummary): string {
  const change = run.change
  if (change) {
    const files = change.files.length
    return `+${change.insertions} / -${change.deletions} · ${files} file${files === 1 ? "" : "s"}`
  }
  // Nothing changed to count, so the other thing a run spends. Local models
  // make this free, which is exactly when a reader stops watching it -- but a
  // bound cloud model makes it the number they came for.
  //
  // What it sends is the larger half and used to be missing entirely. An agent
  // step resends its whole conversation every turn, so a run that answered in
  // 6,578 tokens can have sent 160,360 getting there -- and when such a run
  // dies, that is the number that says why. The cached share is the other half
  // of it: resending looks ruinous until you see how much of it the endpoint
  // already had.
  const out = run.usage?.output_tokens ?? 0
  const sent = run.usage?.input_tokens ?? 0
  const cached = run.usage?.cache_read_tokens ?? 0
  const cacheParts = cached + (run.usage?.cache_write_tokens ?? 0)
  // Older Claude runs stored three disjoint counters, before input_tokens was
  // normalised to the whole prompt. That shape is impossible for a new run.
  const total = cacheParts > sent ? sent + cacheParts : sent
  // One number, because the row is 440px wide and the run's own sentence is
  // what the other column is for. When both are known, sent is the one worth
  // the space: it is the half that grows without bound and the half that says
  // why a run stopped. Output alone still shows for a backend that reports
  // nothing else.
  if (total > 0) {
    const share = cached > 0 ? ` · ${Math.round((cached / total) * 100)}% cached` : ""
    return `${counted(total)} sent${share}`
  }
  return out > 0 ? `${counted(out)} tokens` : ""
}

/** Six figures is unreadable without separators, and the locale is pinned so
 *  that a number quoted from one machine's board matches another's. */
const counted = (n: number): string => n.toLocaleString("en-US")

/** The first line of what the model said, short enough to sit in a row. */
function firstLine(said: string, limit = 90): string {
  const line = said.trim().split(/\r?\n/).find((part) => part.trim()) ?? ""
  return line.length > limit ? `${line.slice(0, limit).trimEnd()}…` : line
}

export function accountOf(run: RunSummary, tracked: boolean): string {
  const outcome = outcomeOf(run, tracked)
  if (outcome === "failed") return run.error || "stopped early"
  if (outcome === "nothing") return "found nothing to do"
  if (run.change?.message) return run.change.message
  // A task that keeps no private copy has no change to describe itself with,
  // and a run that touched no file has no change at all -- which used to leave
  // every row reading the same "3 steps", the graph's shape rather than news
  // about any of them. The run's own closing sentence is the news.
  const said = firstLine(run.said ?? "")
  if (said) return said
  const steps = `${run.steps} step${run.steps === 1 ? "" : "s"}`
  const spent = durationOf(run)
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
              <span className="run-meta">
                <span className="run-when">{shortTime(run.started_at)}</span>
                <span className="run-size">{sizeOf(run)}</span>
              </span>
              <span className="run-what">{accountOf(run, tracked)}</span>
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
