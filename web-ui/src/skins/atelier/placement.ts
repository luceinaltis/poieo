/**
 * Where the reader dragged each bench.
 *
 * Positions live with the skin, not in StageState: a list has no meaningful
 * (x, y), and putting coordinates in the contract would make every future skin
 * carry a concept it never uses.
 */

import type { Spot } from "./scene"

const KEY = "poieo.atelier.benches"

export function savedSpots(): Record<string, Spot> {
  try {
    const raw = localStorage.getItem(KEY)
    if (!raw) return {}
    const parsed = JSON.parse(raw) as Record<string, Spot>
    // Anything that is not a pair of numbers is someone else's data.
    const clean: Record<string, Spot> = {}
    for (const [flow, spot] of Object.entries(parsed ?? {})) {
      if (spot && typeof spot.x === "number" && typeof spot.y === "number") {
        clean[flow] = { x: spot.x, y: spot.y }
      }
    }
    return clean
  } catch {
    return {}
  }
}

export function saveSpot(flow: string, spot: Spot): void {
  try {
    localStorage.setItem(KEY, JSON.stringify({ ...savedSpots(), [flow]: spot }))
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
