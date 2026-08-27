/**
 * How the smithy looks at any moment: how the smith stands, whether the forge
 * is lit, where the hammer is in its arc.
 *
 * Pure functions of the stage. index.ts turns them into three.js, and
 * tools/bench.ts renders one bench on its own so a change can be looked at.
 * Where benches stand is not here -- that is shared with every other skin,
 * in ../layout.
 */

import type { TaskState } from "../../state/stage"

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
 * How the smith stands: at the anvil, sat waiting, or looking up from it.
 *
 * Three poses and no more. A flowState has more states than this, but a figure
 * seen across a room can only say so much, and the drawer is where the rest
 * is read.
 */
export function figurePose(flowState: TaskState): Pose {
  if (flowState.status === "error") return "alarmed"
  return flowState.status === "running" ? "working" : "sitting"
}

export function lampLit(flowState: TaskState): boolean {
  return flowState.status === "running"
}


/**
 * Finished pieces on the shelf.
 *
 * Attempts do not count, and neither does a task that keeps no private copy:
 * it produces nothing to put on a shelf, so filling one would be inventing
 * work it never did.
 */
export function shelfCount(flowState: TaskState): number {
  return flowState.tracked ? flowState.recent.succeeded : 0
}

