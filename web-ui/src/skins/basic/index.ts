/**
 * The plain view: the work as a graph, with one noun on screen.
 *
 * Everything drawn here is a node. A flow is a node too -- shut it is a box
 * with a name, open it is that box with its graph's nodes inside. There is no
 * mode to be in and nothing to remember about where you are; some nodes open.
 *
 * One rule reads the whole picture: **an arrow that crosses a border ends one
 * run and starts another.** Inside a border is the next step, immediately,
 * sharing scope. Across one is a new run, a new private copy, and one more
 * thing to accept or discard in the morning. That is also the shortest true
 * definition of a run this project has managed to write down.
 *
 * Structure and state are drawn apart on purpose. The layout and the arrows
 * come from the wiring, which changes only when a file does; the highlight
 * and the words underneath change every few seconds. Laying out again on
 * every frame would make the board unreadable as well as slow.
 */

import { changedWorkers } from "../changed"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import type { StageState, Worker } from "../../state/stage"
import { BOX, corner, exits, place, steps, walk, wire } from "../wiring"
import type { Placed } from "../wiring"
import { shortTime } from "../../when"
import "./basic.css"

const SVG = "http://www.w3.org/2000/svg"

interface Box {
  root: HTMLElement
  toggle: HTMLElement
  when: HTMLElement
  inside: HTMLElement
  said: HTMLElement
  tools: HTMLElement
  tally: HTMLElement
}

function element(tag: string, className: string, parent: Element): HTMLElement {
  const node = document.createElement(tag)
  node.className = className
  parent.append(node)
  return node
}

/**
 * What a flow has amounted to lately -- results, not attempts.
 *
 * The line used to count every run, including the ones that looked and found
 * nothing to do. For a healthy flow that is nearly all of them, so the number
 * grew large and said nothing: "864 runs · 864 found nothing to do" is a
 * sentence a reader learns to skip.
 *
 * What is left is what happened. A flow that changed nothing says so in one
 * word and gives the time it last looked -- which is the whole of what tells
 * "fine, and there was nothing to do" apart from "stuck", and the only reason
 * the count was ever wanted.
 */
function describeRecent(worker: Worker): string {
  const recent = worker.recent
  if (recent.runs === 0) return "nothing has run yet"

  const parts: string[] = []
  if (recent.succeeded) {
    // A flow with no private copy has nothing to change against, so a run
    // that ran is the whole of what there is to say about it.
    const what = worker.tracked ? "change" : "run"
    parts.push(`${recent.succeeded} ${what}${recent.succeeded === 1 ? "" : "s"}`)
  }
  if (recent.insertions || recent.deletions) {
    parts.push(`+${recent.insertions} / -${recent.deletions}`)
  }
  if (recent.failed) parts.push(`${recent.failed} failed`)

  if (parts.length > 0) return parts.join(" · ")
  const last = worker.lastRun?.finished_at
  return last ? `quiet · last looked ${shortTime(last)}` : "quiet"
}

/** The distinct models a flow's nodes would call, in the order they appear. */
function modelsOf(worker: Worker): string[] {
  const seen: string[] = []
  for (const node of worker.shape.nodes) {
    if (node.model && !seen.includes(node.model)) seen.push(node.model)
  }
  return seen
}

/**
 * The trigger, and what will actually run on it.
 *
 * One model is the common case and the whole answer, so it is said once and
 * said here -- this line is legible with the border shut, and ten flows shut
 * is the glance the board is for. More than one cannot be said in a word, so
 * the count says so and the nodes inside carry the detail. Opening buys the
 * answer, exactly as it does for a handoff arrow.
 */
function describeWhen(worker: Worker): string {
  const models = modelsOf(worker)
  if (models.length === 0) return worker.trigger
  return `${worker.trigger} · ${models.length === 1 ? models[0] : `${models.length} models`}`
}

