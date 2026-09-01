import type { MemoryGraph, MemoryNode } from "./types"

export interface Point3 {
  x: number
  y: number
  z: number
}

function hash(text: string): number {
  let value = 2166136261
  for (let index = 0; index < text.length; index += 1) {
    value ^= text.charCodeAt(index)
    value = Math.imul(value, 16777619)
  }
  value ^= value >>> 16
  value = Math.imul(value, 0x85ebca6b)
  value ^= value >>> 13
  value = Math.imul(value, 0xc2b2ae35)
  value ^= value >>> 16
  return value >>> 0
}

function noise(text: string, channel: string): number {
  return hash(`${channel}\u0000${text}`) / 0xffffffff
}

function homeFor(node: MemoryNode): Point3 {
  const family = node.scope[0] ?? node.anchors[0] ?? "global"
  const side = noise(node.slug, "lobe") < 0.5 ? -1 : 1
  return {
    x: side * (0.56 + noise(node.slug, "width") * 0.16),
    y: (noise(node.slug, "height") - 0.5) * 1.24 + (noise(family, "family-height") - 0.5) * 0.14,
    z: (noise(node.slug, "depth") - 0.5) * 1.3 + (noise(family, "family-depth") - 0.5) * 0.12,
  }
}

function fitShell(point: Point3, standing: boolean, slug: string): Point3 {
  const length = Math.hypot(point.x, point.y, point.z) || 1
  const radius = standing
    ? Math.min(length, 1)
    : 1.1 + noise(slug, "outer-shadow") * 0.12
  const scale = radius / length
  return { x: point.x * scale, y: point.y * scale, z: point.z * scale }
}

/**
 * Stable relationship-aware positions. Slugs seed a broad two-lobed volume,
 * then declared connections pull their ends into the same neighbourhood.
 * Set-aside memory remains on a separate outer shell.
 */
export function placeMemories(graph: MemoryGraph): Map<string, Point3> {
  const nodes = [...graph.nodes].sort((one, other) => one.slug.localeCompare(other.slug))
  const known = new Set(nodes.map((node) => node.slug))
  const homes = new Map(nodes.map((node) => [node.slug, homeFor(node)]))
  const neighbours = new Map(nodes.map((node) => [node.slug, new Map<string, number>()]))

  for (const edge of graph.edges) {
    if (!known.has(edge.source) || !known.has(edge.target) || edge.source === edge.target) continue
    const weight = 1 + Math.min(3, Math.max(0, edge.strength)) * 0.16
    neighbours.get(edge.source)!.set(edge.target, weight)
    neighbours.get(edge.target)!.set(edge.source, weight)
  }

  let positions = new Map([...homes].map(([slug, point]) => [slug, { ...point }]))
  for (let pass = 0; pass < 7; pass += 1) {
    const next = new Map<string, Point3>()
    for (const node of nodes) {
      const point = positions.get(node.slug)!
      const home = homes.get(node.slug)!
      const adjacent = neighbours.get(node.slug)!
      if (adjacent.size === 0) {
        next.set(node.slug, point)
        continue
      }

      let weight = 0
      const centre = { x: 0, y: 0, z: 0 }
      for (const [slug, strength] of adjacent) {
        const neighbour = positions.get(slug)!
        centre.x += neighbour.x * strength
        centre.y += neighbour.y * strength
        centre.z += neighbour.z * strength
        weight += strength
      }
      centre.x /= weight
      centre.y /= weight
      centre.z /= weight

      next.set(node.slug, {
        x: point.x * 0.58 + home.x * 0.2 + centre.x * 0.22,
        y: point.y * 0.58 + home.y * 0.2 + centre.y * 0.22,
        z: point.z * 0.58 + home.z * 0.2 + centre.z * 0.22,
      })
    }
    positions = next
  }

  return new Map(nodes.map((node) => [node.slug, fitShell(positions.get(node.slug)!, node.standing, node.slug)]))
}
