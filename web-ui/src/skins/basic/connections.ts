/** Task handoffs join the actual graph terminals, through the space between cards. */
import { keyOfTask, type StageState } from "../../state/stage"
import type { Placed } from "../wiring"
import { wireWord } from "../../connection"
import { edgePath } from "./graph"

export interface ConnectedBox { root: HTMLElement; steps: HTMLElement }
const NS = "http://www.w3.org/2000/svg"
function svg(tag: string, attributes: Record<string, string>) {
  const el = document.createElementNS(NS, tag)
  for (const [key, value] of Object.entries(attributes)) el.setAttribute(key, value)
  return el
}

export function taskConnections(stage: StageState) {
  const connections = new Map<string, { from: string; to: string; labels: string[] }>()
  for (const [from, task] of Object.entries(stage.tasks)) task.then.forEach((way, index) => {
    if (way.to === null) return
    const to = keyOfTask(task.project, way.to)
    if (!stage.tasks[to]) return
    const key = JSON.stringify([from, to])
    const connection = connections.get(key) ?? { from, to, labels: [] }
    connection.labels.push(`${task.then.length > 1 ? `${index + 1}. ` : ""}${wireWord(way.label, way.when)}`)
    connections.set(key, connection)
  })
  return [...connections.values()]
}

/** Coordinates in the board's space, independent of its current pan and zoom. */
function anchor(box: ConnectedBox, side: "input" | "output") {
  const port = box.steps.querySelector<HTMLElement>(`[data-port="${side}"]`)!
  const card = box.root.getBoundingClientRect(), at = port.getBoundingClientRect()
  const left = parseFloat(box.root.style.left), top = parseFloat(box.root.style.top)
  const width = parseFloat(box.root.style.width)
  const scale = card.width / width || 1
  return at.width ? {
    x: left + ((side === "output" ? at.right : at.left) - card.left) / scale,
    y: top + (at.top + at.height / 2 - card.top) / scale,
  } : {
    // jsdom has no layout; the diagram still provides its own terminal positions.
    x: left + parseFloat(port.style.left) + (side === "output" ? parseFloat(port.style.width) : 0),
    y: top + parseFloat(port.style.top) + (side === "output" ? 22 : 12),
  }
}

function wrap(text: string): string[] {
  const lines: string[] = []
  while (text.length > 13) {
    const space = text.lastIndexOf(" ", 13)
    const cut = space > 0 ? space : 13
    lines.push(text.slice(0, cut))
    text = text.slice(cut).trimStart()
  }
  if (text) lines.push(text)
  return lines
}

export function drawConnections(
  canvas: SVGElement, stage: StageState, placed: Placed[], boxes: Map<string, ConnectedBox>, bottom: number,
  follow: (task: string, input: { x: number; y: number }) => void, trace: (from: string | null, to?: string) => void,
) {
  const focused = document.activeElement?.closest<SVGElement>(".basic-connection")
  const keepFocus = focused && canvas.contains(focused)
  const positions = new Map(placed.map(at => [at.task, at]))
  const columnRight = new Map<number, number>()
  for (const at of placed) {
    const root = boxes.get(at.task)!.root
    columnRight.set(at.column, Math.max(columnRight.get(at.column) ?? 0,
      parseFloat(root.style.left) + parseFloat(root.style.width)))
  }
  const groups: SVGElement[] = []
  let floor = bottom + 24
  for (const connection of taskConnections(stage)) {
    const from = boxes.get(connection.from)!, to = boxes.get(connection.to)!
    const start = anchor(from, "output"), end = anchor(to, "input")
    const toLeft = parseFloat(to.root.style.left)
    const before = positions.get(connection.from)!, after = positions.get(connection.to)!
    // The lane must clear every card in this column, including wider siblings.
    const fromRight = columnRight.get(before.column)!
    const returning = after.column <= before.column
    // A forward wire that skips columns runs straight along its own row when
    // no card in the columns between stands on that row, and turns into the
    // gap just before its target. Only a wire with something in its way, or
    // one going back, takes the long road under the board.
    const skips = after.column > before.column + 1
    const clear = skips && !placed.some((at) => {
      if (at.column <= before.column || at.column >= after.column) return false
      const root = boxes.get(at.task)!.root
      const top = parseFloat(root.style.top)
      return start.y >= top - 12 && start.y <= top + root.offsetHeight + 12
    })
    const outer = after.column !== before.column + 1 && !clear
    const words = connection.labels.flatMap(wrap)
    const turn = clear ? toLeft - 20 : (fromRight + toLeft) / 2
    const under = floor + words.length * 7.5
    const points = outer ? [start, { x: fromRight + 20, y: start.y },
      { x: fromRight + 20, y: under }, { x: toLeft - 20, y: under },
      { x: toLeft - 20, y: end.y }, end] : [start,
      { x: turn, y: start.y }, { x: turn, y: end.y }, end]
    if (outer) floor = under + words.length * 7.5 + 24
    const description = `${stage.tasks[connection.from].name} output → ${stage.tasks[connection.to].name} input: ${connection.labels.join("; ")}`
    const group = svg("g", { class: "basic-connection", "data-from": connection.from, "data-to": connection.to,
      "data-return": String(returning), "data-route": outer ? "under" : "across", role: "button", tabindex: "0", "aria-label": description })
    const title = svg("title", {})
    title.textContent = `${description}. Follow this connection to the receiving task. The first matching condition wins.`
    group.append(title,
      svg("path", { class: "basic-connection-hit", d: edgePath(points) }),
      svg("path", { class: "basic-wire", d: edgePath(points) }),
      svg("path", { class: "basic-tip", d: `M ${end.x - 8} ${end.y - 4} L ${end.x} ${end.y} L ${end.x - 8} ${end.y + 4} Z` }),
      svg("circle", { class: "basic-socket", cx: String(start.x), cy: String(start.y), r: "3.5" }),
    )
    // Beside a straight run, the words sit on it halfway along the row.
    const wordX = clear ? (fromRight + toLeft - 20) / 2 : turn
    const wordY = outer ? under : clear ? start.y : (start.y + end.y) / 2
    const label = svg("text", { class: "basic-word", x: String(wordX), y: String(wordY) })
    words.forEach((word, index) => {
      const line = svg("tspan", { x: String(wordX), dy: String(index ? 15 : -(words.length - 1) * 7.5) })
      line.textContent = word
      label.append(line)
    })
    group.append(label)
    group.addEventListener("focus", () => trace(connection.from, connection.to))
    group.addEventListener("blur", () => trace(null))
    group.addEventListener("pointerenter", () => trace(connection.from, connection.to))
    group.addEventListener("pointerleave", () => { if (document.activeElement !== group) trace(null) })
    group.addEventListener("click", () => follow(connection.to, end))
    group.addEventListener("keydown", (event) => {
      if (event.key !== "Enter" && event.key !== " ") return
      event.preventDefault()
      follow(connection.to, end)
    })
    groups.push(group)
  }
  canvas.replaceChildren(...groups)
  // A title can change card height while the reader is about to follow a wire.
  if (keepFocus) groups.find(group => group.dataset.from === focused.dataset.from && group.dataset.to === focused.dataset.to)
    ?.focus({ preventScroll: true })
  return floor
}
