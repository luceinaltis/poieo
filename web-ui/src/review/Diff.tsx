/**
 * One piece of work, read as a diff.
 *
 * Folded by file, because the question is "what did it touch" before it is
 * "what did it write". No highlighting and no new dependency: a unified patch
 * split by file, with added and removed lines marked.
 */

import { useCallback, useEffect, useMemo, useState } from "react"

import { fetchDiff } from "../api"
import type { DiffReport } from "../types"
import "./review.css"

/** Split a unified patch into the hunks belonging to each file. */
export function splitPatch(patch: string): Record<string, string> {
  const byFile: Record<string, string> = {}
  let current: string | null = null

  for (const line of patch.split("\n")) {
    const header = /^diff --git a\/.+ b\/(.+)$/.exec(line)
    if (header) {
      current = header[1]
      byFile[current] = ""
      continue
    }
    if (current === null) continue
    byFile[current] += byFile[current] ? "\n" + line : line
  }
  return byFile
}

function lineKind(line: string): "added" | "removed" | "meta" | "context" {
  if (line.startsWith("+++") || line.startsWith("---")) return "meta"
  if (line.startsWith("@@") || line.startsWith("index ")) return "meta"
  if (line.startsWith("+")) return "added"
  if (line.startsWith("-")) return "removed"
  return "context"
}

function Hunks({ text }: { text: string }) {
  return (
    <pre className="diff-hunks" data-hunks="true">
      {text.split("\n").map((line, index) => (
        <span key={index} className="diff-line" data-line={lineKind(line)}>
          {line}
          {"\n"}
        </span>
      ))}
    </pre>
  )
}

export function Diff({ runId }: { runId: string }) {
  // undefined while reading; null when it could not be read at all.
  const [report, setReport] = useState<DiffReport | null | undefined>(undefined)
  const [open, setOpen] = useState<string | null>(null)

  const read = useCallback(() => {
    let live = true
    setReport(undefined)
    void fetchDiff(runId).then((next) => {
      if (live) setReport(next)
    })
    return () => {
      live = false
    }
  }, [runId])

  useEffect(read, [read])

  // Split once per report, not on every open-a-file toggle of a large patch.
  const byFile = useMemo(() => splitPatch(report?.patch ?? ""), [report])

  if (report === undefined) return <p className="diff-note">reading…</p>

  if (report === null) {
    return (
      <div className="diff-note">
        <p>This change couldn't be read.</p>
        <button type="button" data-retry="true" onClick={read}>
          try again
        </button>
      </div>
    )
  }

  const files = report.files ?? []
  if (files.length === 0) {
    return <p className="diff-note">This work changed no files.</p>
  }

  return (
    <div className="diff">
      {report.truncated ? (
        <p className="diff-note">
          This change was too large to show in full — the files are all here, the
          text of the last ones is not.
        </p>
      ) : null}

      <ol className="diff-files">
        {files.map((file) => (
          <li key={file.path} className="diff-file" data-file={file.path}>
            <button
              type="button"
              className="diff-open"
              onClick={() => setOpen(open === file.path ? null : file.path)}
            >
              <span className="diff-path">{file.path}</span>
              <span className="diff-count">
                +{file.insertions} / -{file.deletions}
              </span>
            </button>
            {open === file.path ? (
              byFile[file.path] ? (
                <Hunks text={byFile[file.path]} />
              ) : (
                <p className="diff-note">The text of this file was not included.</p>
              )
            ) : null}
          </li>
        ))}
      </ol>
    </div>
  )
}
