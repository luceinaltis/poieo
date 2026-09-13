import type { Application } from "../types"
import "../application.css"

export function applicationLabel(result?: Application): string {
  if (!result) return ""
  if (result.status === "applied") return result.unchanged || result.accepted === 0 ? "Already included" : result.undo_of ? "Undo applied" : "Applied to project"
  if (result.status === "undone") return "Undone"
  if (result.status === "blocked") return "Needs your decision"
  if (result.status === "discarded") return "Discarded"
  return "Ready for review"
}

export function applicationReason(result: Partial<Application>): string {
  if (result.repair?.ready === false && result.repair.reason) return result.repair.reason
  if (result.outside_scope?.length) return `Outside the allowed files: ${result.outside_scope.join(", ")}.`
  if (result.conflict?.length) return `Changes overlap in ${result.conflict.join(", ")}. Your project was kept as it was.`
  if (result.verification_changed?.length) return `A check changed ${result.verification_changed.join(", ")}. Check commands must leave these files unchanged.`
  if (result.dirty?.length) return `Save or commit your edits in ${result.dirty.join(", ")} before applying.`
  return result.stale ?? result.error ?? ""
}

/** The repair the task tried before this verdict, if its permission allowed one. */
function describeRepair(repair: NonNullable<Application["repair"]>): string {
  return repair.ready
    ? repair.run_id ? `repaired first, by run ${repair.run_id}` : "Overlap repaired and checked again."
    : `a repair${repair.run_id ? ` (run ${repair.run_id})` : ""} could not finish: ${repair.reason || "no further detail was recorded"}`
}

/**
 * The checks the change was put through, folded behind their verdict.
 *
 * The line says what a reader scanning wants -- all passed, or which one
 * refused it -- and the rows behind it carry each command's exit code and
 * what it printed, because "verification failed" is the one sentence that
 * always has to be followed by "on what".
 */
export function ApplicationResult({ result: application }: { result: Application }) {
  const checks = application.checks ?? []
  const failed = checks.find((check) => check.exit_code !== 0)
  // A refusal with every check green -- the project moved, a file was out of
  // bounds -- must say so ahead of "2 checks passed", or the line beside
  // "Not applied" reads as a riddle.
  const verdict = failed
    ? failed.exit_code === null ? `${failed.command} did not finish` : `${failed.command} failed (exit ${failed.exit_code})`
    : application.status === "blocked"
      ? applicationReason(application) || "could not be applied"
      : checks.length
        ? `${checks.length} check${checks.length === 1 ? "" : "s"} passed`
        : null
  const repair = application.repair ? (
    <p className="run-repair" data-ready={String(application.repair.ready)}>
      {describeRepair(application.repair)}
    </p>
  ) : null
  if (verdict === null) return repair
  if (checks.length === 0) {
    return (
      <>
        <p className="run-checks run-checks-lead" data-verdict={application.status}>
          {verdict}
        </p>
        {repair}
      </>
    )
  }
  return (
    <>
    <details className="run-checks" data-verdict={application.status}>
      <summary className="run-checks-lead">{verdict}</summary>
      <ul className="run-checks-list">
        {checks.map((check, index) => (
          <li key={index} data-exit={check.exit_code === null ? "none" : String(check.exit_code)}>
            <code className="run-check-command">{check.command}</code>
            <span className="run-check-exit">
              {check.exit_code === null ? "could not finish" : check.exit_code === 0 ? "passed" : `exit ${check.exit_code}`}
            </span>
            {check.output ? <pre className="run-check-output">{check.output}</pre> : null}
          </li>
        ))}
      </ul>
    </details>
    {repair}
    </>
  )
}

