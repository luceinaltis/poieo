/**
 * Where benches stand, shared by every skin that puts them on a floor.
 *
 * Squares rather than free positions: a bench on a square either fits or is
 * refused, which makes overlap decidable instead of a spacing constant that
 * has to be guessed right.
 */

export interface Cell {
  col: number
  row: number
}

export interface Spot {
  x: number
  y: number
}

/** How much room one bench takes on screen once drawn, in pixels. */
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
 * Inflated by the footprint, because a bench is drawn around its origin and
 * not to the right of it -- centring on the bare origins pushes the room off
 * the left edge by half a bench.
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
