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
  radius: number
}

const EDGE_DASH: Record<MemoryEdgeKind, number[]> = {
  mentions: [],
  depends_on: [],
  contradicts: [3, 5],
  supersedes: [1, 6],
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
  const view = useRef({ yaw: -0.24, pitch: 0.12, zoom: 1 })
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
      draw(performance.now())
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
        const x = width * (0.5 + side * 0.095)
        const glow = context.createRadialGradient(x, height * 0.5, 0, x, height * 0.5, Math.min(width, height) * 0.3)
        glow.addColorStop(0, alpha(side < 0 ? colors.paused : colors.ember, side < 0 ? 0.075 : 0.085))
        glow.addColorStop(1, alpha(colors.ground, 0))
        context.fillStyle = glow
        context.beginPath()
        context.ellipse(x, height * 0.5, width * 0.18, height * 0.34, side * 0.08, 0, Math.PI * 2)
        context.fill()

        // A contour, not a literal illustration: just enough anatomy for the
        // constellation to read as one mind before any node is selected.
        context.globalAlpha = 0.13
        context.strokeStyle = side < 0 ? colors.paused : colors.ember
        context.lineWidth = 0.7
        context.setLineDash([1, 8])
        context.beginPath()
        context.ellipse(x, height * 0.5, width * 0.19, height * 0.35, side * 0.08, 0, Math.PI * 2)
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
      cancelAnimationFrame(frame)
      paintNebula()
      const scale = Math.min(width, height) * 0.4 * view.current.zoom
      const focus = highlighted.size > 0
      const pulse = reduced ? 1 : 1 + Math.max(0, 1 - (now - began) / 1400) * 0.45 * Math.sin((now - began) / 85)
      const points: Projected[] = []
      for (const node of graph.nodes) {
        const point = positions.get(node.slug)
        if (!point) continue
        const turned = rotate(point, view.current.yaw, view.current.pitch)
        const depth = 1 + turned.z * 0.13
        points.push({
          node,
          x: width / 2 + turned.x * scale * depth,
          y: height / 2 + turned.y * scale * depth,
          z: turned.z,
          radius: (2.2 + Math.min(4.2, Math.sqrt(node.degree + 1))) * (0.9 + depth * 0.12),
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
        context.globalAlpha = citedPath ? 0.92 : focus ? (involved ? 0.42 : 0.035) : edge.kind === "supersedes" ? 0.08 : 0.2
        context.strokeStyle = style.color
        context.lineWidth = citedPath ? 1.8 : 0.65 + Math.min(1.2, edge.strength * 0.18)
        context.setLineDash(style.dash)
        context.beginPath()
        context.moveTo(source.x, source.y)
        context.lineTo(target.x, target.y)
        context.stroke()
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
        context.globalAlpha = point.node.standing ? (dimmed ? 0.12 : 0.78 + (point.z + 1) * 0.07) : dimmed ? 0.035 : 0.18
        context.fillStyle = isCited
          ? colors.ember
          : isHit
            ? colors.paused
            : point.node.second_look.length
              ? colors.stop
              : point.node.standing
                ? colors.pausedText
                : colors.line
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
          context.fillStyle = colors.text
          context.font = "11px 'DM Mono', ui-monospace, monospace"
          context.fillText(slug, point.x + radius + 6, point.y - radius - 2)
        }
      }
      context.globalAlpha = 1
      canvas.style.cursor = hover.current ? "pointer" : dragging ? "grabbing" : "grab"
      if (!reduced && now - began < 1400 && cited.size > 0) {
        frame = requestAnimationFrame(draw)
      }
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
      draw(performance.now())
    }
    const pointerUp = (event: PointerEvent) => {
      const here = position(event)
      dragging = false
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
      if (moved < 8) {
        const picked = nearest(projected.current, here.x, here.y)
        if (picked) onSelectRef.current(picked.node.slug)
      }
      draw(performance.now())
    }
    const pointerCancel = (event: PointerEvent) => {
      dragging = false
      if (canvas.hasPointerCapture(event.pointerId)) canvas.releasePointerCapture(event.pointerId)
      draw(performance.now())
    }
    const wheel = (event: WheelEvent) => {
      event.preventDefault()
      view.current.zoom = Math.max(0.55, Math.min(2.5, view.current.zoom * Math.exp(-event.deltaY * 0.001)))
      draw(performance.now())
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