function buildBox(flow: string, callbacks: SkinCallbacks): Box {
  const root = document.createElement("div")
  root.className = "basic-flow"
  root.dataset.flow = flow
  // The one width, from the constant the arrows are drawn against. Written in
  // the stylesheet it was free to drift from them, and it had.
  root.style.width = `${BOX.width}px`

  const head = element("div", "basic-head", root)
  // Two things to click, so neither has to mean two things: the name selects
  // the flow, exactly as a card did, and the chevron opens the box.
  const pick = element("button", "basic-pick", head)
  ;(pick as HTMLButtonElement).type = "button"
  pick.addEventListener("click", () => callbacks.onSelectWorker(flow))
  element("span", "basic-dot", pick)
  element("span", "basic-name", pick).textContent = flow

  const toggle = element("button", "basic-toggle", head)
  ;(toggle as HTMLButtonElement).type = "button"
  toggle.textContent = "▾"

  return {
    root,
    toggle,
    when: element("div", "basic-when", root),
    inside: element("div", "basic-inside", root),
    said: element("p", "basic-said", root),
    tools: element("ul", "basic-tools", root),
    tally: element("div", "basic-tally", root),
  }
}

/** The graph inside a border, drawn once: it moves only when a file does. */
function fillInside(box: Box, worker: Worker): void {
  const leaves = new Set(exits(worker.shape))
  // Which neighbouring pairs are a real edge. Drawn between every pair, the
  // connector claims the router's arms run into one another.
  const leads = new Set(steps(worker.shape))
  // Only when they differ. A flow on one model has already said so on the
  // header, and repeating it four times would be noise for one answer.
  const differ = modelsOf(worker).length > 1
  const nodes = walk(worker.shape).map((id) => {
    const pill = document.createElement("span")
    pill.className = "basic-node"
    pill.dataset.node = id
    const spec = worker.shape.nodes.find((node) => node.id === id)
    if (spec) pill.dataset.type = spec.type
    // Where a handoff leaves from, once you can see the nodes at all.
    if (leaves.has(id) && worker.then.length > 0) pill.dataset.exit = "true"
    if (leads.has(id)) pill.dataset.leadsOn = "true"
    pill.textContent = id
    // A router has no model because it calls none, and the gap is itself
    // information: it is why branching is free.
    if (differ && spec?.model) {
      element("span", "basic-node-model", pill).textContent = spec.model
    }
    return pill
  })
  box.inside.replaceChildren(...nodes)
}

/** What moves: which node is lit, and what the flow has been saying. */
function paint(box: Box, worker: Worker, open: boolean): void {
  box.root.dataset.status = worker.status
  box.root.dataset.open = String(open)
  box.toggle.textContent = open ? "▾" : "▸"
  box.toggle.setAttribute("aria-expanded", String(open))
  box.when.textContent = describeWhen(worker)

  for (const pill of Array.from(box.inside.children) as HTMLElement[]) {
    pill.dataset.here = String(pill.dataset.node === worker.currentNode)
  }

  const thinking = !worker.lastText && Boolean(worker.lastThinking)
  box.said.dataset.thinking = String(thinking)
  box.said.textContent = worker.lastText || worker.lastThinking || ""

  box.tools.replaceChildren(
    ...worker.recentToolCalls.map((call) => {
      const item = document.createElement("li")
      item.className = "basic-tool"
      item.dataset.error = String(Boolean(call.error))
      item.textContent = call.name
      return item
    }),
  )
  box.tally.textContent = describeRecent(worker)
}

