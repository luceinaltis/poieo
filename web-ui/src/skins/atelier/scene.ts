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

/** How much room one bench takes on screen once drawn, in pixels. */
export const FOOTPRINT = { width: 270, height: 170 }

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

/**
 * The screen box the arrangement occupies once drawn.
 *
 * Inflated by the footprint, because a bench is drawn around its anchor and
 * not to the right of it -- centring on the bare anchors pushes the room off
 * the left edge by half a bench.
 */
export function bounds(spots: Spot[]): { x: number; y: number; width: number; height: number } {
  if (spots.length === 0) return { x: 0, y: 0, width: 0, height: 0 }
  const screen = spots.map((spot) => toIso(spot.x, spot.y))
  const xs = screen.map((s) => s.x)
  const ys = screen.map((s) => s.y)
  return {
    x: Math.min(...xs) - FOOTPRINT.width / 2,
    y: Math.min(...ys) - FOOTPRINT.height / 2,
    width: Math.max(...xs) - Math.min(...xs) + FOOTPRINT.width,
    height: Math.max(...ys) - Math.min(...ys) + FOOTPRINT.height,
  }
}

/**
 * How much to shrink the room so the whole arrangement is on screen.
 *
 * Never grows past 1: a workshop with one bench on a wide monitor should not
 * blow that bench up to fill it. There is a floor, because a room scaled to
 * nothing is worse than a room you have to scroll.
 */
export function fit(
  box: { width: number; height: number },
  screen: { width: number; height: number },
): number {
  if (box.width <= 0 || box.height <= 0) return 1
  return Math.max(0.35, Math.min(1, screen.width / box.width, screen.height / box.height))
}

/**
 * How many benches stand across.
 *
 * A tall narrow screen gets one. Three in a row lays them along the
 * projection's diagonal, which is the worst shape a phone could be handed.
 */
export function columnsFor(screenWidth: number): number {
  return Math.max(1, Math.min(4, Math.floor(screenWidth / FOOTPRINT.width)))
}

/**
 * Where the workshop puts benches when nobody has moved them.
 *
 * Arranged in screen space and projected back, rather than guessed on the
 * floor and hoped for: the projection halves one axis and quarters the other,
 * so floor spacing that reads as generous lands on top of itself.
 */
export function benchLayout(count: number, columns = 3): Spot[] {
  const spots: Spot[] = []
  for (let i = 0; i < count; i += 1) {
    spots.push(
      fromIso((i % columns) * FOOTPRINT.width, Math.floor(i / columns) * FOOTPRINT.height),
    )
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
  columns = 3,
): Record<string, Spot> {
  const auto = benchLayout(flows.length, columns)
  const placed: Record<string, Spot> = {}
  flows.forEach((flow, index) => {
    placed[flow] = saved[flow] ?? auto[index]
  })
  return placed
}

export type Pose = "sitting" | "working" | "alarmed"

/** The hammer's rest and strike angles, in radians. */
export const HAMMER = { raised: -1.15, struck: 0.35 }

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

/** How far the room may be zoomed by hand. */
export const ZOOM = { min: 0.3, max: 2.5 }

export function clampZoom(scale: number): number {
  return Math.max(ZOOM.min, Math.min(ZOOM.max, scale))
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
