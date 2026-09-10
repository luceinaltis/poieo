/** A reading view of the task's existing graph, with its own zoom and live position. */
import type { StageState, TaskState } from "../../state/stage"
import { layOutSteps, stepName } from "./steps"
import type { LaidSteps } from "./steps"
import "./graph.css"

const NS = "http://www.w3.org/2000/svg"
const kinds: Record<string, string> = {
  agent: "Model", command: "Command", router: "Condition", confirm: "Ask a person",
}

function html<K extends keyof HTMLElementTagNameMap>(tag: K, cls: string, text = "") {
  const el = document.createElement(tag)
  el.className = cls
  el.textContent = text
  return el
}

function svg<K extends keyof SVGElementTagNameMap>(tag: K, attrs: Record<string, string>) {
  const el = document.createElementNS(NS, tag)
  for (const [key, value] of Object.entries(attrs)) el.setAttribute(key, value)
  return el
}

/** Round each bend while keeping the endpoints dagre routed to the node borders. */
export function edgePath(points: { x: number; y: number }[]): string {
  if (!points.length) return ""
  let path = `M${points[0].x} ${points[0].y}`
  for (let i = 1; i < points.length - 1; i++) {
    const a = points[i - 1], b = points[i], c = points[i + 1]
    const before = Math.hypot(b.x - a.x, b.y - a.y)
    const after = Math.hypot(c.x - b.x, c.y - b.y)
    const radius = Math.min(12, before / 2, after / 2)
    if (!before || !after) continue
    const x = b.x + (c.x - b.x) * radius / after
    const y = b.y + (c.y - b.y) * radius / after
    path += ` L${b.x + (a.x - b.x) * radius / before} ${b.y + (a.y - b.y) * radius / before} Q${b.x} ${b.y} ${x} ${y}`
  }
  const end = points[points.length - 1]
  return `${path} L${end.x} ${end.y}`
}

