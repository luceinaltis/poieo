/**
 * A task's own steps, laid out as the graph they are.
 *
 * They were a wrapping grid with an arrow drawn before each pill: a column per
 * step from the entry, a row per arm. It read as a sequence, which is most of
 * what a reader wants -- but a router's arms were *implied* by which row a
 * pill landed on, and the way back out of a loop was not drawn at all. A graph
 * with lines you can follow says both without being explained.
 *
 * `dagre` does the layout, which is the part with an answer capable of being
 * wrong and the part nobody should write twice: ranking a directed graph,
 * ordering within a rank to cross as few lines as possible, and routing an
 * edge that runs backwards around the boxes rather than through them.
 *
 * What stays poieo's is what the picture *means* -- which ways out a step has,
 * which word chooses each of them, and where a run can stop.
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
  /** Where the word goes -- dagre's own answer, being the room it kept for it.
   *  Guessing the middle of the line instead put the word where the layout had
   *  not reserved anything, and it landed over a step or off the picture. */
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
function waysOut(node: NodeShape): { to: string | null; label: string }[] {
  const out: { to: string | null; label: string }[] = []
  if (node.next) out.push({ to: node.next, label: "" })
  for (const branch of node.branches) out.push({ to: branch.to, label: branch.label })
  if (node.default) out.push({ to: node.default, label: "default" })
  return out
}

/**
 * Lay a graph out inside a border.
 *
 * `sizeOf` is asked for each step rather than assumed, because how wide a step
 * is drawn depends on its label and on whether it carries a model or a pair of
 * hands -- things this module cannot see and the caller has already rendered.
 */
export function layOutSteps(shape: GraphShape, sizeOf: (node: NodeShape) => Size): LaidSteps {
  const graph = new dagre.graphlib.Graph()
  graph.setGraph({ rankdir: "LR", nodesep: 8, ranksep: 30, marginx: 3, marginy: 8 })
  graph.setDefaultEdgeLabel(() => ({}))

  const known = new Map(shape.nodes.map((node) => [node.id, node]))
  for (const node of shape.nodes) graph.setNode(node.id, sizeOf(node))

  const stops = new Set<string>()
  const words = new Map<string, string>()
  for (const node of shape.nodes) {
    waysOut(node).forEach((way, index) => {
      let to = way.to
      if (to === null) {
        to = stopId(node.id, index)
        stops.add(to)
        graph.setNode(to, { width: 7, height: 7 })
      } else if (!known.has(to)) {
        // A target the board never heard of. `GraphSpec` refuses one, so this
        // is an older daemon rather than a graph -- and dropping the line
        // silently would draw a step as an ending.
        return
      }
      // The word is handed to dagre as a thing with a size, not written on
      // afterwards: told about it, dagre keeps the ranks far enough apart to
      // hold it and puts it where it kept the room. Written over a layout that
      // did not know, it lands across a step or off the end of the picture.
      graph.setEdge(
        node.id,
        to,
        way.label ? { width: way.label.length * 5.4 + 6, height: 11, labelpos: "c" } : {},
      )
      words.set(`${node.id} ${to}`, way.label)
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
    const label = words.get(`${at.v} ${at.w}`) ?? ""
    return {
      from: at.v,
      to: stops.has(at.w) ? null : at.w,
      label,
      at: label && drawn.x !== undefined ? { x: drawn.x, y: drawn.y } : null,
      points: drawn.points,
    }
  })

  const size = graph.graph()
  return { steps, edges, width: size.width ?? 0, height: size.height ?? 0 }
}
