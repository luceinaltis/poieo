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
