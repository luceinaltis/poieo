/**
 * Where a work graph's boxes go, and in what order a graph's nodes are read.
 *
 * Pure, and tested on its own, because this is the part of drawing a graph
 * that has an answer capable of being wrong. What the DOM does afterwards --
 * measuring boxes, running an arrow between two of them -- is arrangement, and
 * jsdom has no geometry to check it against anyway.
 */

import type { GraphShape } from "../types"

export interface Placed {
  task: string
  column: number
  row: number
}

/**
 * Flows laid out left to right, each one past whatever hands to it.
 *
 * Kahn's peeling, so a task sits one column beyond its *furthest* sender
 * rather than its nearest -- otherwise a long arrow that skips a task would
 * point backwards on screen.
 *
 * Flows nothing points at start on the left. A board where *nothing* hands to
 * anything is laid out as a grid instead of a column: the axis only carries
 * depth when something points somewhere, so with nothing pointing it is free,
 * and a single column of independent work reads as a failure to lay anything
 * out even though it was the layout.
 *
 * A cycle cannot be peeled at all -- nothing in one has all its senders
 * placed -- so peeling stalls and the loop is broken at the first task
 * declared, which unrolls it into a line with one arrow coming back. Piling
 * the leftovers into a single column instead would make every arrow among
 * them run backwards, including the ones that go forwards.
 */
export function place(tasks: string[], handoffs: Record<string, string[]>, across = 4): Placed[] {
  const rank = new Map(tasks.map((task, index) => [task, index]))
  const targets = (task: string): string[] =>
    (handoffs[task] ?? []).filter((to) => rank.has(to) && to !== task)

  // **Nothing hands to anything, so left-to-right means nothing** -- and a
  // column is then not a reading of the work, it is a column. Laid out as a
  // grid instead, which says the same thing (these are independent) while
  // using the board a reader is looking at. The moment one task hands to
  // another the axis carries depth again, and every rule below applies.
  if (!tasks.some((task) => targets(task).length > 0)) {
    const wide = Math.max(1, across)
    return tasks.map((task, index) => ({
      task,
      column: index % wide,
      row: Math.floor(index / wide),
    }))
  }

  const waiting = new Map(tasks.map((task) => [task, 0]))
  for (const task of tasks) {
    for (const to of targets(task)) waiting.set(to, waiting.get(to)! + 1)
  }

  const column = new Map<string, number>()
  const left = new Set(tasks)
  let layer = tasks.filter((task) => waiting.get(task) === 0)
  let depth = 0

  while (left.size > 0) {
    if (layer.length === 0) {
      // Peeling has stalled, which means a cycle: nothing left has all its
      // senders placed. Break it at the first task declared and carry on.
      // Left in a heap they would share one column, and then *every* arrow
      // between them would run backwards -- including the ones going
      // forwards, which is most of them.
      const seed = tasks.find((task) => left.has(task))
      if (seed === undefined) break
      layer = [seed]
    }
    for (const task of layer) {
      column.set(task, depth)
      left.delete(task)
    }
    const next: string[] = []
    for (const task of layer) {
      for (const to of targets(task)) {
        if (!left.has(to)) continue
        waiting.set(to, waiting.get(to)! - 1)
        if (waiting.get(to) === 0) next.push(to)
      }
    }
    // Declared order decides who is above whom, at every depth, so the board
    // does not rearrange itself when an unrelated task is added.
    layer = next.sort((a, b) => rank.get(a)! - rank.get(b)!)
    depth += 1
  }

  const filled = new Map<number, number>()
  return tasks.map((task) => {
    const at = column.get(task)!
    const row = filled.get(at) ?? 0
    filled.set(at, row + 1)
    return { task, column: at, row }
  })
}

/**
 * A graph's nodes in the order a reader meets them, entry first.
 *
 * Depth first along `next`, then `default`, then the branches in the order
 * they were written -- which is the order they read on the page. Every node
 * once: a graph may loop, and a walk that followed one would not stop.
 */
