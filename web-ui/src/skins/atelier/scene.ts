/**
 * The workshop's geometry, with no canvas in sight.
 *
 * Everything here is a pure function of the stage: which square a bench stands
 * on, how the smith at it is standing, whether the forge is lit. index.ts turns
 * that into PixiJS. Splitting it this way is what lets the arrangement be
 * tested at all -- the drawing itself is verified by looking.
 */

import type { Worker } from "../../state/stage"

export interface Cell {
  col: number
  row: number
}

export interface Spot {
  x: number
  y: number
}

/**
 * One square of the workshop floor, in screen pixels.
 *
 * Tall enough for the whole bench including its label: at 170 the label of one
 * bench disappeared behind the next one down.
 */
export const CELL = { width: 280, height: 250 }

export const key = (cell: Cell): string => `${cell.col},${cell.row}`

/** The screen offset a bench standing on this square is drawn at. */
export function cellOrigin(cell: Cell): Spot {
  return { x: cell.col * CELL.width, y: cell.row * CELL.height }
}

/** Which square a loose position belongs to -- benches never sit between two. */
export function cellAt(x: number, y: number): Cell {
  return { col: Math.round(x / CELL.width), row: Math.round(y / CELL.height) }
}

/** Whether a square already has a bench on it. */
export function occupied(
  placed: Record<string, Cell>,
  cell: Cell,
  except: string,
): boolean {
  return Object.entries(placed).some(
    ([flow, at]) => flow !== except && at.col === cell.col && at.row === cell.row,
  )
}

/**
 * The screen box the arrangement occupies once drawn.
 *
 * A bench is drawn around its origin, not to the right of it, so centring on
 * bare origins pushes the room off the left edge by half a bench.
 */
export function bounds(cells: Cell[]): { x: number; y: number; width: number; height: number } {
  if (cells.length === 0) return { x: 0, y: 0, width: 0, height: 0 }
  const at = cells.map(cellOrigin)
  const xs = at.map((s) => s.x)
  const ys = at.map((s) => s.y)
  return {
    x: Math.min(...xs) - CELL.width / 2,
    y: Math.min(...ys) - CELL.height / 2,
    width: Math.max(...xs) - Math.min(...xs) + CELL.width,
    height: Math.max(...ys) - Math.min(...ys) + CELL.height,
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
 * A tall narrow screen gets one. Three abreast on a phone puts two of them
 * off-stage.
 */
export function columnsFor(screenWidth: number): number {
  return Math.max(1, Math.min(4, Math.floor(screenWidth / CELL.width)))
}

/** How far the room may be zoomed by hand. */
export const ZOOM = { min: 0.3, max: 2.5 }

export function clampZoom(scale: number): number {
  return Math.max(ZOOM.min, Math.min(ZOOM.max, scale))
}

/**
 * Where the workshop puts benches, honouring anything the reader has moved.
 *
 * A saved square for a flow that no longer exists is dropped; two flows can
 * never end up on one square, because a saved square that is already taken
 * falls back to the automatic one.
 */
export function place(
  flows: string[],
  saved: Record<string, Cell> = {},
  columns = 3,
): Record<string, Cell> {
  const placed: Record<string, Cell> = {}
  const taken = new Set<string>()

  for (const flow of flows) {
    const want = saved[flow]
    if (want && !taken.has(key(want))) {
      placed[flow] = want
      taken.add(key(want))
    }
  }

  let next = 0
  for (const flow of flows) {
    if (placed[flow]) continue
    let cell = { col: next % columns, row: Math.floor(next / columns) }
    while (taken.has(key(cell))) {
      next += 1
      cell = { col: next % columns, row: Math.floor(next / columns) }
    }
    placed[flow] = cell
    taken.add(key(cell))
    next += 1
  }
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
