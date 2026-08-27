/**
 * Which square the reader put each bench on.
 *
 * Positions live with this skin, not in StageState: a list has no meaningful
 * square, and putting them in the contract would make every future skin carry
 * a concept it never uses.
 */

import type { Cell } from "./scene"

/**
 * Bumped twice. The first release treated a four-pixel tap as a drag, so
 * phones collected arrangements nobody meant to make; the second stored loose
 * floor coordinates rather than squares. Neither is worth migrating.
 */
const KEY = "poieo.atelier.benches.v3"

export function savedSpots(): Record<string, Cell> {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, Cell>
    const clean: Record<string, Cell> = {}
    for (const [task, cell] of Object.entries(parsed ?? {})) {
      // Anything that is not a pair of whole numbers is someone else's data.
      if (cell && Number.isInteger(cell.col) && Number.isInteger(cell.row)) {
        clean[task] = { col: cell.col, row: cell.row }
      }
    }
    return clean
  } catch {
    return {}
  }
}

export function saveSpot(task: string, cell: Cell): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...savedSpots(), [task]: cell }))
  } catch {
    // A workshop that cannot remember its layout is still a workshop.
  }
}

export function forgetSpots(): void {
  try {
    localStorage.removeItem(KEY)
  } catch {
    /* nothing to do */
  }
}
