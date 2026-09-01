import { useEffect, useMemo, useRef } from "react"

import { arrangeMemories, DEFAULT_MEMORY_PITCH, DEFAULT_MEMORY_YAW } from "./layout"
import type { Point3 } from "./layout"
import type { MemoryEdgeKind, MemoryGraph, MemoryNode } from "./types"

interface Props {
  graph: MemoryGraph
  highlighted: Set<string>
  cited: Set<string>
  selected: string | null
  onSelect(slug: string): void
}

interface Projected {
  node: MemoryNode
  x: number
  y: number
  z: number
  perspective: number
  radius: number
}

const EDGE_DASH: Record<MemoryEdgeKind, number[]> = {
  mentions: [],
  depends_on: [],
  contradicts: [3, 5],
  supersedes: [1, 6],
}

export const NODE_LABEL_FONT_PX = 14
const CURVED_EDGE_LIMIT = 1_200
const HIGHLIGHT_LABEL_LIMIT = 8
const REGION_HAZE_LIMIT = 80

export function edgeUsesCurve(edgeCount: number): boolean {
  return edgeCount <= CURVED_EDGE_LIMIT
}

export function showHighlightedLabels(highlightedCount: number): boolean {
  return highlightedCount <= HIGHLIGHT_LABEL_LIMIT
}

export function regionsUseHaze(regionCount: number): boolean {
  return regionCount <= REGION_HAZE_LIMIT
}

export function nodeRadiusFor(degree: number, perspective: number, nodeCount: number): number {
  const density = Math.max(0.56, 1 - Math.max(0, nodeCount - 160) / 600)
  return (3 + Math.min(4.6, Math.sqrt(degree + 1) * 1.15)) * perspective * density
}

export function perspectiveForDepth(depth: number): number {
  const clipped = Math.max(-1.25, Math.min(1.25, depth))
  return 1 / (1 - clipped * 0.31)
}

export function fitConstellationScale(
  width: number,
  height: number,
  _points: Array<{ x: number; y: number }>,
): number {
  return Math.min(width * 0.32, height * 0.27)
}

export function edgeHasArrow(kind: MemoryEdgeKind): boolean {
  return kind !== "contradicts"
}

function palette() {
  const style = getComputedStyle(document.documentElement)
  const value = (name: string) => style.getPropertyValue(`--${name}`).trim()
  return {
    ground: value("ground"),
    line: value("line"),
    text: value("text"),
    dim: value("dim"),
    ember: value("ember"),
    stop: value("stop"),
    paused: value("paused"),
    pausedText: value("paused-text"),
  }
}

function alpha(color: string, opacity: number): string {
  const short = /^#([\da-f])([\da-f])([\da-f])$/i.exec(color)
  const full = /^#([\da-f]{2})([\da-f]{2})([\da-f]{2})$/i.exec(color)
  const parts = short
    ? short.slice(1).map((part) => Number.parseInt(part + part, 16))
    : full?.slice(1).map((part) => Number.parseInt(part, 16))
  return parts ? `rgba(${parts.join(", ")}, ${opacity})` : color
}

function rotate(point: Point3, yaw: number, pitch: number): Point3 {
  const cy = Math.cos(yaw)
  const sy = Math.sin(yaw)
  const cp = Math.cos(pitch)
  const sp = Math.sin(pitch)
  const x = point.x * cy - point.z * sy
  const z = point.x * sy + point.z * cy
  return { x, y: point.y * cp - z * sp, z: point.y * sp + z * cp }
}

export function projectConstellationPoints(
  points: Point3[],
  width: number,
  height: number,
  yaw = DEFAULT_MEMORY_YAW,
  pitch = DEFAULT_MEMORY_PITCH,
  zoom = 1,
): Array<{ x: number; y: number; z: number; perspective: number }> {
  const scale = fitConstellationScale(width, height, []) * zoom
  return points.map((point) => {
    const turned = rotate(point, yaw, pitch)
    const perspective = perspectiveForDepth(turned.z)
    return {
      x: width / 2 + turned.x * perspective * scale,
      y: height / 2 + turned.y * perspective * scale,
      z: turned.z,
      perspective,
    }
  })
}

function nearest(nodes: Projected[], x: number, y: number): Projected | null {
  let found: Projected | null = null
  let distance = Number.POSITIVE_INFINITY
  for (const node of nodes) {
    const away = Math.hypot(node.x - x, node.y - y)
    if (away <= Math.max(22, node.radius + 5) && away < distance) {
      found = node
      distance = away
    }
  }
  return found
}