function drawWires(svg: SVGElement, stage: StageState, placed: Placed[]): void {
  const at = new Map(placed.map((one) => [one.flow, one]))
  const lines: SVGElement[] = []

  for (const [flow, worker] of Object.entries(stage.workers)) {
    const from = at.get(flow)
    if (from === undefined) continue
    for (const arrow of worker.then) {
      const to = arrow.to === null ? undefined : at.get(arrow.to)
      // A branch that deliberately stops has nothing to point at, and a target
      // that is disabled has no box on this board.
      if (to === undefined) continue
      const line = wire(from, to)
      const mid = (line.x1 + line.x2) / 2

      const path = document.createElementNS(SVG, "path")
      path.setAttribute("class", "basic-wire")
      path.setAttribute(
        "d",
        `M ${line.x1} ${line.y1} C ${mid} ${line.y1}, ${mid} ${line.y2}, ${line.x2} ${line.y2}`,
      )
      lines.push(path)

      // A head, because the rule the whole board rests on is that an arrow
      // crosses a border. A bare line says two flows are related; it does not
      // say which one ends and which one begins.
      const head = document.createElementNS(SVG, "path")
      head.setAttribute("class", "basic-tip")
      head.setAttribute(
        "d",
        `M ${line.x2 - 8} ${line.y2 - 4} L ${line.x2} ${line.y2} L ${line.x2 - 8} ${line.y2 + 4} Z`,
      )
      lines.push(head)

      const word = document.createElementNS(SVG, "text")
      word.setAttribute("class", "basic-word")
      word.setAttribute("x", String(mid))
      // On the line, not above it: floated, the word sat against the border
      // below and read as that box's label rather than this arrow's.
      word.setAttribute("y", String((line.y1 + line.y2) / 2))
      word.textContent = arrow.label
      lines.push(word)
    }
  }
  svg.replaceChildren(...lines)
}

/** Whether the layout has to be worked out again, rather than just repainted. */
function wiringKey(stage: StageState): string {
  return Object.entries(stage.workers)
    .map(([flow, worker]) => `${flow}>${worker.then.map((a) => a.to).join(",")}`)
    .join("|")
}

export const basic: Skin = {
  id: "basic",
  label: "Basic",

  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle {
    const board = element("div", "basic", el)
    const svg = document.createElementNS(SVG, "svg")
    svg.setAttribute("class", "basic-wires")
    board.append(svg)

    const boxes = new Map<string, Box>()
    const painted = new Map<string, Worker>()
    // Only flows the reader has touched. Everything else follows the rule
    // below, so the board opens where something is happening and stays quiet
    // everywhere else.
    const byHand = new Map<string, boolean>()
    let key = ""

    const isOpen = (flow: string, worker: Worker): boolean =>
      byHand.get(flow) ?? worker.status === "running"

    function relayout(stage: StageState): void {
      const flows = Object.keys(stage.workers)
      const handoffs: Record<string, string[]> = {}
      for (const [flow, worker] of Object.entries(stage.workers)) {
        handoffs[flow] = worker.then
          .map((arrow) => arrow.to)
          .filter((to): to is string => to !== null)
      }
      const placed = place(flows, handoffs)
      for (const one of placed) {
        const box = boxes.get(one.flow)
        if (box === undefined) continue
        const spot = corner(one)
        box.root.style.left = `${spot.x}px`
        box.root.style.top = `${spot.y}px`
      }
      const columns = Math.max(1, ...placed.map((one) => one.column + 1))
      const rows = Math.max(1, ...placed.map((one) => one.row + 1))
      board.style.width = `${columns * (BOX.width + BOX.gapX)}px`
      board.style.height = `${rows * (BOX.height + BOX.gapY)}px`
      drawWires(svg, stage, placed)
    }

    return {
      update(stage: StageState) {
        let moved = false
        for (const [flow, worker] of changedWorkers(stage.workers, painted)) {
          let box = boxes.get(flow)
          if (box === undefined) {
            box = buildBox(flow, callbacks)
            box.toggle.addEventListener("click", () => {
              byHand.set(flow, !isOpen(flow, painted.get(flow) ?? worker))
              const now = painted.get(flow)
              if (now !== undefined) paint(box!, now, isOpen(flow, now))
            })
            boxes.set(flow, box)
            board.append(box.root)
            moved = true
          }
          fillInside(box, worker)
          paint(box, worker, isOpen(flow, worker))
        }
        for (const [flow, box] of boxes) {
          if (!(flow in stage.workers)) {
            box.root.remove()
            boxes.delete(flow)
            byHand.delete(flow)
            moved = true
          }
        }
        const fresh = wiringKey(stage)
        if (moved || fresh !== key) {
          key = fresh
          relayout(stage)
        }
      },

      destroy() {
        boxes.clear()
        board.remove()
      },
    }
  },
}
