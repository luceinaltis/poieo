import { expect, test } from "vitest"

import {
  edgeHasArrow,
  edgeUsesCurve,
  fitConstellationScale,
  NODE_LABEL_FONT_PX,
  nodeRadiusFor,
  perspectiveForDepth,
  projectConstellationPoints,
  regionsUseHaze,
  showHighlightedLabels,
} from "./Constellation"
import { arrangeMemories } from "./layout"
import type { MemoryGraph } from "./types"

test("directional memory relationships get arrowheads", () => {
  expect(edgeHasArrow("mentions")).toBe(true)
  expect(edgeHasArrow("depends_on")).toBe(true)
  expect(edgeHasArrow("supersedes")).toBe(true)
  expect(edgeHasArrow("contradicts")).toBe(false)
})

test("large constellations trade decorative curves for responsive orbiting", () => {
  expect(edgeUsesCurve(47)).toBe(true)
  expect(edgeUsesCurve(12_000)).toBe(false)
})

test("many memory regions trade decorative haze for responsive orbiting", () => {
  expect(regionsUseHaze(24)).toBe(true)
  expect(regionsUseHaze(500)).toBe(false)
})

test("depth changes the apparent scale enough to read as three-dimensional", () => {
  expect(perspectiveForDepth(0)).toBe(1)
  expect(perspectiveForDepth(1)).toBeGreaterThan(1.3)
  expect(perspectiveForDepth(-1)).toBeLessThan(0.8)
})

test("canvas labels stay readable beside the compact interface", () => {
  expect(NODE_LABEL_FONT_PX).toBeGreaterThanOrEqual(14)
})

test("a broad search keeps the constellation labels from piling up", () => {
  expect(showHighlightedLabels(8)).toBe(true)
  expect(showHighlightedLabels(9)).toBe(false)
})

test("the initial view fits projected outer memories inside the canvas", () => {
  const width = 960
  const height = 720
  const points = [{ x: -1.8, y: -1.4 }, { x: 1.5, y: 1.7 }]
  const scale = fitConstellationScale(width, height, points)

  expect(((1.5 - -1.8) / 2) * scale).toBeLessThanOrEqual(width * 0.44)
  expect(((1.7 - -1.4) / 2) * scale).toBeLessThanOrEqual(height * 0.42)
})

test("adding an unrelated point does not move the existing screen map", () => {
  const established = [{ x: -0.42, y: 0.18, z: 0.25 }, { x: 0.31, y: -0.27, z: -0.16 }]
  const before = projectConstellationPoints(established, 393, 443)
  const after = projectConstellationPoints([...established, { x: 0.8, y: 0.7, z: 0.6 }], 393, 443)

  expect(after.slice(0, established.length)).toEqual(before)
})

