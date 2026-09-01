import type { MemoryGraph, MemoryNode } from "./types"

export interface Point3 {
  x: number
  y: number
  z: number
}

export interface MemoryArrangement {
  positions: Map<string, Point3>
  communities: Map<string, string>
  regionSlots: Map<string, number>
}

export const DEFAULT_MEMORY_YAW = -0.58
export const DEFAULT_MEMORY_PITCH = -0.16

const REGION_HASH_SLOT_COUNT = 99
const REGION_SLOT_SPACING = 0.18

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

function weightedNeighbours(nodes: MemoryNode[], graph: MemoryGraph): Map<string, Map<string, number>> {
  const known = new Set(nodes.map((node) => node.slug))
  const neighbours = new Map(nodes.map((node) => [node.slug, new Map<string, number>()]))
  const edges = [...graph.edges].sort((one, other) => (
    `${one.source}\u0000${one.target}\u0000${one.kind}`.localeCompare(`${other.source}\u0000${other.target}\u0000${other.kind}`)
  ))
  for (const edge of edges) {
    if (!known.has(edge.source) || !known.has(edge.target) || edge.source === edge.target) continue
    const weight = 1 + Math.min(3, Math.max(0, edge.strength)) * 0.16
    const source = neighbours.get(edge.source)!
    const target = neighbours.get(edge.target)!
    source.set(edge.target, (source.get(edge.target) ?? 0) + weight)
    target.set(edge.source, (target.get(edge.source) ?? 0) + weight)
  }
  return neighbours
}

/** Deterministic first-phase modularity grouping over declared relationships. */
function communitiesFor(nodes: MemoryNode[], neighbours: Map<string, Map<string, number>>): Map<string, string> {
  const known = new Map(nodes.map((node) => [node.slug, node]))
  const seen = new Set<string>()
  const components: MemoryNode[][] = []
  for (const start of nodes) {
    if (seen.has(start.slug)) continue
    const slugs: string[] = []
    const pending = [start.slug]
    seen.add(start.slug)
    while (pending.length > 0) {
      const slug = pending.pop()!
      slugs.push(slug)
      for (const neighbour of neighbours.get(slug)!.keys()) {
        if (!known.has(neighbour) || seen.has(neighbour)) continue
        seen.add(neighbour)
        pending.push(neighbour)
      }
    }
    slugs.sort()
    components.push(slugs.map((slug) => known.get(slug)!))
  }
  if (components.length > 1) {
    const combined = new Map<string, string>()
    for (const component of components) {
      for (const [slug, community] of communitiesFor(component, neighbours)) combined.set(slug, community)
    }
    return combined
  }

  const degree = new Map(nodes.map((node) => [
    node.slug,
    [...neighbours.get(node.slug)!.values()].reduce((sum, weight) => sum + weight, 0),
  ]))
  const totalWeight = [...degree.values()].reduce((sum, value) => sum + value, 0)
  const communities = new Map(nodes.map((node) => [node.slug, node.slug]))
  if (totalWeight === 0) return communities

  const totals = new Map(degree)
  const order = [...nodes].sort((one, other) => (
    degree.get(other.slug)! - degree.get(one.slug)! || one.slug.localeCompare(other.slug)
  ))
  for (let pass = 0; pass < 24; pass += 1) {
    let moved = false
    for (const node of order) {
      const slug = node.slug
      const current = communities.get(slug)!
      const nodeDegree = degree.get(slug)!
      if (nodeDegree === 0) continue
      totals.set(current, (totals.get(current) ?? 0) - nodeDegree)

      const connection = new Map<string, number>()
      for (const [neighbour, weight] of neighbours.get(slug)!) {
        const community = communities.get(neighbour)!
        connection.set(community, (connection.get(community) ?? 0) + weight)
      }
      if (!connection.has(current)) connection.set(current, 0)

      let best = current
      let bestGain = Number.NEGATIVE_INFINITY
      for (const candidate of [...connection.keys()].sort()) {
        const gain = connection.get(candidate)! - (nodeDegree * (totals.get(candidate) ?? 0)) / totalWeight
        if (gain > bestGain + 1e-10 || (Math.abs(gain - bestGain) <= 1e-10 && candidate < best)) {
          best = candidate
          bestGain = gain
        }
      }
      communities.set(slug, best)
      totals.set(best, (totals.get(best) ?? 0) + nodeDegree)
      moved ||= best !== current
    }
    if (!moved) break
  }

  const members = new Map<string, string[]>()
  for (const node of nodes) {
    const community = communities.get(node.slug)!
    const group = members.get(community) ?? []
    group.push(node.slug)
    members.set(community, group)
  }
  const canonical = new Map<string, string>()
  for (const group of members.values()) {
    group.sort()
    for (const slug of group) canonical.set(slug, group[0])
  }

  for (let pass = 0; pass < nodes.length; pass += 1) {
    const sizes = new Map<string, number>()
    for (const community of canonical.values()) sizes.set(community, (sizes.get(community) ?? 0) + 1)
    const sparse = [...sizes].filter(([, size]) => size < 4).map(([community]) => community).sort()
    let merged = false
    for (const community of sparse) {
      if ((sizes.get(community) ?? 0) >= 4) continue
      const connection = new Map<string, number>()
      const group = nodes.filter((node) => canonical.get(node.slug) === community)
      for (const node of group) {
        for (const [neighbour, weight] of neighbours.get(node.slug)!) {
          const target = canonical.get(neighbour)!
          if (target === community) continue
          connection.set(target, (connection.get(target) ?? 0) + weight)
        }
      }
      const target = [...connection].sort((one, other) => (
        other[1] - one[1]
        || (sizes.get(one[0]) ?? 0) - (sizes.get(other[0]) ?? 0)
        || one[0].localeCompare(other[0])
      ))[0]?.[0]
      if (!target) continue
      for (const node of group) canonical.set(node.slug, target)
      sizes.set(target, (sizes.get(target) ?? 0) + group.length)
      sizes.set(community, 0)
      merged = true
    }
    if (!merged) break
  }

  const finalMembers = new Map<string, string[]>()
  for (const node of nodes) {
    const community = canonical.get(node.slug)!
    const group = finalMembers.get(community) ?? []
    group.push(node.slug)
    finalMembers.set(community, group)
  }
  const final = new Map<string, string>()
  for (const group of finalMembers.values()) {
    group.sort()
    for (const slug of group) final.set(slug, group[0])
  }
  return final
}

