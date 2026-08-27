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
  flow: string
  column: number
  row: number
}

/**
 * Flows laid out left to right, each one past whatever hands to it.
 *
 * Kahn's peeling, so a flow sits one column beyond its *furthest* sender
 * rather than its nearest -- otherwise a long arrow that skips a flow would
 * point backwards on screen.
 *
 * Flows nothing points at start on the left, which is where a board with no
 * handoffs at all ends up: one column of independent work. That is the common
 * case today and it must not read as a failure to lay anything out.
 *
 * A cycle cannot be peeled at all -- nothing in one has all its senders
 * placed -- so peeling stalls and the loop is broken at the first flow
 * declared, which unrolls it into a line with one arrow coming back. Piling
 * the leftovers into a single column instead would make every arrow among
 * them run backwards, including the ones that go forwards.
 */
export function place(flows: string[], handoffs: Record<string, string[]>): Placed[] {
  const rank = new Map(flows.map((flow, index) => [flow, index]))
  const targets = (flow: string): string[] =>
    (handoffs[flow] ?? []).filter((to) => rank.has(to) && to !== flow)

  const waiting = new Map(flows.map((flow) => [flow, 0]))
  for (const flow of flows) {
    for (const to of targets(flow)) waiting.set(to, waiting.get(to)! + 1)
  }

  const column = new Map<string, number>()
  const left = new Set(flows)
  let layer = flows.filter((flow) => waiting.get(flow) === 0)
  let depth = 0

  while (left.size > 0) {
    if (layer.length === 0) {
      // Peeling has stalled, which means a cycle: nothing left has all its
      // senders placed. Break it at the first flow declared and carry on.
      // Left in a heap they would share one column, and then *every* arrow
      // between them would run backwards -- including the ones going
      // forwards, which is most of them.
      const seed = flows.find((flow) => left.has(flow))
      if (seed === undefined) break
      layer = [seed]
    }
    for (const flow of layer) {
      column.set(flow, depth)
      left.delete(flow)
    }
    const next: string[] = []
    for (const flow of layer) {
      for (const to of targets(flow)) {
        if (!left.has(to)) continue
        waiting.set(to, waiting.get(to)! - 1)
        if (waiting.get(to) === 0) next.push(to)
      }
    }
    // Declared order decides who is above whom, at every depth, so the board
    // does not rearrange itself when an unrelated flow is added.
    layer = next.sort((a, b) => rank.get(a)! - rank.get(b)!)
    depth += 1
  }

  const filled = new Map<number, number>()
  return flows.map((flow) => {
    const at = column.get(flow)!
    const row = filled.get(at) ?? 0
    filled.set(at, row + 1)
    return { flow, column: at, row }
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
 * What an outgoing handoff arrow leaves from once a flow is opened. Shut, the
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
 * How much room a flow takes, and where an arrow meets it.
 *
 * Fixed, so every arrow's geometry is arithmetic rather than a measurement --
 * which is what lets it be tested at all, jsdom having no layout to measure.
 * A box may grow taller than `height` when it is opened; `head` is why that
 * does not drag its arrows down with it.
 */
export const BOX = { width: 260, height: 132, gapX: 96, gapY: 20, head: 21, around: 34 }

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
  /** How tall each box actually came out, by flow. */
  heights: Record<string, number>
}

/** The top-left corner of a flow's box. */
export function corner(at: Placed, frame?: Frame): Anchor {
  return {
    x: at.column * (BOX.width + BOX.gapX),
    y: frame?.tops[at.row] ?? at.row * (BOX.height + BOX.gapY),
  }
}

/**
 * Whether a handoff runs backwards -- to a flow no further right than its own.
 *
 * `place` lays flows out by who hands to whom, so a handoff normally lands in
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
    y2: end.y + (frame?.heights[to.flow] ?? BOX.height),
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