export function walk(shape: GraphShape): string[] {
  const byId = new Map(shape.nodes.map((node) => [node.id, node]))
  const seen = new Set<string>()
  const order: string[] = []

  const visit = (id: string | null): void => {
    if (id === null || seen.has(id)) return
    const node = byId.get(id)
    if (node === undefined) return
    seen.add(id)
    order.push(id)
    visit(node.next)
    visit(node.default)
    for (const branch of node.branches) visit(branch.to)
  }

  visit(shape.entry)
  // GraphSpec refuses an unreachable node, so this cannot happen against a
  // daemon that validated the graph. It can happen against an older one, and
  // dropping a node silently is the one thing worse than drawing it last.
  for (const node of shape.nodes) {
    if (!seen.has(node.id)) {
      seen.add(node.id)
      order.push(node.id)
    }
  }
  return order
}

/** Where one node sits inside a border: a step across, a sibling down. */
export interface Cell {
  id: string
  column: number
  row: number
}

/** Everywhere a node points: `next`, then `default`, then its branches. */
export function targets(node: GraphShape["nodes"][number]): string[] {
  return [node.next, node.default, ...node.branches.map((branch) => branch.to)].filter(
    (to): to is string => to !== null,
  )
}

/**
 * A graph's nodes on a grid: a column per step from the entry, a row per arm.
 *
 * Laid out in one wrapping line, a router's arms read as four steps in a row
 * -- which is the one thing about a branching graph a reader needs and the
 * line could never say. A column is how far along the run a node is; nodes
 * sharing a column are alternatives at that point.
 *
 * Depth comes off `walk`'s own descent rather than a longest-path pass,
 * because a graph here may loop: an edge back to a node already placed is not
 * another step forward, and counting it as one would march a cycle off the
 * right-hand edge of the border for as long as the walk cared to go.
 */
export function depths(shape: GraphShape): Cell[] {
  const byId = new Map(shape.nodes.map((node) => [node.id, node]))
  const column = new Map<string, number>()
  const seen = new Set<string>()

  const visit = (id: string, at: number): void => {
    if (seen.has(id)) return
    const node = byId.get(id)
    if (node === undefined) return
    seen.add(id)
    column.set(id, at)
    for (const to of targets(node)) visit(to, at + 1)
  }
  visit(shape.entry, 0)

  const filled = new Map<number, number>()
  return walk(shape).map((id) => {
    // A node the walk reached but this descent did not is unreachable, which
    // GraphSpec refuses; drawn last, in a column of its own, rather than lost.
    const at = column.get(id) ?? 0
    const row = filled.get(at) ?? 0
    filled.set(at, row + 1)
    return { id, column: at, row }
  })
}

/**
 * The nodes something in the column to their left points at.
 *
 * Which is where the connector goes -- on the node being arrived at, not on
 * the one leading away. A router points at every one of its arms, and an
 * arrow hung off the router could only be drawn to one of them; hung off each
 * arm, all three are drawn and they converge on the router by themselves.
 *
 * Nodes sharing a column are alternatives, never a chain, so nothing is drawn
 * between them.
 */
export function arrivals(shape: GraphShape): string[] {
  const byId = new Map(shape.nodes.map((node) => [node.id, node]))
  const cells = depths(shape)
  const before = new Map<number, string[]>()
  for (const cell of cells) {
    before.set(cell.column, [...(before.get(cell.column) ?? []), cell.id])
  }
  return cells
    .filter((cell) =>
      (before.get(cell.column - 1) ?? []).some((from) => {
        const node = byId.get(from)
        return node !== undefined && targets(node).includes(cell.id)
      }),
    )
    .map((cell) => cell.id)
}

/**
 * The nodes a run can stop on, in walk order.
 *
 * What an outgoing handoff arrow leaves from once a task is opened. Shut, the
 * arrow leaves the border and says "when chores finishes"; open, it leaves the
 * node it really leaves from and says "when chores reaches gate".
 *
 * A router counts when any one of its arms goes nowhere -- the run can end
 * there even though it need not.
 */
export function exits(shape: GraphShape): string[] {
  const byId = new Map(shape.nodes.map((node) => [node.id, node]))
  return walk(shape).filter((id) => {
    const node = byId.get(id)
    if (node === undefined) return false
    if (node.branches.some((branch) => branch.to === null)) return true
    return node.next === null && node.default === null && node.branches.length === 0
  })
}