export function Constellation({ graph, highlighted, cited, selected, onSelect }: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const slotCache = useRef(new Map<string, number>())
  const arrangement = useMemo(() => {
    const next = arrangeMemories(graph, slotCache.current)
    for (const [region, slot] of next.regionSlots) slotCache.current.set(region, slot)
    return next
  }, [graph])
  const { communities, positions } = arrangement
  const view = useRef({ yaw: DEFAULT_MEMORY_YAW, pitch: DEFAULT_MEMORY_PITCH, zoom: 1 })
  const projected = useRef<Projected[]>([])
  const hover = useRef<string | null>(null)
  const onSelectRef = useRef(onSelect)
  onSelectRef.current = onSelect

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const context = canvas.getContext("2d")
    if (!context) return
    const colors = palette()
    const edgeStyle: Record<MemoryEdgeKind, { color: string; dash: number[] }> = {
      mentions: { color: colors.paused, dash: EDGE_DASH.mentions },
      depends_on: { color: colors.ember, dash: EDGE_DASH.depends_on },
      contradicts: { color: colors.stop, dash: EDGE_DASH.contradicts },
      supersedes: { color: colors.line, dash: EDGE_DASH.supersedes },
    }
    const curvedEdges = edgeUsesCurve(graph.edges.length)
    const reduced = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false
    const began = performance.now()
    let frame = 0
    let width = 0
    let height = 0
    let dragging = false
    let moved = 0
    let lastX = 0
    let lastY = 0
    hover.current = null

    const resize = () => {
      const rect = canvas.getBoundingClientRect()
      width = Math.max(1, rect.width)
      height = Math.max(1, rect.height)
      const ratio = Math.min(2, window.devicePixelRatio || 1)
      canvas.width = Math.round(width * ratio)
      canvas.height = Math.round(height * ratio)
      context.setTransform(ratio, 0, 0, ratio, 0, 0)
      scheduleDraw()
    }

    const paintNebula = () => {
      context.clearRect(0, 0, width, height)
      const haze = context.createRadialGradient(
        width * 0.5,
        height * 0.5,
        0,
        width * 0.5,
        height * 0.5,
        Math.max(width, height) * 0.68,
      )
      haze.addColorStop(0, alpha(colors.paused, 0.16))
      haze.addColorStop(0.45, alpha(colors.ember, 0.07))
      haze.addColorStop(1, alpha(colors.ground, 0))
      context.fillStyle = haze
      context.fillRect(0, 0, width, height)

      for (let index = 0; index < 90; index += 1) {
        const seed = Math.imul(index + 17, 2654435761) >>> 0
        const x = (seed % 1000) / 1000
        const y = ((seed >>> 10) % 1000) / 1000
        const opacity = 0.08 + ((seed >>> 20) % 10) / 90
        context.fillStyle = alpha(colors.text, opacity)
        context.fillRect(x * width, y * height, index % 11 === 0 ? 1.4 : 0.7, index % 11 === 0 ? 1.4 : 0.7)
      }

      for (const side of [-1, 1]) {
        const x = width * (0.5 + side * 0.14)
        const glow = context.createRadialGradient(x, height * 0.5, 0, x, height * 0.5, Math.min(width, height) * 0.3)
        glow.addColorStop(0, alpha(side < 0 ? colors.paused : colors.ember, side < 0 ? 0.075 : 0.085))
        glow.addColorStop(1, alpha(colors.ground, 0))
        context.fillStyle = glow
        context.beginPath()
        context.ellipse(x, height * 0.5, width * 0.235, height * 0.32, side * 0.08, 0, Math.PI * 2)
        context.fill()

        // A contour, not a literal illustration: just enough anatomy for the
        // constellation to read as one mind before any node is selected.
        context.globalAlpha = 0.13
        context.strokeStyle = side < 0 ? colors.paused : colors.ember
        context.lineWidth = 0.7
        context.setLineDash([1, 8])
        context.beginPath()
        context.ellipse(x, height * 0.5, width * 0.245, height * 0.33, side * 0.08, 0, Math.PI * 2)
        context.stroke()
      }
      context.setLineDash([])
      context.globalAlpha = 0.12
      context.strokeStyle = colors.ember
      context.lineWidth = 1.2
      context.beginPath()
      context.moveTo(width * 0.43, height * 0.5)
      context.bezierCurveTo(width * 0.47, height * 0.43, width * 0.53, height * 0.57, width * 0.57, height * 0.5)
      context.stroke()
      context.globalAlpha = 1
    }

    const draw = (now: number) => {
      paintNebula()
      const focus = highlighted.size > 0
      const pulse = reduced ? 1 : 1 + Math.max(0, 1 - (now - began) / 1400) * 0.45 * Math.sin((now - began) / 85)
      const shape: Array<{ node: MemoryNode; point: Point3 }> = []
      for (const node of graph.nodes) {
        const point = positions.get(node.slug)
        if (!point) continue
        shape.push({ node, point })
      }
      const screen = projectConstellationPoints(
        shape.map((entry) => entry.point),
        width,
        height,
        view.current.yaw,
        view.current.pitch,
        view.current.zoom,
      )
      const points: Projected[] = shape.map((entry, index) => ({
        node: entry.node,
        ...screen[index],
        radius: nodeRadiusFor(entry.node.degree, screen[index].perspective, graph.nodes.length),
      }))
      projected.current = points
      const bySlug = new Map(points.map((point) => [point.node.slug, point]))

      const regions = new Map<string, Projected[]>()
      for (const point of points) {
        if (!point.node.standing) continue
        const community = communities.get(point.node.slug)
        if (!community) continue
        const region = regions.get(community) ?? []
        region.push(point)
        regions.set(community, region)
      }
      for (const region of regionsUseHaze(regions.size) ? regions.values() : []) {
        if (region.length < 2) continue
        const x = region.reduce((sum, point) => sum + point.x, 0) / region.length
        const y = region.reduce((sum, point) => sum + point.y, 0) / region.length
        const radius = Math.min(150, Math.max(42, ...region.map((point) => Math.hypot(point.x - x, point.y - y) + 28)))
        const glow = context.createRadialGradient(x, y, 0, x, y, radius)
        glow.addColorStop(0, alpha(colors.paused, 0.115))
        glow.addColorStop(0.58, alpha(colors.paused, 0.05))
        glow.addColorStop(1, alpha(colors.ground, 0))
        context.fillStyle = glow
        context.beginPath()
        context.arc(x, y, radius, 0, Math.PI * 2)
        context.fill()
      }

      context.lineCap = "round"
      for (const edge of graph.edges) {
        const source = bySlug.get(edge.source)
        const target = bySlug.get(edge.target)
        if (!source || !target) continue
        const style = edgeStyle[edge.kind]
        const involved = highlighted.has(edge.source) || highlighted.has(edge.target)
        const citedPath = cited.has(edge.source) && cited.has(edge.target)
        const edgePerspective = perspectiveForDepth((source.z + target.z) / 2)
        const restingAlpha = edge.kind === "supersedes" ? 0.08 : 0.12 + Math.max(0, edgePerspective - 0.7) * 0.18
        context.globalAlpha = citedPath ? 0.92 : focus ? (involved ? 0.42 : 0.035) : restingAlpha
        context.strokeStyle = style.color
        context.lineWidth = citedPath ? 1.8 : (0.65 + Math.min(1.2, edge.strength * 0.18)) * Math.sqrt(edgePerspective)
        context.setLineDash(style.dash)
        const dx = target.x - source.x
        const dy = target.y - source.y
        const distance = Math.hypot(dx, dy) || 1
        let controlX = source.x
        let controlY = source.y
        context.beginPath()
        context.moveTo(source.x, source.y)
        if (curvedEdges) {
          const direction = edge.source.localeCompare(edge.target) < 0 ? 1 : -1
          const bend = Math.min(22, distance * 0.065) * (0.75 + Math.abs(source.z - target.z) * 0.35) * direction
          controlX = (source.x + target.x) / 2 - (dy / distance) * bend
          controlY = (source.y + target.y) / 2 + (dx / distance) * bend
          context.quadraticCurveTo(controlX, controlY, target.x, target.y)
        } else {
          context.lineTo(target.x, target.y)
        }
        context.stroke()
        if (edgeHasArrow(edge.kind)) {
          const angle = Math.atan2(target.y - controlY, target.x - controlX)
          const inset = target.radius + 2
          const tipX = target.x - Math.cos(angle) * inset
          const tipY = target.y - Math.sin(angle) * inset
          const length = 5 * Math.sqrt(edgePerspective)
          const spread = 0.55
          context.fillStyle = style.color
          context.beginPath()
          context.moveTo(tipX, tipY)
          context.lineTo(
            tipX - Math.cos(angle - spread) * length,
            tipY - Math.sin(angle - spread) * length,
          )
          context.lineTo(
            tipX - Math.cos(angle + spread) * length,
            tipY - Math.sin(angle + spread) * length,
          )
          context.closePath()
          context.fill()
        }
      }
      context.setLineDash([])

      points.sort((one, other) => one.z - other.z)
      for (const point of points) {
        const slug = point.node.slug
        const isSelected = selected === slug
        const isHovered = hover.current === slug
        const isCited = cited.has(slug)
        const isHit = highlighted.has(slug)
        const dimmed = focus && !isHit && !isCited
        const radius = point.radius * (isCited ? pulse : 1)
        context.globalAlpha = point.node.standing
          ? dimmed
            ? 0.1
            : Math.min(0.96, 0.54 + point.perspective * 0.3)
          : dimmed
            ? 0.025
            : Math.min(0.22, 0.06 + point.perspective * 0.1)
        const fillColor = isCited
          ? colors.ember
          : isHit
            ? colors.paused
            : point.node.second_look.length
              ? colors.stop
              : point.node.standing
                ? colors.pausedText
                : colors.line
        context.fillStyle = fillColor
        if (isSelected || isCited) {
          context.shadowColor = isCited ? colors.ember : colors.paused
          context.shadowBlur = isCited ? 18 : 12
        }
        context.beginPath()
        context.arc(point.x, point.y, radius, 0, Math.PI * 2)
        context.fill()
        context.shadowBlur = 0

        if (isSelected) {
          context.globalAlpha = 0.9
          context.strokeStyle = colors.text
          context.lineWidth = 1
          context.beginPath()
          context.arc(point.x, point.y, radius + 5, 0, Math.PI * 2)
          context.stroke()
        }

        if (isSelected || isHovered || (isHit && showHighlightedLabels(highlighted.size)) || isCited) {
          context.globalAlpha = dimmed ? 0.3 : 0.88
          const labelX = point.x + radius + 7
          const labelY = point.y - radius - 3
          context.fillStyle = colors.text
          context.font = `500 ${NODE_LABEL_FONT_PX}px 'DM Mono', ui-monospace, monospace`
          context.lineJoin = "round"
          context.lineWidth = 3
          context.strokeStyle = alpha(colors.ground, 0.86)
          context.strokeText(slug, labelX, labelY)
          context.fillText(slug, labelX, labelY)
        }
      }
      context.globalAlpha = 1
      canvas.style.cursor = hover.current ? "pointer" : dragging ? "grabbing" : "grab"
      if (!reduced && now - began < 1400 && cited.size > 0) {
        scheduleDraw()
      }
    }

    const scheduleDraw = () => {
      if (frame !== 0) return
      frame = requestAnimationFrame((now) => {
        frame = 0
        draw(now)
      })
    }

    const position = (event: PointerEvent | WheelEvent) => {
      const rect = canvas.getBoundingClientRect()
      return { x: event.clientX - rect.left, y: event.clientY - rect.top }
    }
    const pointerDown = (event: PointerEvent) => {
      dragging = true
      moved = 0
      lastX = event.clientX
      lastY = event.clientY
      canvas.setPointerCapture(event.pointerId)
    }
    const pointerMove = (event: PointerEvent) => {
      const here = position(event)
      if (dragging) {
        const dx = event.clientX - lastX
        const dy = event.clientY - lastY
        moved += Math.abs(dx) + Math.abs(dy)
        view.current.yaw += dx * 0.006
        view.current.pitch = Math.max(-1.15, Math.min(1.15, view.current.pitch + dy * 0.005))
        lastX = event.clientX
        lastY = event.clientY
      } else {
        hover.current = nearest(projected.current, here.x, here.y)?.node.slug ?? null
      }
      scheduleDraw()
    }
    const pointerUp = (event: PointerEvent) => {
      const here = position(event)
      dragging = false
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
      if (moved < 8) {
        const picked = nearest(projected.current, here.x, here.y)
        if (picked) onSelectRef.current(picked.node.slug)
      }
      scheduleDraw()
    }
    const pointerCancel = (event: PointerEvent) => {
      dragging = false
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
      scheduleDraw()
    }
    const wheel = (event: WheelEvent) => {
      event.preventDefault()
      view.current.zoom = Math.max(0.55, Math.min(2.5, view.current.zoom * Math.exp(-event.deltaY * 0.001)))
      scheduleDraw()
    }

    canvas.addEventListener("pointerdown", pointerDown)
    canvas.addEventListener("pointermove", pointerMove)
    canvas.addEventListener("pointerup", pointerUp)
    canvas.addEventListener("pointercancel", pointerCancel)
    canvas.addEventListener("wheel", wheel, { passive: false })
    const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(resize)
    observer?.observe(canvas)
    window.addEventListener("resize", resize)
    resize()
    return () => {
      cancelAnimationFrame(frame)
      observer?.disconnect()
      window.removeEventListener("resize", resize)
      canvas.removeEventListener("pointerdown", pointerDown)
      canvas.removeEventListener("pointermove", pointerMove)
      canvas.removeEventListener("pointerup", pointerUp)
      canvas.removeEventListener("pointercancel", pointerCancel)
      canvas.removeEventListener("wheel", wheel)
    }
  }, [cited, communities, graph, highlighted, positions, selected])

  return (
    <canvas
      ref={canvasRef}
      className="memory-canvas"
      role="img"
      aria-label={`${graph.nodes.length} memories grouped by their relationships in a three-dimensional constellation`}
    />
  )
}
