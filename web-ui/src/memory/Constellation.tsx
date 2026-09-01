import { useEffect, useMemo, useRef } from "react"

import { placeMemories } from "./layout"
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

export const NODE_LABEL_FONT_PX = 13
const CURVED_EDGE_LIMIT = 1_200

export function edgeUsesCurve(edgeCount: number): boolean {
  return edgeCount <= CURVED_EDGE_LIMIT
}

export function perspectiveForDepth(depth: number): number {
  const clipped = Math.max(-1.25, Math.min(1.25, depth))
  return 1 / (1 - clipped * 0.31)
}

export function fitConstellationScale(
  width: number,
  height: number,
  points: Array<{ x: number; y: number }>,
): number {
  const natural = Math.min(width * 0.38, height * 0.36)
  if (points.length < 2) return natural
  const xs = points.map((point) => point.x)
  const ys = points.map((point) => point.y)
  const radiusX = Math.max(0.001, (Math.max(...xs) - Math.min(...xs)) / 2)
  const radiusY = Math.max(0.001, (Math.max(...ys) - Math.min(...ys)) / 2)
  return Math.min(natural, (width * 0.44) / radiusX, (height * 0.42) / radiusY)
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
  const positions = useMemo(() => placeMemories(graph), [graph])
  const view = useRef({ yaw: -0.58, pitch: -0.16, zoom: 1 })
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
      const shape: Array<{
        node: MemoryNode
        turned: Point3
        perspective: number
        x: number
        y: number
      }> = []
      for (const node of graph.nodes) {
        const point = positions.get(node.slug)
        if (!point) continue
        const turned = rotate(point, view.current.yaw, view.current.pitch)
        const perspective = perspectiveForDepth(turned.z)
        shape.push({
          node,
          turned,
          perspective,
          x: turned.x * perspective,
          y: turned.y * perspective,
        })
      }
      const xs = shape.map((point) => point.x)
      const ys = shape.map((point) => point.y)
      const centreX = shape.length ? (Math.min(...xs) + Math.max(...xs)) / 2 : 0
      const centreY = shape.length ? (Math.min(...ys) + Math.max(...ys)) / 2 : 0
      const scale = fitConstellationScale(width, height, shape) * view.current.zoom
      const points: Projected[] = []
      for (const point of shape) {
        points.push({
          node: point.node,
          x: width / 2 + (point.x - centreX) * scale,
          y: height / 2 + (point.y - centreY) * scale,
          z: point.turned.z,
          perspective: point.perspective,
          radius: (3 + Math.min(4.6, Math.sqrt(point.node.degree + 1) * 1.15)) * point.perspective,
        })
      }
      projected.current = points
      const bySlug = new Map(points.map((point) => [point.node.slug, point]))

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

        if (isSelected || isHovered || isHit || isCited) {
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
  }, [cited, graph, highlighted, positions, selected])

  return (
    <canvas
      ref={canvasRef}
      className="memory-canvas"
      role="img"
      aria-label={`${graph.nodes.length} memories connected in a three-dimensional constellation`}
    />
  )
}
