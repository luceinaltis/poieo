import type { Application } from "../types"
import "../application.css"

export function applicationLabel(result?: Application): string {
  if (!result) return ""
  if (result.status === "applied") return result.unchanged || result.accepted === 0 ? "Already included" : result.undo_of ? "Undo applied · task paused" : "Applied to project"
  if (result.status === "undone") return "Undone · task paused"
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

export function ApplicationResult({ result }: { result: Application }) {
  const reason = applicationReason(result)
  return (
    <section className="application-result" aria-label="Change application">
      <p><strong>{applicationLabel(result)}</strong></p>
      {result.repair?.ready ? <p>Overlap repaired and checked again.</p> : null}
      {reason ? <p>{reason}</p> : null}
      {result.checks?.length ? (
        <details>
          <summary>Verification · {result.checks.every((check) => check.exit_code === 0) ? "passed" : "did not pass"}</summary>
          {result.checks.map((check, index) => (
            <div key={index}>
              <p><code>{check.command}</code> · {check.exit_code === 0 ? "passed" : check.exit_code === null ? "could not finish" : `exit ${check.exit_code}`}</p>
              {check.output ? <pre>{check.output}</pre> : null}
            </div>
          ))}
        </details>
      ) : null}
    </section>
  )
}
