/**
 * A task's own steps, laid out as the graph they are.
 *
 * Dagre ranks steps, separates branches, and routes return paths around nodes.
 * Each condition retains its own edge, including paths that end the run.
 * The board overview and the full reading view share that topology.
 */

import dagre from "@dagrejs/dagre"

import type { GraphShape, NodeShape } from "../../types"

/** How big a step is drawn, once its label is in it. */
export interface Size {
  width: number
  height: number
}

export interface LaidStep {
  id: string
  /** The centre, in the box's own coordinates. */
  x: number
  y: number
  width: number
  height: number
  /** The run can stop here: nothing leads on. */
  ends: boolean
  /** Not a step at all -- the small terminal a branch that ends the run lands on. */
  stop: boolean
}

export interface LaidEdge {
  from: string
  /** `null` when this arm ends the run; it lands on a terminal of its own. */
  to: string | null
  /** The word that chooses this way, or "" when there is nothing to choose. */
  label: string
  fallback: boolean
  lines: string[]
  /** The position dagre reserved for the condition label. */
  at: { x: number; y: number } | null
  points: { x: number; y: number }[]
}

export interface LaidSteps {
  steps: LaidStep[]
  edges: LaidEdge[]
  width: number
  height: number
}

/** Somewhere for an arm that ends the run to land. One per arm, never shared:
 *  two different ways of ending are two different facts. */
const stopId = (from: string, index: number): string => `${from} stop${index}`

/**
 * Every way out of a step, and the word that chooses it.
 *
 * `next` is the plain one and has nothing to choose, so it carries no word.
 * `default` does: it is the arm taken when no condition matched, and a reader
 * who cannot tell it from a chosen one is reading a different graph.
 */
function waysOut(node: NodeShape): { to: string | null; label: string; fallback: boolean }[] {
  const out: { to: string | null; label: string; fallback: boolean }[] = []
  if (node.next) out.push({ to: node.next, label: "", fallback: false })
  for (const branch of node.branches) out.push({ to: branch.to, label: branch.label, fallback: false })
  if (node.type === "router") out.push({ to: node.default, label: "default", fallback: true })
  return out
}

export const stepName = (node: NodeShape): string => node.description?.trim() || node.id

/** Keep long conditions readable without letting one label stretch the whole graph. */
function wrapLabel(text: string, width: number): string[] {
  const lines: string[] = []
  let remaining = text
  while (remaining.length > width) {
    const space = remaining.lastIndexOf(" ", width)
    const cut = space > 0 ? space : width
    lines.push(remaining.slice(0, cut))
    remaining = remaining.slice(cut).trimStart()
  }
  if (remaining) lines.push(remaining)
  return lines
}

/**
 * Lay a graph out inside a border.
 *
 * `sizeOf` is asked for each step rather than assumed, because how wide a step
 * is drawn depends on its label and on whether it carries a model or a pair of
 * hands -- things this module cannot see and the caller has already rendered.
 */
export function layOutSteps(shape: GraphShape, sizeOf: (node: NodeShape) => Size, full = false): LaidSteps {
  const graph = new dagre.graphlib.Graph({ multigraph: true })
  graph.setGraph({ rankdir: "LR", nodesep: full ? 36 : 12, ranksep: full ? 56 : 30, marginx: full ? 32 : 3, marginy: full ? 32 : 8 })
  graph.setDefaultEdgeLabel(() => ({}))

  const known = new Map(shape.nodes.map((node) => [node.id, node]))
  for (const node of shape.nodes) graph.setNode(node.id, sizeOf(node))

  const stops = new Set<string>()
  const words = new Map<string, { label: string; fallback: boolean; lines: string[] }>()
  for (const node of shape.nodes) {
    waysOut(node).forEach((way, index) => {
      let to = way.to
      if (to === null) {
        to = stopId(node.id, index)
        stops.add(to)
        graph.setNode(to, full ? { width: 84, height: 30 } : { width: 7, height: 7 })
      } else if (!known.has(to)) {
        // GraphSpec rejects unknown targets; tolerate an incomplete older payload.
        return
      }
      // Reserve label space before routing, using DM Mono's approximate advance.
      const lines = wrapLabel(full && way.fallback ? "Otherwise" : way.label, full ? 26 : 22)
      graph.setEdge(
        node.id,
        to,
        way.label ? { width: Math.max(...lines.map(line => line.length)) * (full ? 7.2 : 6.6) + 12, height: lines.length * 15 + 4, labelpos: "c" } : {},
        String(index),
      )
      words.set(`${node.id} ${index}`, { label: way.label, fallback: way.fallback, lines })
    })
  }

  dagre.layout(graph)

  const leads = new Set(shape.nodes.filter((node) => waysOut(node).length > 0).map((n) => n.id))
  const steps: LaidStep[] = graph.nodes().map((id) => {
    const at = graph.node(id)
    return {
      id,
      x: at.x,
      y: at.y,
      width: at.width,
      height: at.height,
      ends: !stops.has(id) && !leads.has(id),
      stop: stops.has(id),
    }
  })

  const edges: LaidEdge[] = graph.edges().map((at) => {
    const drawn = graph.edge(at)
    const { label, fallback, lines } = words.get(`${at.v} ${at.name}`)!
    return {
      from: at.v,
      to: stops.has(at.w) ? null : at.w,
      label,
      fallback,
      lines,
      at: label && drawn.x !== undefined ? { x: drawn.x, y: drawn.y } : null,
      points: drawn.points,
    }
  })

  const size = graph.graph()
  return { steps, edges, width: size.width ?? 0, height: size.height ?? 0 }
}