export function createGraphDialog(host: HTMLElement) {
  const dialog = html("dialog", "graph-dialog")
  const header = html("header", "graph-header")
  const title = html("h2", "graph-title")
  const context = html("p", "graph-context")
  const heading = html("div", "graph-heading")
  heading.append(title, context)
  const close = html("button", "graph-close", "close")
  close.type = "button"
  close.setAttribute("aria-label", "Close steps")
  close.addEventListener("click", () => dialog.close())
  header.append(heading, close)

  const toolbar = html("div", "graph-toolbar")
  const hint = html("p", "graph-hint", "Follow the arrows. A returning line repeats earlier work.")
  const controls = html("div", "graph-controls")
  const window = html("div", "graph-window")
  window.tabIndex = 0
  window.setAttribute("role", "region")
  window.setAttribute("aria-label", "Task steps, scroll to explore")
  const world = html("div", "graph-world")
  const scene = html("div", "graph-scene")
  world.append(scene)
  window.append(world)

  let selected: string | null = null
  let opener: HTMLElement | null = null
  let shapeKey = ""
  let laid: LaidSteps | null = null
  let zoom = 1
  const amount = html("output", "graph-zoom", "100%")
  amount.setAttribute("role", "status")
  amount.setAttribute("aria-live", "polite")
  const button = (name: string, text: string, action: () => void) => {
    const control = html("button", "", text)
    control.type = "button"
    control.setAttribute("aria-label", name)
    control.addEventListener("click", action)
    return control
  }
  const minus = button("Zoom out", "−", () => scale(zoom - 0.25))
  const plus = button("Zoom in", "+", () => scale(zoom + 0.25))
  const fit = button("Fit all steps", "Fit", () => scale(fitScale()))
  const actual = button("Actual size", "100%", () => scale(1))
  controls.append(minus, amount, plus, fit, actual)
  toolbar.append(hint, controls)
  dialog.append(header, toolbar, window)
  host.append(dialog)

  function fitScale() {
    if (!laid || window.clientWidth <= 24 || window.clientHeight <= 24) return 1
    return Math.min((window.clientWidth - 24) / laid.width, (window.clientHeight - 24) / laid.height, 1)
  }

  function scale(value: number) {
    if (!laid) return
    const previous = zoom
    const centre = {
      x: (window.scrollLeft + window.clientWidth / 2 - (parseFloat(scene.style.left) || 0)) / previous,
      y: (window.scrollTop + window.clientHeight / 2 - (parseFloat(scene.style.top) || 0)) / previous,
    }
    const minimum = Math.min(0.25, fitScale())
    zoom = Math.max(minimum, Math.min(2, value))
    // clientHeight rounds fractional CSS pixels up; leave a pixel to avoid
    // scrollbars repeatedly appearing and resizing an otherwise fitted scene.
    const width = Math.max(window.clientWidth - 1, laid.width * zoom)
    const height = Math.max(window.clientHeight - 1, laid.height * zoom)
    const left = (width - laid.width * zoom) / 2
    const top = (height - laid.height * zoom) / 2
    world.style.width = `${width}px`
    world.style.height = `${height}px`
    scene.style.left = `${left}px`
    scene.style.top = `${top}px`
    scene.style.transform = `scale(${zoom})`
    window.scrollLeft = centre.x * zoom + left - window.clientWidth / 2
    window.scrollTop = centre.y * zoom + top - window.clientHeight / 2
    amount.textContent = `${Math.round(zoom * 100)}%`
    minus.disabled = zoom <= minimum
    plus.disabled = zoom >= 2
  }

  function draw(task: TaskState) {
    shapeKey = JSON.stringify(task.shape)
    laid = layOutSteps(task.shape, () => ({ width: 208, height: 112 }), true)
    const names = new Map(task.shape.nodes.map(node => [node.id, stepName(node)]))
    const edges = svg("svg", { class: "graph-edges", width: String(laid.width), height: String(laid.height) })
    edges.setAttribute("role", "img")
    edges.setAttribute("aria-label", laid.edges.map(edge =>
      `${names.get(edge.from)} → ${edge.to ? names.get(edge.to) : "End run"}${edge.label ? `: ${edge.fallback ? "Otherwise" : edge.label}` : ""}`,
    ).join(". "))
    for (const edge of laid.edges) {
      const cls = edge.label ? "graph-edge graph-branch" : "graph-edge"
      const line = svg("path", { class: cls, d: edgePath(edge.points) })
      const end = edge.points[edge.points.length - 1]
      const before = edge.points[edge.points.length - 2] ?? end
      const angle = Math.atan2(end.y - before.y, end.x - before.x) * 180 / Math.PI
      const arrow = svg("path", { class: edge.label ? "graph-arrow graph-branch" : "graph-arrow", d: "M0 0 L-8 4 L-8 -4 Z", transform: `translate(${end.x} ${end.y}) rotate(${angle})` })
      edges.append(line, arrow)
      if (edge.at) {
        const word = svg("text", { class: "graph-edge-label", x: String(edge.at.x), y: String(edge.at.y - (edge.lines.length - 1) * 7.5) })
        edge.lines.forEach((text, index) => {
          const line = svg("tspan", { x: String(edge.at!.x), dy: index ? "15" : "0" })
          line.textContent = text
          word.append(line)
        })
        const full = svg("title", {})
        full.textContent = edge.fallback ? "Otherwise" : edge.label
        word.append(full)
        edges.append(word)
      }
    }
    scene.style.width = `${laid.width}px`
    scene.style.height = `${laid.height}px`
    scene.replaceChildren(edges)
    for (const step of laid.steps) {
      const node = task.shape.nodes.find(node => node.id === step.id)
      const card = html(step.stop ? "span" : "article", step.stop ? "graph-end" : "graph-node")
      Object.assign(card.style, { left: `${step.x - step.width / 2}px`, top: `${step.y - step.height / 2}px`, width: `${step.width}px`, height: `${step.height}px` })
      if (node) {
        card.dataset.node = node.id
        card.dataset.type = node.type
        card.dataset.entry = String(node.id === task.shape.entry)
        card.tabIndex = 0
        card.title = `${stepName(node)} (${node.id})`
        const kind = html("div", "graph-node-kind", kinds[node.type] || node.type)
        if (node.id === task.shape.entry) kind.append(html("span", "graph-entry", "Start"))
        card.append(kind, html("h3", "graph-node-name", stepName(node)))
        const meta = html("p", "graph-node-meta", node.model || node.id)
        meta.title = node.model || node.id
        card.append(meta)
        const footer = html("div", "graph-node-footer")
        if (node.tools.length) footer.append(html("span", "graph-node-tools", "Edits files"))
        if (step.ends) footer.append(html("span", "graph-node-finish", "Ends this run"))
        card.append(footer)
      } else card.textContent = "End run"
      scene.append(card)
    }
  }

  function paint(task: TaskState) {
    title.textContent = task.name
    const current = task.shape.nodes.find(node => node.id === task.currentNode)
    const now = task.status === "running" && current ? `Running: ${stepName(current)}`
      : task.status === "paused" ? task.enabled ? "Paused" : "Switched off"
        : task.status === "error" ? "Stopped" : "Waiting for its next turn"
    const count = task.shape.nodes.length
    context.textContent = `${count} ${count === 1 ? "step" : "steps"}. ${now}.`
    for (const card of scene.querySelectorAll<HTMLElement>("[data-node]")) {
      const active = task.status === "running" && card.dataset.node === task.currentNode
      card.dataset.here = String(active)
      if (active) card.setAttribute("aria-current", "step")
      else card.removeAttribute("aria-current")
    }
  }

  dialog.addEventListener("close", () => {
    selected = null
    if (opener?.isConnected) opener.focus()
    opener = null
  })
  const observer = typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => {
    if (dialog.open) scale(zoom)
  })
  observer?.observe(window)

  return {
    open(key: string, task: TaskState, from: HTMLElement) {
      selected = key
      opener = from
      zoom = 1
      dialog.setAttribute("aria-label", `Steps in ${task.name}`)
      draw(task)
      paint(task)
      dialog.showModal()
      scale(1)
      window.scrollLeft = 0
      window.scrollTop = 0
      close.focus()
    },
    update(stage: StageState) {
      if (selected === null) return
      const task = stage.tasks[selected]
      if (!task) { dialog.close(); return }
      if (shapeKey !== JSON.stringify(task.shape)) { draw(task); scale(zoom) }
      paint(task)
    },
    destroy() {
      if (dialog.open) dialog.close()
      observer?.disconnect()
      dialog.remove()
    },
  }
}