/**
 * How much room a task takes, and where an arrow meets it.
 *
 * Fixed, so every arrow's geometry is arithmetic rather than a measurement --
 * which is what lets it be tested at all, jsdom having no layout to measure.
 * A box may grow taller than `height` when it is opened; `head` is why that
 * does not drag its arrows down with it.
 *
 * The width is what a task's steps need, not what its name needs: they are
 * drawn on a shut border now, and at 260 a chain of four wrapped onto three
 * lines and stopped reading as a sequence.
 */
export const BOX = { width: 348, height: 132, gapX: 104, gapY: 22, head: 21, around: 34 }

export interface Anchor {
  x: number
  y: number
}

/**
 * What the rows actually came out as, once the boxes were laid out.
 *
 * `BOX.height` is a *pitch* -- an assumption about how tall a border is -- and
 * a border is as tall as its graph and whatever it last said. The assumption
 * was close enough while the nodes inside were one line; it is not, now that
 * they are a grid. Rows measured on the page are passed in here; nothing is
 * passed in the tests, where the arithmetic is the point.
 */
export interface Frame {
  /** The top of each row. */
  tops: number[]
  /** The underside of the lowest box on the board. */
  bottom: number
  /** How tall each box actually came out, by task. */
  heights: Record<string, number>
}

/** A size in board coordinates, before any of this is scaled. */
export interface Size {
  width: number
  height: number
}

/**
 * Where the board sits in its viewport, and how far it is scaled.
 *
 * Applied as one transform, so everything drawn -- boxes, arrows, the words on
 * them -- moves together and none of the geometry above has to know that a
 * view exists.
 */
export interface View {
  x: number
  y: number
  zoom: number
}

/**
 * The view that puts the whole board on screen at once.
 *
 * Scaled down only, never up: four boxes magnified to fill a wide screen would
 * shout at a reader who asked to see a board, and the type sizes were chosen
 * to be read at 1. So a board that already fits is simply centred.
 *
 * `margin` is kept clear on every side, which is why it is subtracted before
 * the ratio rather than after -- fitting to the full width and then insetting
 * would push the edges back out past it.
 */
export function fit(board: Size, host: Size, margin = 24): View {
  const room = {
    width: Math.max(0, host.width - margin * 2),
    height: Math.max(0, host.height - margin * 2),
  }
  const zoom = Math.min(
    1,
    board.width > 0 ? room.width / board.width : 1,
    board.height > 0 ? room.height / board.height : 1,
  )
  return {
    x: (host.width - board.width * zoom) / 2,
    y: (host.height - board.height * zoom) / 2,
    zoom,
  }
}

/**
 * How far a view may be scaled by hand.
 *
 * The floor is not the fit's: a fit may go below it, because showing the whole
 * board is worth more than legible type and there is no other way to see the
 * shape. Reaching that by hand, past the point of reading anything, only loses
 * the board. The ceiling stops a board becoming one box and a lot of felt.
 */
export const ZOOM = { min: 0.1, max: 4 }

/* Sliding and scaling a view by hand is `d3-zoom`'s, not this module's. Both
   were four lines of arithmetic here and correct for a mouse; what they did
   not have is the trackpad pinch, the two-finger touch and the keyboard paths
   a reader reaches for first. `ZOOM` stays, because the bounds are poieo's
   judgement rather than the gesture's. */

/** A rectangle in minimap coordinates. */
export interface Patch {
  x: number
  y: number
  width: number
  height: number
}

/**
 * How small the whole board has to be drawn to sit in a corner of the screen.
 *
 * One scale for both axes, decided by whichever side is tighter, so a long
 * board is drawn long rather than squashed into the shape of its frame.
 */
export function minimap(board: Size, room: Size): Size & { zoom: number } {
  const zoom = Math.min(
    board.width > 0 ? room.width / board.width : 1,
    board.height > 0 ? room.height / board.height : 1,
  )
  return { zoom, width: board.width * zoom, height: board.height * zoom }
}

/**
 * The part of the board the window is showing, in minimap coordinates.
 *
 * The inverse of the view transform: a screen point is `(screen - view) / zoom`
 * on the board, so the window's own corners say which piece of board is
 * visible. Clipped to the board, because a reader who has panned past the edge
 * is looking partly at nothing, and a rectangle drawn outside the minimap
 * reads as a bug rather than as "you have gone too far".
 */
