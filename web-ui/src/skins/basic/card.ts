/** A vertical graph at card reading size. Exact conditions stay on their own wires. */
import dagre from "@dagrejs/dagre"

import type { TaskState } from "../../state/stage"
import { walk } from "../wiring"
import { edgePath } from "./graph"
import { stepName, waysOut } from "./steps"

const NS = "http://www.w3.org/2000/svg"

function html(tag: string, cls: string, text = "") {
  const el = document.createElement(tag)
  el.className = cls
  el.textContent = text
  return el
}

function svg(tag: string, attrs: Record<string, string>) {
  const el = document.createElementNS(NS, tag)
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value)
  return el
}

export function drawCardSteps(container: HTMLElement, task: TaskState) {
  const shape = task.shape
  const nodes = new Map(shape.nodes.map(node => [node.id, node]))
  const names = new Map<string, number>()
  for (const node of shape.nodes) names.set(stepName(node), (names.get(stepName(node)) ?? 0) + 1)
  const nameOf = (id: string): string => {
    const node = nodes.get(id)!
    const name = stepName(node)
    return names.get(name)! > 1 ? `${name} (${id})` : name
  }
  const differ = new Set(shape.nodes.map(node => node.model).filter(Boolean)).size > 1
  const graph = new dagre.graphlib.Graph({ multigraph: true })
    .setGraph({ rankdir: "TB", nodesep: 18, ranksep: 26, edgesep: 4, marginx: 10, marginy: 12 })
    .setDefaultEdgeLabel(() => ({}))
  const scene = html("div", "basic-step-scene")
  container.replaceChildren(scene)
  const drawn = new Map<string, HTMLElement>()
  // Authored IDs never share the namespace of diagram-only starts and ends.
  const keyOf = (id: string) => `node:${id}`
  const add = (id: string, el: HTMLElement, width: number, height: number) => {
    el.style.width = `${width}px`
    scene.append(el)
    graph.setNode(id, { width, height: el.offsetHeight || height })
    drawn.set(id, el)
  }
  for (const id of walk(shape)) {
    const node = nodes.get(id)!
    const step = html("section", "basic-node")
    step.dataset.node = id
    step.dataset.type = node.type
    step.setAttribute("aria-label", nameOf(id))
    step.title = `${stepName(node)} (${id})`
    const head = html("div", "basic-node-head")
    head.append(html("span", "basic-node-glyph"), html("span", "basic-node-name", nameOf(id)))
    step.append(head)
    if (differ && node.model) step.append(html("span", "basic-node-model", node.model))
    if (node.tools.length) {
      const hands = html("span", "basic-node-hands", "edits files")
      hands.title = node.tools.join(", ")
      step.append(hands)
    }
    add(keyOf(id), step, 144, 42)
  }
  const edges: { from: string; to: string; description: string; label?: HTMLElement; source?: string }[] = []
  const connect = (from: string, to: string, description: string, label?: HTMLElement, source?: string) => {
    if (label) scene.append(label)
    const size = label ? { width: 100, height: label.offsetHeight || 32, labelpos: "c" } : {}
    graph.setEdge(from, to, size, String(edges.length))
    edges.push({ from, to, description, label, source })
  }
  if (nodes.has(shape.entry)) {
    add("start", html("span", "basic-step-start", "Start"), 60, 24)
    connect("start", keyOf(shape.entry), `Start → ${nameOf(shape.entry)}`)
  }
  for (const id of walk(shape)) {
    const ways = waysOut(nodes.get(id)!)
    if (!ways.length) ways.push({ to: null, label: "", fallback: false })
    for (const [index, way] of ways.entries()) {
      if (way.to !== null && !nodes.has(way.to)) continue
      const to = way.to === null ? `end:${id}:${index}` : keyOf(way.to)
      if (way.to === null) add(to, html("span", "basic-step-end", "End run"), 68, 26)
      const condition = way.fallback ? "Otherwise" : way.label ? `If ${way.label}` : ""
      const label = condition ? html("span", "basic-step-condition", condition) : undefined
      const description = `${nameOf(id)} → ${way.to === null ? "End run" : nameOf(way.to)}${condition ? `: ${condition}` : ""}`
      connect(keyOf(id), to, description, label, id)
    }
  }
  dagre.layout(graph)
  const room = (container.parentElement?.clientWidth || 310) - 2
  // Conditions can use more lines before the graph needs to use smaller type.
  if ((graph.graph().width ?? 0) > room) {
    edges.forEach((edge, index) => {
      if (!edge.label) return
      edge.label.style.width = "66px"
      graph.setEdge(edge.from, edge.to, { width: 66, height: edge.label.offsetHeight || 48, labelpos: "c" }, String(index))
    })
    dagre.layout(graph)
  }
  const wires = svg("svg", { class: "basic-step-wires", width: String(graph.graph().width), height: String(graph.graph().height) })
  for (const [index, edge] of edges.entries()) {
    const points = graph.edge(edge.from, edge.to, String(index)).points
    const end = points[points.length - 1], before = points[points.length - 2]
    const angle = Math.atan2(end.y - before.y, end.x - before.x) * 180 / Math.PI
    const group = svg("g", { class: "basic-step-wire", "data-conditional": String(Boolean(edge.label)), "data-return": String(graph.node(edge.to).y <= graph.node(edge.from).y) })
    const path = svg("path", { class: "basic-step-edge", d: edgePath(points), role: "img", "aria-label": edge.description })
    if (edge.source) path.setAttribute("data-from", edge.source)
    group.append(path, svg("path", { class: "basic-step-arrow", d: "M0 0 L-7 3.5 L-7 -3.5 Z", transform: `translate(${end.x} ${end.y}) rotate(${angle})` }))
    group.append(svg("circle", { class: "basic-step-port", cx: String(points[0].x), cy: String(points[0].y), r: "2.5" }))
    wires.append(group)
    if (edge.label) {
      const at = graph.edge(edge.from, edge.to, String(index))
      Object.assign(edge.label.style, { left: `${at.x - at.width / 2}px`, top: `${at.y - at.height / 2}px` })
    }
  }
  scene.prepend(wires)
  for (const [id, el] of drawn) {
    const at = graph.node(id)
    Object.assign(el.style, { left: `${at.x - at.width / 2}px`, top: `${at.y - at.height / 2}px` })
  }
  const width = graph.graph().width ?? 0, height = graph.graph().height ?? 0
  // Keep type readable for unusually wide forks; the card owns that scrolling.
  const scale = width ? Math.min(1, Math.max(0.9, room / width)) : 1
  Object.assign(scene.style, { width: `${width}px`, height: `${height}px`, transform: `scale(${scale})`, transformOrigin: "0 0" })
  Object.assign(container.style, { width: `${Math.ceil(width * scale)}px`, height: `${Math.ceil(height * scale)}px`, marginInline: "auto" })
}
