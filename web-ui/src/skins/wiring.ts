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
 * A cycle cannot be peeled, so whatever is left over is placed in the column
 * after the last one that could be. Refusing to draw a legitimate feedback
 * loop would be worse than drawing it in a line.
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

  while (layer.length > 0) {
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
  for (const flow of flows) if (!column.has(flow)) column.set(flow, depth)

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
export const BOX = { width: 260, height: 132, gapX: 96, gapY: 20, head: 21 }

export interface Anchor {
  x: number
  y: number
}

/** The top-left corner of a flow's box. */
export function corner(at: Placed): Anchor {
  return {
    x: at.column * (BOX.width + BOX.gapX),
    y: at.row * (BOX.height + BOX.gapY),
  }
}

/**
 * The line an arrow runs along between two boxes: out of one's right edge and
 * into the other's left, both level with the header rather than the middle.
 */
export function wire(from: Placed, to: Placed): { x1: number; y1: number; x2: number; y2: number } {
  const start = corner(from)
  const end = corner(to)
  return {
    x1: start.x + BOX.width,
    y1: start.y + BOX.head,
    x2: end.x,
    y2: end.y + BOX.head,
  }
}