test.each([
  { regionCount: 62, minimumDistance: 16 },
  { regionCount: 100, minimumDistance: 10 },
])("$regionCount independent memory regions keep readable space on a phone", ({ regionCount, minimumDistance }) => {
  const nodes = Array.from({ length: regionCount * 4 }, (_, index) => ({
    slug: `region-${Math.floor(index / 4).toString().padStart(2, "0")}-${index % 4}`,
    preview: "",
    updated_at: "2026-01-01T00:00:00Z",
    scope: [],
    anchors: [],
    standing: true,
    superseded_by: null,
    second_look: [],
    degree: 20,
  }))
  const edges: MemoryGraph["edges"] = []
  for (let group = 0; group < regionCount; group += 1) {
    const members = nodes.slice(group * 4, group * 4 + 4)
    for (let source = 0; source < members.length; source += 1) {
      for (let target = source + 1; target < members.length; target += 1) {
        edges.push({ source: members[source].slug, target: members[target].slug, kind: "mentions", strength: 0 })
      }
    }
  }
  const graph: MemoryGraph = {
    nodes,
    edges,
    total_nodes: nodes.length,
    total_edges: edges.length,
    truncated: false,
    edges_truncated: false,
  }
  const layout = arrangeMemories(graph)
  const centres = Array.from({ length: regionCount }, (_, group) => {
    const members = nodes.slice(group * 4, group * 4 + 4)
    return {
      x: members.reduce((sum, node) => sum + layout.positions.get(node.slug)!.x, 0) / members.length,
      y: members.reduce((sum, node) => sum + layout.positions.get(node.slug)!.y, 0) / members.length,
      z: members.reduce((sum, node) => sum + layout.positions.get(node.slug)!.z, 0) / members.length,
    }
  })
  const projected = projectConstellationPoints(centres, 393, 443)
  const distances = projected.flatMap((point, index) => (
    projected.slice(index + 1).map((other) => Math.hypot(point.x - other.x, point.y - other.y))
  ))
  const nodePoints = projectConstellationPoints(nodes.map((node) => layout.positions.get(node.slug)!), 393, 443)
  const clearances: number[] = []
  for (let one = 0; one < nodePoints.length; one += 1) {
    for (let other = one + 1; other < nodePoints.length; other += 1) {
      if (Math.floor(one / 4) === Math.floor(other / 4)) continue
      const oneRadius = nodeRadiusFor(nodes[one].degree, nodePoints[one].perspective, nodes.length)
      const otherRadius = nodeRadiusFor(nodes[other].degree, nodePoints[other].perspective, nodes.length)
      clearances.push(
        Math.hypot(nodePoints[one].x - nodePoints[other].x, nodePoints[one].y - nodePoints[other].y)
        - oneRadius - otherRadius,
      )
    }
  }

  expect(Math.min(...distances)).toBeGreaterThan(minimumDistance)
  expect(Math.min(...clearances)).toBeGreaterThan(0)
})

test("neighbouring multi-region families do not overlap", () => {
  const communityCount = 8
  const nodes = Array.from({ length: communityCount * 4 }, (_, index) => ({
    slug: `family-${Math.floor(index / 4).toString().padStart(2, "0")}-${index % 4}`,
    preview: "",
    updated_at: "2026-01-01T00:00:00Z",
    scope: [],
    anchors: [],
    standing: true,
    superseded_by: null,
    second_look: [],
    degree: 3,
  }))
  const edges: MemoryGraph["edges"] = []
  for (let community = 0; community < communityCount; community += 1) {
    const members = nodes.slice(community * 4, community * 4 + 4)
    for (let source = 0; source < members.length; source += 1) {
      for (let target = source + 1; target < members.length; target += 1) {
        edges.push({ source: members[source].slug, target: members[target].slug, kind: "mentions", strength: 0 })
      }
    }
    if (community % 2 === 0) {
      edges.push({ source: members[3].slug, target: nodes[(community + 1) * 4].slug, kind: "mentions", strength: 0 })
    }
  }
  const layout = arrangeMemories({
    nodes,
    edges,
    total_nodes: nodes.length,
    total_edges: edges.length,
    truncated: false,
    edges_truncated: false,
  })
  const screen = projectConstellationPoints(nodes.map((node) => layout.positions.get(node.slug)!), 393, 443)
  const regions = new Map<string, Array<{ x: number; y: number }>>()
  nodes.forEach((node, index) => {
    const community = layout.communities.get(node.slug)!
    const points = regions.get(community) ?? []
    points.push(screen[index])
    regions.set(community, points)
  })
  const bounds = [...regions.values()].map((points) => {
    const centre = {
      x: points.reduce((sum, point) => sum + point.x, 0) / points.length,
      y: points.reduce((sum, point) => sum + point.y, 0) / points.length,
    }
    return { centre, radius: Math.max(...points.map((point) => Math.hypot(point.x - centre.x, point.y - centre.y))) }
  })
  const clearances = bounds.flatMap((region, index) => bounds.slice(index + 1).map((other) => (
    Math.hypot(region.centre.x - other.centre.x, region.centre.y - other.centre.y) - region.radius - other.radius
  )))

  expect(Math.min(...clearances)).toBeGreaterThan(1)
})
