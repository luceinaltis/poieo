import type { MemoryGraph } from "./types"

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
  return value >>> 0
}

function unit(seed: number, shift: number): number {
  return ((seed >>> shift) & 0xff) / 255
}

/**
 * Stable two-lobed positions. Scope chooses a neighbourhood; the slug chooses
 * a point inside it. Past memory is deliberately outside both lobes.
 */
export function placeMemories(graph: MemoryGraph): Map<string, Point3> {
  const placed = new Map<string, Point3>()
  for (const node of [...graph.nodes].sort((one, other) => one.slug.localeCompare(other.slug))) {
    const seed = hash(node.slug)
    const neighbourhood = hash(node.scope[0] ?? node.anchors[0] ?? "global") % 7
    const base = (neighbourhood / 7) * Math.PI * 2
    const angle = base + (unit(seed, 8) - 0.5) * 0.9
    const side = (seed & 1) === 0 ? -1 : 1
    const depth = (unit(seed, 16) - 0.5) * 1.15
    const height = Math.sin(angle) * 0.58 + (unit(seed, 0) - 0.5) * 0.32
    const width = 0.24 + Math.abs(Math.cos(angle)) * 0.5 + unit(seed, 24) * 0.12

    // Normalize first, then choose the shell. This invariant is what makes
    // set-aside memory read as shadow rather than as one more node colour.
    const raw = { x: side * width, y: height, z: depth }
    const length = Math.hypot(raw.x, raw.y, raw.z) || 1
    const radius = node.standing
      ? 0.56 + unit(seed, 4) * 0.28
      : 1.15 + unit(seed, 4) * 0.2
    placed.set(node.slug, {
      x: (raw.x / length) * radius,
      y: (raw.y / length) * radius,
      z: (raw.z / length) * radius,
    })
  }
  return placed
}
