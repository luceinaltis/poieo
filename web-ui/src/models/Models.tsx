/**
 * Which models this project runs on.
 *
 * The same answer `poieo config` gives, in the browser -- so the terminal and
 * the board cannot disagree about what a project is bound to. Shell UI, not a
 * skin, so it is allowed to read the API; it hangs off the bar rather than off
 * a card because a project's models are the project's, not one task's.
 *
 * Roles are **gated on content**, the way a card's prompt gates its memory
 * block: most projects run everything on one model, and a heading over an
 * empty list is furniture. A project whose file names roles gets them,
 * because without them the panel would be lying by omission -- the default is
 * not what the step pinned to `reader` will use.
 */

import { useEffect, useState } from "react"

import { fetchModels } from "../api"
import type { ModelsReport } from "../api"
import "./models.css"

export function Models({
  project,
  onClose,
}: {
  project: string
  onClose(): void
}) {
  const [report, setReport] = useState<ModelsReport | null | undefined>(undefined)

  useEffect(() => {
    let live = true
    void fetchModels(project).then((answer) => {
      if (live) setReport(answer)
    })
    return () => {
      live = false
    }
  }, [project])

  return (
    <aside className="models" aria-label="Models">
      <header className="models-head">
        <h2>models</h2>
        {report?.binding ? (
          <span className="models-file" title={report.binding.path}>
            {shortPath(report.binding.path)}
          </span>
        ) : null}
        <button type="button" className="models-close" onClick={onClose}>
          ✕
        </button>
      </header>
      {/* One box under the header, because the aside is a two-row grid: left
          loose, its `1fr` lands on whichever child happens to be second and
          stretches that one alone. */}
      <div className="models-body">
        <Body report={report} />
      </div>
    </aside>
  )
}

function Body({ report }: { report: ModelsReport | null | undefined }) {
  if (report === undefined) return <p className="models-note">reading…</p>
  // Null is the daemon not answering, which is a different thing from a
  // project that has no models file -- and only one of them is the reader's
  // to fix.
  if (report === null) {
    return <p className="models-note">the models file could not be read.</p>
  }
  if (!report.binding) {
    return (
      <p className="models-note">
        This project names no models file. `poieo init` writes one.
      </p>
    )
  }

  const roles = Object.entries(report.roles)
  return (
    <>
      <ul className="models-endpoints">
        {Object.entries(report.providers).map(([name, provider]) => (
          <li key={name} data-endpoint={name}>
            <span className="models-endpoint-name">{name}</span>
            <span className="models-kind">{provider.type}</span>
            {/* Only when the endpoint names a variable. One that does not is
                resolving its own credential, which is not news. */}
            {provider.api_key_env ? (
              <span
                className="models-key"
                data-key={provider.api_key_set ? "set" : "missing"}
              >
                {provider.api_key_env}
                {provider.api_key_set ? " ✓" : " — not set"}
              </span>
            ) : null}
          </li>
        ))}
      </ul>

      {/* One list, because "everything" is the first row of the same answer:
          what runs what. A project whose file names no roles is simply a list
          of one, and shows no trace of a feature it does not use. */}
      <ul className="models-bound">
        <li data-role="default">
          <span className="models-role">everything</span>
          <span className="models-ref">{report.default ?? "(nothing named)"}</span>
        </li>
        {roles.map(([role, ref]) => (
          <li key={role} data-role={role}>
            <span className="models-role">{role}</span>
            {/* A role the file names but the binding cannot resolve is a
                broken file, and the one line here worth finding. */}
            <span className="models-ref" data-unresolved={String(ref === null)}>
              {ref ?? "(unresolved)"}
            </span>
          </li>
        ))}
      </ul>
    </>
  )
}

/** The tail of a path: enough to recognise, short enough for a bar. */
function shortPath(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts.slice(-2).join("/")
}
