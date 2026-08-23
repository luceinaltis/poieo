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
export function figurePose(worker: Worker): Pose {
  if (worker.status === "error") return "alarmed"
  return worker.status === "running" ? "working" : "sitting"
}

export function lampLit(worker: Worker): boolean {
  return worker.status === "running"
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