interface RegionCell {
  q: number
  r: number
  x: number
  y: number
}

const REGION_GRID_RADIUS = 32
const REGION_GRID: RegionCell[] = []
for (let q = -REGION_GRID_RADIUS; q <= REGION_GRID_RADIUS; q += 1) {
  const firstRow = Math.max(-REGION_GRID_RADIUS, -q - REGION_GRID_RADIUS)
  const lastRow = Math.min(REGION_GRID_RADIUS, -q + REGION_GRID_RADIUS)
  for (let r = firstRow; r <= lastRow; r += 1) {
    REGION_GRID.push({
      q,
      r,
      x: (q + r / 2) * REGION_SLOT_SPACING,
      y: r * REGION_SLOT_SPACING * Math.sqrt(3) / 2,
    })
  }
}
REGION_GRID.sort((one, other) => (
  Math.max(Math.abs(one.q), Math.abs(one.r), Math.abs(-one.q - one.r))
  - Math.max(Math.abs(other.q), Math.abs(other.r), Math.abs(-other.q - other.r))
  || Math.atan2(one.y, one.x) - Math.atan2(other.y, other.x)
))
const REGION_SLOT_BY_CELL = new Map(REGION_GRID.map((cell, slot) => [`${cell.q},${cell.r}`, slot]))

function viewForRegionSlot(slot: number): Point3 {
  const layer = Math.floor(slot / REGION_GRID.length)
  const index = slot % REGION_GRID.length
  const cell = REGION_GRID[index]
  const staggerDirection = layer % 2 === 0 ? -1 : 1
  const staggerX = layer === 0 ? 0 : staggerDirection * REGION_SLOT_SPACING / 2
  const staggerY = layer === 0 ? 0 : staggerDirection * REGION_SLOT_SPACING * Math.sqrt(3) / 6
  return {
    x: cell.x + staggerX,
    y: cell.y + staggerY,
    z: (noise(String(slot), "region-slot-depth") - 0.5) * 0.16 + layer * 0.08,
  }
}

