/**
 * The workshop's geometry, with no canvas in sight.
 *
 * Everything here is a pure function of the stage: where a bench stands, how
 * the figure at it is standing, whether the lamp is on. index.ts turns that
 * into PixiJS. Splitting it this way is what lets the arrangement be tested
 * at all -- the drawing itself is verified by looking.
 */

import type { Worker } from "../../state/stage"

export interface Spot {
  x: number
  y: number
}

/** Floor footprint of one bench, in room units. */
export const BENCH = { width: 220, depth: 150 }

/** How many benches stand in a row before the workshop starts another. */
const PER_ROW = 3

export type Pose = "sitting" | "working" | "alarmed"

/** A 2:1 isometric projection: floor coordinates to screen offsets. */
export function toIso(x: number, y: number): Spot {
  return { x: (x - y) * 0.5, y: (x + y) * 0.25 }
}

/**
 * Screen offsets back to floor coordinates.
 *
 * A dragged bench arrives as a screen position, and what gets remembered is
 * where it stands on the floor -- so the arrangement survives any change to
 * the projection.
 */
export function fromIso(sx: number, sy: number): Spot {
  return { x: sx + 2 * sy, y: 2 * sy - sx }
}

/** Where the workshop puts benches when nobody has moved them. */
export function benchLayout(count: number): Spot[] {
  const spots: Spot[] = []
  for (let i = 0; i < count; i += 1) {
    spots.push({
      x: (i % PER_ROW) * BENCH.width,
      y: Math.floor(i / PER_ROW) * BENCH.depth,
    })
  }
  return spots
}

/**
 * Merge the automatic arrangement with whatever the reader dragged.
 *
 * A saved spot for a flow that no longer exists is dropped rather than kept:
 * flows come and go, and the file should not accumulate ghosts.
 */
export function place(
  flows: string[],
  saved: Record<string, Spot> = {},
): Record<string, Spot> {
  const auto = benchLayout(flows.length)
  const placed: Record<string, Spot> = {}
  flows.forEach((flow, index) => {
    placed[flow] = saved[flow] ?? auto[index]
  })
  return placed
}

export function figurePose(worker: Worker): Pose {
  if (worker.status === "error") return "alarmed"
  return worker.status === "running" ? "working" : "sitting"
}

export function lampLit(worker: Worker): boolean {
  return worker.status === "running"
}

export function bubbleVisible(worker: Worker): boolean {
  return worker.lastThinking.trim().length > 0
}

/** Finished pieces on the shelf. Attempts do not count; only work that landed. */
export function shelfCount(worker: Worker): number {
  return worker.recent.succeeded
}

export function transitionMs(reducedMotion: boolean): number {
  return reducedMotion ? 0 : 220
}

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  )
}
