/**
 * How the smithy looks at any moment: how the smith stands, whether the forge
 * is lit, where the hammer is in its arc.
 *
 * Pure functions of the stage. index.ts turns them into PixiJS, and
 * tools/preview.py draws the same shapes so a change can be looked at. Where
 * benches stand is not here -- that is shared with every other skin, in
 * ../layout.
 */

import type { Worker } from "../../state/stage"

export {
  CELL,
  ZOOM,
  bounds,
  cellAt,
  cellOrigin,
  clampZoom,
  columnsFor,
  fit,
  key,
  occupied,
  place,
} from "../layout"
export type { Cell, Spot } from "../layout"

export type Pose = "sitting" | "working" | "alarmed"

/**
 * Where the hammer sits at each point of its arc.
 *
 * The pivot is the shoulder and the hammer is long, so a strike much past zero
 * swings the head forward over the anvil instead of down onto the work.
 */
export const HAMMER = { raised: -1.25, struck: 0.02, resting: 1.15 }

/**
 * Where the hammer is in its swing.
 *
 * Slow lift, quick fall -- an even sine reads as waving, not striking.
 */
export function hammerAngle(elapsed: number, period = 900): number {
  const t = ((elapsed % period) + period) % period / period
  const { raised, struck } = HAMMER
  return t < 0.7
    ? struck + (raised - struck) * (t / 0.7)
    : raised + (struck - raised) * ((t - 0.7) / 0.3)
}

/** Sparks fly on the strike, and only while there is work under the hammer. */
export function sparking(worker: Worker, elapsed: number, period = 900): boolean {
  if (figurePose(worker) !== "working") return false
  const t = ((elapsed % period) + period) % period / period
  return t > 0.93
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

/**
 * Finished pieces on the shelf.
 *
 * Attempts do not count, and neither does a flow that keeps no private copy:
 * it produces nothing to put on a shelf, so filling one would be inventing
 * work it never did.
 */
export function shelfCount(worker: Worker): number {
  return worker.tracked ? worker.recent.succeeded : 0
}

export function prefersReducedMotion(): boolean {
  return (
    typeof window !== "undefined" &&
    typeof window.matchMedia === "function" &&
    window.matchMedia("(prefers-reduced-motion: reduce)").matches
  )
}