function regionSlotsFor(
  componentMembers: Map<string, string[]>,
  linkedGroups: Map<string, Set<string>>,
  communitySizes: Map<string, number>,
  previous: Map<string, number>,
): Map<string, number> {
  const slots = new Map<string, number>()
  const used = new Set([...previous.values()].filter((slot) => slot >= 0))
  for (const members of componentMembers.values()) {
    for (const community of members) {
      const slot = previous.get(community)
      if (slot !== undefined && slot >= 0) slots.set(community, slot)
    }
  }

  const firstFree = (preferred: number) => {
    for (let offset = 0; offset < REGION_HASH_SLOT_COUNT; offset += 1) {
      const slot = (preferred + offset) % REGION_HASH_SLOT_COUNT
      if (!used.has(slot)) return slot
    }
    let slot = REGION_HASH_SLOT_COUNT
    while (used.has(slot)) slot += 1
    return slot
  }
  const nearestFree = (targets: number[]) => {
    const candidates = new Set<number>()
    for (const target of targets) {
      const origin = REGION_GRID[target]
      if (!origin) continue
      for (const offset of REGION_GRID) {
        const slot = REGION_SLOT_BY_CELL.get(`${origin.q + offset.q},${origin.r + offset.r}`)
        if (slot === undefined || used.has(slot)) continue
        candidates.add(slot)
        break
      }
    }
    if (candidates.size === 0) return firstFree(0)
    let best = [...candidates][0]
    let bestScore = Number.POSITIVE_INFINITY
    for (const slot of candidates) {
      const point = viewForRegionSlot(slot)
      const score = targets.reduce((sum, target) => {
        const neighbour = viewForRegionSlot(target)
        return sum + Math.hypot(point.x - neighbour.x, point.y - neighbour.y)
      }, 0) / targets.length
      if (score < bestScore || (score === bestScore && slot < best)) {
        best = slot
        bestScore = score
      }
    }
    return best
  }

  const componentMass = new Map([...componentMembers.values()].map((members) => [
    members[0],
    members.reduce((sum, community) => sum + communitySizes.get(community)!, 0),
  ]))
  const orderedComponents = [...componentMembers.values()].sort((one, other) => {
    const oneRemembered = one.some((community) => slots.has(community))
    const otherRemembered = other.some((community) => slots.has(community))
    return Number(otherRemembered) - Number(oneRemembered)
      || componentMass.get(other[0])! - componentMass.get(one[0])!
      || one[0].localeCompare(other[0])
  })
  let centreClaimed = used.has(0)
  for (const members of orderedComponents) {
    const unassigned = new Set(members.filter((community) => !slots.has(community)))
    const queued = new Set<string>()
    const queue: string[] = []
    let cursor = 0
    const enqueueNeighbours = (community: string) => {
      for (const neighbour of [...linkedGroups.get(community)!].sort()) {
        if (!unassigned.has(neighbour) || queued.has(neighbour)) continue
        queued.add(neighbour)
        queue.push(neighbour)
      }
    }
    for (const community of members) {
      if (slots.has(community)) enqueueNeighbours(community)
    }

    while (unassigned.size > 0) {
      if (cursor >= queue.length) {
        const root = [...unassigned].sort((one, other) => (
          linkedGroups.get(other)!.size - linkedGroups.get(one)!.size
          || communitySizes.get(other)! - communitySizes.get(one)!
          || one.localeCompare(other)
        ))[0]
        queued.add(root)
        queue.push(root)
      }
      const community = queue[cursor]
      cursor += 1
      if (!unassigned.delete(community)) continue
      let targets = [...linkedGroups.get(community)!]
        .map((neighbour) => slots.get(neighbour))
        .filter((slot): slot is number => slot !== undefined)
      if (targets.length === 0) {
        targets = members.map((member) => slots.get(member)).filter((slot): slot is number => slot !== undefined)
      }
      const slot = targets.length > 0
        ? nearestFree(targets)
        : firstFree(centreClaimed ? hash(`region-slot\u0000${community}`) % REGION_HASH_SLOT_COUNT : 0)
      slots.set(community, slot)
      used.add(slot)
      if (slot === 0) centreClaimed = true
      enqueueNeighbours(community)
    }
  }
  return slots
}

/** A spaced grid in the constellation's default view, then rotated back into world space. */
function pointForRegionSlot(slot: number): Point3 {
  const view = viewForRegionSlot(slot)

  const cy = Math.cos(DEFAULT_MEMORY_YAW)
  const sy = Math.sin(DEFAULT_MEMORY_YAW)
  const cp = Math.cos(DEFAULT_MEMORY_PITCH)
  const sp = Math.sin(DEFAULT_MEMORY_PITCH)
  const worldY = view.y * cp + view.z * sp
  const yawDepth = -view.y * sp + view.z * cp
  return {
    x: view.x * cy + yawDepth * sy,
    y: worldY,
    z: -view.x * sy + yawDepth * cy,
  }
}

