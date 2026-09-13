/** Compact task flows expand into vertical graphs with conditions on their wires. */
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

function inputPort(receives: boolean) {
  const input = html("span", "basic-step-start", receives ? "Input" : "Start")
  if (receives) {
    input.dataset.port = "input"
    input.tabIndex = 0
    input.title = "The sending task's completed run is received here."
  }
  return input
}

function outputPort() {
  const output = html("span", "basic-step-output", "Output")
  output.dataset.port = "output"
  output.tabIndex = 0
  output.title = "This completed run's results, state and answer are passed to the next task."
  output.append(html("small", "", "Run result"))
  return output
}

/** The hidden steps occupy one short connection between the same task terminals. */
export function drawCardSummary(container: HTMLElement, task: TaskState, receives: boolean) {
  const sends = task.then.some(way => way.to !== null)
  const count = task.shape.nodes.length
  const scene = html("div", "basic-step-scene basic-step-summary")
  const start = inputPort(receives)
  const steps = html("span", "basic-step-count", `${count} ${count === 1 ? "step" : "steps"}`)
  const end = sends ? outputPort() : html("span", "basic-step-end", "End run")
  Object.assign(start.style, { left: "10px", top: "20px", width: "60px" })
  Object.assign(steps.style, { left: "98px", top: "19px", width: "76px" })
  Object.assign(end.style, { left: "202px", top: sends ? "10px" : "19px", width: "88px" })
  const wires = svg("svg", { class: "basic-step-wires", width: "300", height: "64", "aria-hidden": "true" })
  wires.append(svg("path", { class: "basic-summary-edge", d: "M70 32 H94 M174 32 H198" }),
    svg("path", { class: "basic-summary-arrow", d: "M98 32 l-5 -3 v6 Z M202 32 l-5 -3 v6 Z" }))
  scene.append(wires, start, steps, end)
  Object.assign(scene.style, { width: "300px", height: "64px" })
  Object.assign(container.style, { width: "300px", height: "64px", marginInline: "auto" })
  container.replaceChildren(scene)
  return 300
}

export function drawCardSteps(container: HTMLElement, task: TaskState, receives = false) {
  const shape = task.shape
  const sends = task.then.some(way => way.to !== null)
  const connected = receives || sends
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
  if (nodes.has(shape.entry) || receives) {
    add("start", inputPort(receives), 60, 24)
    if (nodes.has(shape.entry)) connect("start", keyOf(shape.entry), `${receives ? "Input" : "Start"} → ${nameOf(shape.entry)}`)
  }
  if (sends) add("output", outputPort(), 100, 44)
  for (const id of walk(shape)) {
    const ways = waysOut(nodes.get(id)!)
    if (!ways.length) ways.push({ to: null, label: "", fallback: false })
    const ordered = ways.filter(way => way.label && !way.fallback).length > 1
    let conditionNumber = 0
    for (const [index, way] of ways.entries()) {
      if (way.label && !way.fallback) conditionNumber++
      if (way.to !== null && !nodes.has(way.to)) continue
      const to = way.to === null ? `end:${id}:${index}` : keyOf(way.to)
      if (way.to === null) {
        add(to, html("span", "basic-step-end", "End run"), 68, 26)
        if (sends) {
          const answer = nodes.get(id)!.type === "confirm" ? html("span", "basic-step-condition", "After answer") : undefined
          connect(to, "output", `End run → Output${answer ? ": After answer" : ""}`, answer)
        }
      }
      const condition = way.fallback ? "Otherwise" : way.label ? `${ordered ? `${conditionNumber}. ` : ""}If ${way.label}` : ""
      const label = condition ? html("span", "basic-step-condition", condition) : undefined
      if (ordered && label) label.title = "The first matching condition chooses the next step."
      const description = `${nameOf(id)} → ${way.to === null ? "End run" : nameOf(way.to)}${condition ? `: ${condition}` : ""}`
      connect(keyOf(id), to, description, label, id)
    }
  }
  if (sends) task.then.forEach((way, index) => {
    if (way.to !== null) return
    const end = `handoff-end:${index}`
    add(end, html("span", "basic-step-end", "Stop here"), 76, 26)
    const label = `${task.then.length > 1 ? `${index + 1}. ` : ""}${way.label}`
    connect("output", end, `Output → Stop here: ${label}`, html("span", "basic-step-condition", label))
  })
  dagre.layout(graph)
  const room = (container.parentElement?.clientWidth || 310) - 2
  // Conditions can use more lines before the graph needs to use smaller type.
  if (!connected && (graph.graph().width ?? 0) > room) {
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
  const scale = !connected && width ? Math.min(1, Math.max(0.9, room / width)) : 1
  Object.assign(scene.style, { width: `${width}px`, height: `${height}px`, transform: `scale(${scale})`, transformOrigin: "0 0" })
  Object.assign(container.style, { width: `${Math.ceil(width * scale)}px`, height: `${Math.ceil(height * scale)}px`, marginInline: "auto" })
  return Math.ceil(width * scale)
}
