import { expect, test } from "vitest"

import { arrangeMemories, placeMemories } from "./layout"
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

const completeEdges = (members: string[]) => members.flatMap((source, index) => (
  members.slice(index + 1).map((target) => ({ source, target, kind: "mentions" as const, strength: 0 }))
))

function communityGraph(): MemoryGraph {
  const slugs = ["alpha-1", "alpha-2", "alpha-3", "alpha-4", "beta-1", "beta-2", "beta-3", "beta-4"]
  const nodes = slugs.map((slug) => ({
    ...graph.nodes[0],
    slug,
    preview: slug,
    degree: 3,
  }))
  const edges = [
    ...completeEdges(slugs.slice(0, 4)),
    ...completeEdges(slugs.slice(4)),
    { source: "alpha-4", target: "beta-1", kind: "mentions" as const, strength: 0 },
  ]
  return {
    nodes,
    edges,
    total_nodes: nodes.length,
    total_edges: edges.length,
    truncated: false,
    edges_truncated: false,
  }
}

function linkedRegionsGraph(): MemoryGraph {
  const groups = ["alpha", "beta", "charlie", "delta"].map((prefix) => (
    Array.from({ length: 4 }, (_, index) => `${prefix}-${index + 1}`)
  ))
  const slugs = groups.flat()
  const nodes = slugs.map((slug) => ({ ...graph.nodes[0], slug, preview: slug, degree: 3 }))
  const edges = [
    ...groups.flatMap(completeEdges),
    { source: "beta-4", target: "charlie-1", kind: "mentions" as const, strength: 0 },
  ]
  return {
    nodes,
    edges,
    total_nodes: nodes.length,
    total_edges: edges.length,
    truncated: false,
    edges_truncated: false,
  }
}

function chainGraph(): MemoryGraph {
  const nodes = Array.from({ length: 16 }, (_, index) => ({
    ...graph.nodes[0],
    slug: `chain-${index.toString().padStart(2, "0")}`,
    preview: `chain ${index}`,
    degree: 2,
  }))
  const edges = nodes.slice(0, -1).flatMap((node, index) => {
    const next = nodes[index + 1]
    const linked: MemoryGraph["edges"] = [
      { source: node.slug, target: next.slug, kind: "mentions", strength: 0 },
    ]
    if (index % 2 === 0) linked.push({ source: node.slug, target: next.slug, kind: "depends_on", strength: 0 })
    return linked
  })
  return {
    nodes,
    edges,
    total_nodes: nodes.length,
    total_edges: edges.length,
    truncated: false,
    edges_truncated: false,
  }
}

function distance(one: { x: number; y: number; z: number }, other: { x: number; y: number; z: number }) {
  return Math.hypot(one.x - other.x, one.y - other.y, one.z - other.z)
}

test("the memory constellation is deterministic", () => {
  expect(placeMemories(graph)).toEqual(placeMemories(graph))
})

test("an unrelated memory does not move established regions", () => {
  const established = linkedRegionsGraph()
  const establishedLayout = arrangeMemories(established)
  const before = establishedLayout.positions
  const isolated = {
    ...graph.nodes[0],
    slug: "000-unrelated",
    preview: "unrelated",
    degree: 0,
  }
  const after = arrangeMemories({
    ...established,
    nodes: [...established.nodes, isolated],
    total_nodes: established.total_nodes + 1,
  }, establishedLayout.regionSlots).positions

  for (const [slug, point] of before) expect(after.get(slug)).toEqual(point)
})

test("unrelated relationship families do not move established regions", () => {
  const established = linkedRegionsGraph()
  const establishedLayout = arrangeMemories(established)
  const before = establishedLayout.positions
  const additions = Array.from({ length: 49 }, (_, index) => {
    const prefix = `unrelated-${index.toString().padStart(2, "0")}`
    const extra = communityGraph()
    const rename = (slug: string) => `${prefix}-${slug}`
    return {
      nodes: extra.nodes.map((node) => ({ ...node, slug: rename(node.slug), preview: rename(node.slug) })),
      edges: extra.edges.map((edge) => ({ ...edge, source: rename(edge.source), target: rename(edge.target) })),
    }
  })
  const nodes = [...established.nodes, ...additions.flatMap((addition) => addition.nodes)]
  const edges = [...established.edges, ...additions.flatMap((addition) => addition.edges)]
  const after = arrangeMemories({
    ...established,
    nodes,
    edges,
    total_nodes: nodes.length,
    total_edges: edges.length,
  }, establishedLayout.regionSlots).positions

  for (const [slug, point] of before) expect(after.get(slug)).toEqual(point)
})

