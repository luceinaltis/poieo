import { expect, test } from "vitest"

import { placeMemories } from "./layout"
import type { MemoryGraph } from "./types"

const graph: MemoryGraph = {
  nodes: [
    {
      slug: "active",
      preview: "active",
      updated_at: "2026-01-01T00:00:00Z",
      scope: ["global"],
      anchors: [],
      standing: true,
      superseded_by: null,
      second_look: [],
      degree: 1,
    },
    {
      slug: "past",
      preview: "past",
      updated_at: "2025-01-01T00:00:00Z",
      scope: ["global"],
      anchors: [],
      standing: false,
      superseded_by: "active",
      second_look: [],
      degree: 1,
    },
  ],
  edges: [{ source: "past", target: "active", kind: "supersedes", strength: 0 }],
  total_nodes: 2,
  total_edges: 1,
  truncated: false,
  edges_truncated: false,
}

test("the memory constellation is deterministic", () => {
  expect(placeMemories(graph)).toEqual(placeMemories(graph))
})

test("set-aside memory sits in the outer shadow", () => {
  const placed = placeMemories(graph)
  const radius = (slug: string) => {
    const point = placed.get(slug)!
    return Math.hypot(point.x, point.y, point.z)
  }

  expect(radius("past")).toBeGreaterThan(radius("active"))
})

test("declared relationships pull memories into the same neighbourhood", () => {
  const standing = graph.nodes.map((node) => ({ ...node, standing: true }))
  const disconnected: MemoryGraph = { ...graph, nodes: standing, edges: [], total_edges: 0 }
  const connected: MemoryGraph = { ...disconnected, edges: graph.edges, total_edges: 1 }
  const distance = (placed: Map<string, { x: number; y: number; z: number }>) => {
    const one = placed.get("active")!
    const other = placed.get("past")!
    return Math.hypot(one.x - other.x, one.y - other.y, one.z - other.z)
  }

  expect(distance(placeMemories(connected))).toBeLessThan(distance(placeMemories(disconnected)))
})

test("the constellation has useful breadth and depth before it is orbited", () => {
  const nodes = Array.from({ length: 12 }, (_, index) => ({
    ...graph.nodes[0],
    slug: `memory-${index.toString().padStart(2, "0")}`,
    degree: index % 4,
  }))
  const placed = placeMemories({ ...graph, nodes, edges: [], total_nodes: nodes.length, total_edges: 0 })
  const span = (axis: "x" | "y" | "z") => {
    const values = [...placed.values()].map((point) => point[axis])
    return Math.max(...values) - Math.min(...values)
  }

  expect(span("x")).toBeGreaterThan(1)
  expect(span("z")).toBeGreaterThan(0.75)
  expect(span("x") / span("y")).toBeGreaterThan(0.8)
})