export function looking(
  view: View,
  window: Size,
  map: { zoom: number; board?: Size },
): Patch {
  const left = -view.x / view.zoom
  const top = -view.y / view.zoom
  const right = left + window.width / view.zoom
  const bottom = top + window.height / view.zoom

  const edge = map.board
  const x0 = Math.max(0, left)
  const y0 = Math.max(0, top)
  const x1 = edge ? Math.min(edge.width, right) : right
  const y1 = edge ? Math.min(edge.height, bottom) : bottom
  return {
    x: x0 * map.zoom,
    y: y0 * map.zoom,
    width: Math.max(0, x1 - x0) * map.zoom,
    height: Math.max(0, y1 - y0) * map.zoom,
  }
}

/** Move the view so a point on the board sits in the middle of the window. */
export function centreOn(view: View, on: { x: number; y: number }, window: Size): View {
  return {
    x: window.width / 2 - on.x * view.zoom,
    y: window.height / 2 - on.y * view.zoom,
    zoom: view.zoom,
  }
}

/** The top-left corner of a task's box. */
export function corner(at: Placed, frame?: Frame): Anchor {
  return {
    x: at.column * (BOX.width + BOX.gapX),
    y: frame?.tops[at.row] ?? at.row * (BOX.height + BOX.gapY),
  }
}

/**
 * Whether a handoff runs backwards -- to a task no further right than its own.
 *
 * `place` lays tasks out by who hands to whom, so a handoff normally lands in
 * a later column and the arrow has the gap between them to itself. A cycle has
 * no such order: `place` cannot peel one, and drops whatever is left into a
 * single column. Drawn as though it went forwards, such an arrow runs
 * right-to-left through every box between the two, which paint over it -- it
 * survives only as stubs in the gaps between rows.
 */
export function loops(from: Placed, to: Placed): boolean {
  return to.column <= from.column
}

/** The way round for a handoff that goes back. */
export interface BackWire extends Wire {
  /** The height of the long return leg, clear below every box. */
  under: number
}

/**
 * The way round for a handoff that goes back: out of the sender's right edge,
 * round past the boards's right-hand side, along underneath everything, and up
 * into the *underside* of the target.
 *
 * Arriving underneath is the whole point. A forward arrow always leaves a
 * right edge and arrives at a left one, so an arrow coming up from below
 * cannot be read as one, and the reader is told "back to here" without a word
 * for it. Taken straight across at header height instead -- the obvious
 * route -- the return leg runs through every box and every label between the
 * two, because that is exactly the height everything else is drawn at.
 *
 * `lastRow` is the bottom row on the board, so the return leg can be put
 * below all of it rather than in whatever gap happens to be nearest. Where a
 * `Frame` was measured it is used instead, because a border is as tall as its
 * graph and `BOX.height` only ever guessed.
 */
export function backWire(
  from: Placed,
  to: Placed,
  lastRow: number,
  frame?: Frame,
): BackWire {
  const start = corner(from, frame)
  const end = corner(to, frame)
  const floor = frame?.bottom ?? lastRow * (BOX.height + BOX.gapY) + BOX.height
  return {
    x1: start.x + BOX.width,
    y1: start.y + BOX.head,
    turn: Math.max(start.x, end.x) + BOX.width + BOX.around,
    under: floor + BOX.gapY / 2,
    // Up into the middle of the target's underside.
    x2: end.x + BOX.width / 2,
    y2: end.y + (frame?.heights[to.task] ?? BOX.height),
  }
}

/** Where an arrow starts, where it bends, and where it ends. */
export interface Wire {
  x1: number
  y1: number
  /** The x the line bends around, and where its word sits. */
  turn: number
  x2: number
  y2: number
}

/**
 * The line an arrow runs along between two boxes: out of one's right edge and
 * into the other's left, both level with the header rather than the middle.
 */
export function wire(from: Placed, to: Placed, frame?: Frame): Wire {
  const start = corner(from, frame)
  const end = corner(to, frame)
  const x1 = start.x + BOX.width
  const x2 = end.x
  return {
    x1,
    y1: start.y + BOX.head,
    turn: (x1 + x2) / 2,
    x2,
    y2: end.y + BOX.head,
  }
}
