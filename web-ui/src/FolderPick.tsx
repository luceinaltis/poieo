/**
 * Choosing the folder a task works in, from the ones the project has.
 *
 * A card spells its folder relative to the tasks folder, so the project
 * itself is `..`, and a reader had to know that. This lists what the daemon
 * would accept, in the daemon's spelling, labelled as a person reads them.
 *
 * It stands beside a field or alone. Beside the setup form's field, it
 * offers and the field stays the truth: a path typed by hand that the list
 * does not have leaves the list unselected rather than the field unchanged,
 * and with nothing to offer it is not there at all. Alone, on the new-task
 * panel, it is the field: it always stands on the folder the task has,
 * starting on the whole project, and a folder the list does not have -- a
 * seed's, a draft's -- is shown as one more choice rather than hidden.
 */

import { useEffect, useState } from "react"

import { fetchFolders } from "./api"
import type { Folder } from "./api"

export function FolderPick({
  project,
  value,
  disabled = false,
  alone = false,
  onPick,
}: {
  project: string
  /** The folder the task has, so the list can stand on it when it has it. */
  value: string
  disabled?: boolean
  /** The only control for the folder, rather than a list beside a field. */
  alone?: boolean
  onPick(path: string): void
}) {
  const [folders, setFolders] = useState<Folder[]>([])
  // Whether the folder is being written out rather than chosen.
  const [writing, setWriting] = useState(false)

  useEffect(() => {
    let live = true
    void fetchFolders(project).then((list) => {
      if (live) setFolders(list)
    })
    return () => {
      live = false
    }
  }, [project])

  // Nothing to offer is no list at all, not an empty one: a daemon too old to
  // answer leaves the setup form exactly as it was. Alone, the list is the
  // field, and a field cannot be absent.
  if (folders.length === 0 && !alone) return null

  const current = value.trim()
  const known = folders.some((folder) => folder.path === current)
  const select = (
    <select
      name="folder-pick"
      className="folder-pick"
      aria-label="Choose a folder in this project"
      value={writing ? OTHER : alone || known ? current : ""}
      disabled={disabled}
      onChange={(event) => {
        const picked = event.target.value
        setWriting(picked === OTHER)
        if (picked && picked !== OTHER) onPick(picked)
      }}
    >
      {alone ? null : <option value="">choose from this project…</option>}
      {alone && current && !known ? (
        <option value={current}>{current === ".." ? "this project" : current}</option>
      ) : null}
      {folders.map((folder) => (
        <option key={folder.path} value={folder.path}>
          {folder.name}
        </option>
      ))}
      {/* The list stops two levels down and the daemon's fence does not: a
          deeper folder is written out, as the card spells it. */}
      {alone ? <option value={OTHER}>another folder…</option> : null}
    </select>
  )
  if (!writing) return select
  return (
    <>
      {select}
      <input
        name="folder"
        className="folder-typed"
        aria-label="The folder, as the card spells it"
        placeholder="../src/deep/folder"
        value={value}
        disabled={disabled}
        onChange={(event) => onPick(event.target.value)}
      />
    </>
  )
}

/** The list's last choice, which opens the folder as written. Not a path a card could hold. */
const OTHER = "::another"
