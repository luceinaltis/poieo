/**
 * Choosing the folder a task works in, from the ones the project has.
 *
 * The folder is the one thing a form here never fills in: it is the place the
 * model's hands may touch, and DESIGN.md keeps that choice with the person.
 * What the form could not do was *say* what the choice was between -- a card
 * spells its folder relative to the tasks folder, so the project itself was
 * `..`, and a reader had to know that. This lists what the daemon would
 * accept, in the daemon's spelling, beside the field it fills. Offering is
 * not inferring: it opens on nothing, or on the folder the field already has.
 *
 * The field stays the truth. A path typed by hand that the list does not
 * have leaves the list unselected rather than the field unchanged.
 */

import { useEffect, useState } from "react"

import { fetchFolders } from "./api"
import type { Folder } from "./api"

export function FolderPick({
  project,
  value,
  disabled = false,
  onPick,
}: {
  project: string
  /** The field's current value, so the list can stand on it when it has it. */
  value: string
  disabled?: boolean
  onPick(path: string): void
}) {
  const [folders, setFolders] = useState<Folder[]>([])

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
  // answer leaves the form exactly as it was.
  if (folders.length === 0) return null

  const chosen = folders.some((folder) => folder.path === value.trim()) ? value.trim() : ""
  return (
    <select
      name="folder-pick"
      className="folder-pick"
      aria-label="Choose a folder in this project"
      value={chosen}
      disabled={disabled}
      onChange={(event) => {
        if (event.target.value) onPick(event.target.value)
      }}
    >
      <option value="">choose from this project…</option>
      {folders.map((folder) => (
        <option key={folder.path} value={folder.path}>
          {folder.name}
        </option>
      ))}
    </select>
  )
}