test("hidden regions keep their slots reserved when new memory arrives", () => {
  const isolatedGraph = (slugs: string[]): MemoryGraph => ({
    ...graph,
    nodes: slugs.map((slug) => ({ ...graph.nodes[0], slug, preview: slug, degree: 0 })),
    edges: [],
    total_nodes: slugs.length,
    total_edges: 0,
  })
  const cache = new Map<string, number>()
  const remember = (layout: ReturnType<typeof arrangeMemories>) => {
    for (const [community, slot] of layout.regionSlots) cache.set(community, slot)
  }
  const first = arrangeMemories(isolatedGraph(["always-visible", "reserved-old"]), cache)
  remember(first)
  const oldSlot = first.regionSlots.get("reserved-old")!
  const candidate = "new-arrival"

  remember(arrangeMemories(isolatedGraph(["always-visible"]), cache))
  const added = arrangeMemories(isolatedGraph(["always-visible", candidate]), cache)
  remember(added)
  const restored = arrangeMemories(isolatedGraph(["always-visible", candidate, "reserved-old"]), cache)

  expect(added.regionSlots.get(candidate)).not.toBe(oldSlot)
  expect(restored.regionSlots.get(candidate)).toBe(added.regionSlots.get(candidate))
  expect(restored.regionSlots.get("reserved-old")).toBe(oldSlot)
  expect(restored.positions.get(candidate)).toEqual(added.positions.get(candidate))
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

test("densely related memories occupy their own regions across a weak bridge", () => {
  const layout = arrangeMemories(communityGraph())
  const alpha = ["alpha-1", "alpha-2", "alpha-3", "alpha-4"]
  const beta = ["beta-1", "beta-2", "beta-3", "beta-4"]
  const communityOf = (slugs: string[]) => new Set(slugs.map((slug) => layout.communities.get(slug)))
  expect(communityOf(alpha).size).toBe(1)
  expect(communityOf(beta).size).toBe(1)
  expect(layout.communities.get(alpha[0])).not.toBe(layout.communities.get(beta[0]))

  const centre = (slugs: string[]) => ({
    x: slugs.reduce((sum, slug) => sum + layout.positions.get(slug)!.x, 0) / slugs.length,
    y: slugs.reduce((sum, slug) => sum + layout.positions.get(slug)!.y, 0) / slugs.length,
    z: slugs.reduce((sum, slug) => sum + layout.positions.get(slug)!.z, 0) / slugs.length,
  })
  const spread = (slugs: string[]) => Math.max(...slugs.map((slug) => distance(layout.positions.get(slug)!, centre(slugs))))
  expect(distance(centre(alpha), centre(beta))).toBeGreaterThan(Math.max(spread(alpha), spread(beta)) * 2)
})

test("a relationship between regions makes those regions neighbours", () => {
  const layout = arrangeMemories(linkedRegionsGraph())
  const centre = (prefix: string) => {
    const slugs = Array.from({ length: 4 }, (_, index) => `${prefix}-${index + 1}`)
    return {
      x: slugs.reduce((sum, slug) => sum + layout.positions.get(slug)!.x, 0) / slugs.length,
      y: slugs.reduce((sum, slug) => sum + layout.positions.get(slug)!.y, 0) / slugs.length,
      z: slugs.reduce((sum, slug) => sum + layout.positions.get(slug)!.z, 0) / slugs.length,
    }
  }

  expect(distance(centre("beta"), centre("charlie"))).toBeLessThan(distance(centre("beta"), centre("alpha")))
})

test("standing regions leave breathing room inside the set-aside shell", () => {
  const positions = arrangeMemories(linkedRegionsGraph()).positions
  const outermost = Math.max(...[...positions.values()].map((point) => Math.hypot(point.x, point.y, point.z)))

  expect(outermost).toBeLessThan(0.95)
})

test("a long connected chain forms readable regions instead of pair-sized islands", () => {
  const communities = arrangeMemories(chainGraph()).communities
  const sizes = new Map<string, number>()
  for (const community of communities.values()) sizes.set(community, (sizes.get(community) ?? 0) + 1)

  expect(sizes.size).toBeLessThanOrEqual(4)
  expect(Math.min(...sizes.values())).toBeGreaterThanOrEqual(4)
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

test("the largest supported relationship map stays inside an interactive layout budget", () => {
  const communityCount = 500
  const nodes = Array.from({ length: communityCount * 4 }, (_, index) => ({
    ...graph.nodes[0],
    slug: `large-${Math.floor(index / 4).toString().padStart(3, "0")}-${index % 4}`,
    degree: 4,
  }))
  const edges: MemoryGraph["edges"] = []
  for (let community = 0; community < communityCount; community += 1) {
    const members = nodes.slice(community * 4, community * 4 + 4)
    edges.push(...completeEdges(members.map((node) => node.slug)))
    edges.push({
      source: members[3].slug,
      target: nodes[((community + 1) % communityCount) * 4].slug,
      kind: "mentions",
      strength: 0,
    })
  }
  const began = performance.now()
  const layout = arrangeMemories({
    nodes,
    edges,
    total_nodes: nodes.length,
    total_edges: edges.length,
    truncated: false,
    edges_truncated: false,
  })

  expect(new Set(layout.communities.values()).size).toBe(communityCount)
  expect(performance.now() - began).toBeLessThan(500)
})