function communityCentres(
  communities: Map<string, string>,
  neighbours: Map<string, Map<string, number>>,
  previousSlots: Map<string, number>,
): { positions: Map<string, Point3>; regionSlots: Map<string, number> } {
  const groups = [...new Set(communities.values())].sort()
  const communitySizes = new Map(groups.map((community) => [community, 0]))
  for (const community of communities.values()) communitySizes.set(community, communitySizes.get(community)! + 1)
  const linkedGroups = new Map(groups.map((community) => [community, new Set<string>()]))
  for (const [slug, adjacent] of neighbours) {
    const source = communities.get(slug)!
    for (const neighbour of adjacent.keys()) {
      const target = communities.get(neighbour)!
      if (source === target) continue
      linkedGroups.get(source)!.add(target)
      linkedGroups.get(target)!.add(source)
    }
  }

  const componentMembers = new Map<string, string[]>()
  const assigned = new Set<string>()
  for (const start of groups) {
    if (assigned.has(start)) continue
    const members: string[] = []
    const pending = [start]
    const seen = new Set([start])
    while (pending.length > 0) {
      const community = pending.pop()!
      members.push(community)
      for (const neighbour of [...linkedGroups.get(community)!].sort().reverse()) {
        if (seen.has(neighbour)) continue
        seen.add(neighbour)
        pending.push(neighbour)
      }
    }
    members.sort()
    const component = members[0]
    componentMembers.set(component, members)
    for (const community of members) assigned.add(community)
  }

  const regionSlots = regionSlotsFor(componentMembers, linkedGroups, communitySizes, previousSlots)
  const positions = new Map(groups.map((community) => [community, pointForRegionSlot(regionSlots.get(community)!)]))
  return { positions, regionSlots }
}

function homeFor(node: MemoryNode, centre: Point3, communitySize: number): Point3 {
  const spread = Math.min(0.26, 0.04 + Math.max(0, communitySize - 1) * 0.012)
  const vertical = noise(node.slug, "local-height") * 2 - 1
  const ring = Math.sqrt(1 - vertical * vertical)
  const angle = noise(node.slug, "local-angle") * Math.PI * 2
  const radius = Math.cbrt(noise(node.slug, "local-radius")) * spread
  return {
    x: centre.x + Math.cos(angle) * ring * radius,
    y: centre.y + vertical * radius,
    z: centre.z + Math.sin(angle) * ring * radius,
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

/** Stable relationship communities, separated before their members settle. */
export function arrangeMemories(graph: MemoryGraph, previousSlots = new Map<string, number>()): MemoryArrangement {
  const nodes = [...graph.nodes].sort((one, other) => one.slug.localeCompare(other.slug))
  if (nodes.length === 0) return { positions: new Map(), communities: new Map(), regionSlots: new Map() }
  const neighbours = weightedNeighbours(nodes, graph)
  const communities = communitiesFor(nodes, neighbours)
  const centreLayout = communityCentres(communities, neighbours, previousSlots)
  const centres = centreLayout.positions
  const sizes = new Map<string, number>()
  for (const community of communities.values()) {
    sizes.set(community, (sizes.get(community) ?? 0) + 1)
  }
  const homes = new Map(nodes.map((node) => {
    const community = communities.get(node.slug)!
    return [node.slug, homeFor(node, centres.get(community)!, sizes.get(community)!)]
  }))

  let positions = new Map([...homes].map(([slug, point]) => [slug, { ...point }]))
  for (let pass = 0; pass < 9; pass += 1) {
    const next = new Map<string, Point3>()
    for (const node of nodes) {
      const point = positions.get(node.slug)!
      const home = homes.get(node.slug)!
      const community = communities.get(node.slug)!
      const adjacent = [...neighbours.get(node.slug)!].filter(([slug]) => communities.get(slug) === community)
      if (adjacent.length === 0) {
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
        x: point.x * 0.48 + home.x * 0.22 + centre.x * 0.3,
        y: point.y * 0.48 + home.y * 0.22 + centre.y * 0.3,
        z: point.z * 0.48 + home.z * 0.22 + centre.z * 0.3,
      })
    }
    positions = next
  }

  const members = new Map<string, MemoryNode[]>()
  for (const node of nodes) {
    const community = communities.get(node.slug)!
    const group = members.get(community) ?? []
    group.push(node)
    members.set(community, group)
  }
  for (const [community, group] of members) {
    const mean = group.reduce((point, node) => {
      const placed = positions.get(node.slug)!
      point.x += placed.x / group.length
      point.y += placed.y / group.length
      point.z += placed.z / group.length
      return point
    }, { x: 0, y: 0, z: 0 })
    const target = centres.get(community)!
    for (const node of group) {
      const point = positions.get(node.slug)!
      positions.set(node.slug, {
        x: point.x + target.x - mean.x,
        y: point.y + target.y - mean.y,
        z: point.z + target.z - mean.z,
      })
    }
  }

  return {
    positions: new Map(nodes.map((node) => [node.slug, fitShell(positions.get(node.slug)!, node.standing, node.slug)])),
    communities,
    regionSlots: centreLayout.regionSlots,
  }
}

export function placeMemories(graph: MemoryGraph): Map<string, Point3> {
  return arrangeMemories(graph).positions
}
