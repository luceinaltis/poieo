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

import { changedFlows } from "../changed"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import type { StageState, FlowState } from "../../state/stage"
import {
  BOX, arrivals, backWire, corner, depths, exits, fit, loops, pan, place, wire, zoom,
} from "../wiring"
import type { Frame } from "../wiring"
import type { Placed, View } from "../wiring"
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
function describeRecent(flowState: FlowState): string {
  const recent = flowState.recent
  if (recent.runs === 0) return "nothing has run yet"

  const parts: string[] = []
  if (recent.succeeded) {
    // A flow with no private copy has nothing to change against, so a run
    // that ran is the whole of what there is to say about it.
    const what = flowState.tracked ? "change" : "run"
    parts.push(`${recent.succeeded} ${what}${recent.succeeded === 1 ? "" : "s"}`)
  }
  if (recent.insertions || recent.deletions) {
    parts.push(`+${recent.insertions} / -${recent.deletions}`)
  }
  if (recent.failed) parts.push(`${recent.failed} failed`)

  if (parts.length > 0) return parts.join(" · ")
  const last = flowState.lastRun?.finished_at
  return last ? `quiet · last looked ${shortTime(last)}` : "quiet"
}

/** The distinct models a flow's nodes would call, in the order they appear. */
function modelsOf(flowState: FlowState): string[] {
  const seen: string[] = []
  for (const node of flowState.shape.nodes) {
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
function describeWhen(flowState: FlowState): string {
  const models = modelsOf(flowState)
  if (models.length === 0) return flowState.trigger
  return `${flowState.trigger} · ${models.length === 1 ? models[0] : `${models.length} models`}`
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
  pick.addEventListener("click", () => callbacks.onSelectFlow(flow))
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
function fillInside(box: Box, flowState: FlowState): void {
  const leaves = new Set(exits(flowState.shape))
  // Which nodes something to their left points at. Hung on the arriving
  // node, so a router draws an arrow into every arm rather than one.
  const reached = new Set(arrivals(flowState.shape))
  // Only when they differ. A flow on one model has already said so on the
  // header, and repeating it four times would be noise for one answer.
  const differ = modelsOf(flowState).length > 1
  const nodes = depths(flowState.shape).map((cell) => {
    const id = cell.id
    const pill = document.createElement("span")
    pill.className = "basic-node"
    pill.dataset.node = id
    // A column per step from the entry, a row per arm of a branch. In one
    // wrapping line a router's arms read as four steps in a row.
    pill.style.gridColumn = String(cell.column + 1)
    pill.style.gridRow = String(cell.row + 1)
    const spec = flowState.shape.nodes.find((node) => node.id === id)
    if (spec) pill.dataset.type = spec.type
    // Where a handoff leaves from, once you can see the nodes at all.
    if (leaves.has(id) && flowState.then.length > 0) pill.dataset.exit = "true"
    if (reached.has(id)) pill.dataset.from = "true"
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
function paint(box: Box, flowState: FlowState, open: boolean): void {
  box.root.dataset.status = flowState.status
  box.root.dataset.open = String(open)
  box.toggle.textContent = open ? "▾" : "▸"
  box.toggle.setAttribute("aria-expanded", String(open))
  box.when.textContent = describeWhen(flowState)

  for (const pill of Array.from(box.inside.children) as HTMLElement[]) {
    pill.dataset.here = String(pill.dataset.node === flowState.currentNode)
  }

  const thinking = !flowState.lastText && Boolean(flowState.lastThinking)
  box.said.dataset.thinking = String(thinking)
  box.said.textContent = flowState.lastText || flowState.lastThinking || ""

  box.tools.replaceChildren(
    ...flowState.recentToolCalls.map((call) => {
      const item = document.createElement("li")
      item.className = "basic-tool"
      item.dataset.error = String(Boolean(call.error))
      item.textContent = call.name
      return item
    }),
  )
  box.tally.textContent = describeRecent(flowState)
}

/**
 * Where the rows really are, once the boxes have been built.
 *
 * The one measurement in this file, and it is taken here because this is the
 * one place that already runs only when the wiring changes -- a border's
 * height is a fact about its graph, not about the frame arriving over SSE.
 * `BOX.height` remains the fallback the tests are written against.
 */
function measure(placed: Placed[], boxes: Map<string, Box>): Frame {
  const heights: Record<string, number> = {}
  const tall: number[] = []
  for (const one of placed) {
    const height = boxes.get(one.flow)?.root.offsetHeight || BOX.height
    heights[one.flow] = height
    tall[one.row] = Math.max(tall[one.row] ?? 0, height)
  }

  const tops: number[] = []
  let y = 0
  for (let row = 0; row < tall.length; row += 1) {
    tops[row] = y
    y += (tall[row] ?? BOX.height) + BOX.gapY
  }
  return { tops, bottom: y - BOX.gapY, heights }
}

function drawWires(
  svg: SVGElement,
  stage: StageState,
  placed: Placed[],
  frame: Frame,
): void {
  const at = new Map(placed.map((one) => [one.flow, one]))
  const lastRow = placed.reduce((low, one) => Math.max(low, one.row), 0)
  const lines: SVGElement[] = []

  for (const [flow, flowState] of Object.entries(stage.flows)) {
    const from = at.get(flow)
    if (from === undefined) continue
    for (const arrow of flowState.then) {
      const to = arrow.to === null ? undefined : at.get(arrow.to)
      // A branch that deliberately stops has nothing to point at, and a target
      // that is disabled has no box on this board.
      if (to === undefined) continue
      const back = loops(from, to) ? backWire(from, to, lastRow, frame) : null
      const line = back ?? wire(from, to, frame)

      const path = document.createElementNS(SVG, "path")
      path.setAttribute("class", "basic-wire")
      path.setAttribute(
        "d",
        back
          ? `M ${back.x1} ${back.y1} H ${back.turn} V ${back.under} H ${back.x2} V ${back.y2}`
          : `M ${line.x1} ${line.y1} C ${line.turn} ${line.y1}, ${line.turn} ${line.y2}, ${line.x2} ${line.y2}`,
      )
      lines.push(path)

      // A head, because the rule the whole board rests on is that an arrow
      // crosses a border. A bare line says two flows are related; it does not
      // say which one ends and which one begins.
      //
      // Going back it points up instead, into an underside. A forward arrow
      // always arrives at a left edge, so one arriving from below cannot be
      // mistaken for a step onward.
      const head = document.createElementNS(SVG, "path")
      head.setAttribute("class", "basic-tip")
      head.setAttribute(
        "d",
        back
          ? `M ${back.x2 - 4} ${back.y2 + 8} L ${back.x2} ${back.y2} L ${back.x2 + 4} ${back.y2 + 8} Z`
          : `M ${line.x2 - 8} ${line.y2 - 4} L ${line.x2} ${line.y2} L ${line.x2 - 8} ${line.y2 + 4} Z`,
      )
      lines.push(head)

      const word = document.createElementNS(SVG, "text")
      word.setAttribute("class", "basic-word")
      // Forward, the bend is the middle of the gap the arrow crosses; going
      // back, the middle of the long leg underneath. Either way it is the one
      // piece of the route that is nowhere near a border.
      word.setAttribute("x", String(back ? (back.turn + back.x2) / 2 : line.turn))
      // On the line, not above it: floated, the word sat against the border
      // below and read as that box's label rather than this arrow's.
      word.setAttribute("y", String(back ? back.under : (line.y1 + line.y2) / 2))
      word.textContent = arrow.label
      lines.push(word)
    }
  }
  svg.replaceChildren(...lines)
}

/** Whether the layout has to be worked out again, rather than just repainted. */
/**
 * What the layout depends on: who hands to whom, and which borders are open.
 *
 * Open belongs here because it changes a border's height, and the rows and the
 * arrows are measured off those heights. Left out, a flow that starts running
 * grows and every arrow keeps the geometry of the board before it did.
 */
function wiringKey(stage: StageState, open: (flow: string, at: FlowState) => boolean): string {
  return Object.entries(stage.flows)
    .map(
      ([flow, flowState]) =>
        `${flow}>${flowState.then.map((a) => a.to).join(",")}${open(flow, flowState) ? "+" : "-"}`,
    )
    .join("|")
}

export const basic: Skin = {
  id: "basic",
  label: "Basic",

  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle {
    // The board hangs in a viewport that fills the host. The board is sized by
    // its own layout and cannot place itself; the viewport is the window it is
    // seen through, and one transform on the board decides what is on screen.
    const viewport = element("div", "basic-viewport", el)
    const board = element("div", "basic", viewport)
    const svg = document.createElementNS(SVG, "svg")
    svg.setAttribute("class", "basic-wires")
    board.append(svg)

    const boxes = new Map<string, Box>()
    const painted = new Map<string, FlowState>()
    // Only flows the reader has touched. Everything else follows the rule
    // below, so the board opens where something is happening and stays quiet
    // everywhere else.
    const byHand = new Map<string, boolean>()
    let key = ""
    // The last stage drawn, so a border opened by hand can lay the board out
    // again -- it just changed a height, and the arrows are drawn off those.
    let last: StageState | null = null
    // A fit is only true of the board and the window it was measured from, so
    // a window that changes size needs a new one. Guarded: the observer is not
    // in jsdom, and a skin that cannot watch simply keeps the fit it has.
    const watching =
      typeof ResizeObserver === "undefined" ? null : new ResizeObserver(() => show())
    watching?.observe(viewport)

    // Null until the reader moves the board themselves; after that it is their
    // view, and `show` stops fitting.
    let chosen: View | null = null

    // A box's own controls are buttons, and a press on one of those is a click
    // on the box rather than a grab of the board behind it.
    const grabbable = (event: Event): boolean =>
      !(event.target as HTMLElement | null)?.closest("button")

    viewport.addEventListener("pointerdown", (event) => {
      if (!grabbable(event) || event.button !== 0) return
      const from = { x: event.clientX, y: event.clientY }
      viewport.setPointerCapture(event.pointerId)
      viewport.dataset.grabbing = "true"

      const move = (to: PointerEvent) => {
        chosen = pan(chosen ?? where(), to.clientX - from.x, to.clientY - from.y)
        from.x = to.clientX
        from.y = to.clientY
        show()
      }
      const done = () => {
        viewport.dataset.grabbing = "false"
        viewport.removeEventListener("pointermove", move)
        viewport.removeEventListener("pointerup", done)
        viewport.removeEventListener("pointercancel", done)
      }
      viewport.addEventListener("pointermove", move)
      viewport.addEventListener("pointerup", done)
      viewport.addEventListener("pointercancel", done)
    })

    // Not passive: a wheel over the board zooms it rather than scrolling the
    // page, and saying so has to happen before the default does.
    viewport.addEventListener(
      "wheel",
      (event) => {
        event.preventDefault()
        const box = viewport.getBoundingClientRect()
        chosen = zoom(chosen ?? where(), Math.exp(-event.deltaY * 0.0015), {
          x: event.clientX - box.left,
          y: event.clientY - box.top,
        })
        show()
      },
      { passive: false },
    )

    // The way back. A board a reader has lost themselves in is otherwise only
    // recoverable by reloading the page.
    viewport.addEventListener("dblclick", (event) => {
      if (!grabbable(event)) return
      chosen = null
      show()
    })

    const isOpen = (flow: string, flowState: FlowState): boolean =>
      byHand.get(flow) ?? flowState.status === "running"

    function relayout(stage: StageState): void {
      const flows = Object.keys(stage.flows)
      const handoffs: Record<string, string[]> = {}
      for (const [flow, flowState] of Object.entries(stage.flows)) {
        handoffs[flow] = flowState.then
          .map((arrow) => arrow.to)
          .filter((to): to is string => to !== null)
      }
      const placed = place(flows, handoffs)
      const rows = measure(placed, boxes)
      for (const one of placed) {
        const box = boxes.get(one.flow)
        if (box === undefined) continue
        const spot = corner(one, rows)
        box.root.style.left = `${spot.x}px`
        box.root.style.top = `${spot.y}px`
      }
      const columns = Math.max(1, ...placed.map((one) => one.column + 1))
      // The gaps sit between columns, so the last one is trailing air.
      board.style.width = `${columns * (BOX.width + BOX.gapX) - BOX.gapX}px`
      // Room below for the return leg of a handoff that goes back, which is
      // drawn half a gap under the lowest box. Trimmed to `rows.bottom`, the
      // fit would size the board without it and the viewport would clip it.
      board.style.height = `${rows.bottom + BOX.gapY}px`
      drawWires(svg, stage, placed, rows)
      show()
    }

    /**
     * Where the board sits: the reader's own view, or the fit if they have not
     * asked for one.
     *
     * A fit is only true of the board and the window it was measured from, so
     * it is recomputed rather than stored -- but the moment a reader drags or
     * zooms, their view is theirs and no later frame may take it back. Same
     * rule the open borders follow.
     */
    function where(): View {
      return (
        chosen ??
        fit(
          { width: board.offsetWidth, height: board.offsetHeight },
          { width: viewport.clientWidth, height: viewport.clientHeight },
        )
      )
    }

    function show(): void {
      const view = where()
      board.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`
    }

    return {
      update(stage: StageState) {
        let moved = false
        for (const [flow, flowState] of changedFlows(stage.flows, painted)) {
          let box = boxes.get(flow)
          if (box === undefined) {
            box = buildBox(flow, callbacks)
            box.toggle.addEventListener("click", () => {
              byHand.set(flow, !isOpen(flow, painted.get(flow) ?? flowState))
              const now = painted.get(flow)
              if (now !== undefined) paint(box!, now, isOpen(flow, now))
              if (last !== null) relayout(last)
            })
            boxes.set(flow, box)
            board.append(box.root)
            moved = true
          }
          fillInside(box, flowState)
          paint(box, flowState, isOpen(flow, flowState))
        }
        for (const [flow, box] of boxes) {
          if (!(flow in stage.flows)) {
            box.root.remove()
            boxes.delete(flow)
            byHand.delete(flow)
            moved = true
          }
        }
        last = stage
        const fresh = wiringKey(stage, isOpen)
        if (moved || fresh !== key) {
          key = fresh
          relayout(stage)
        }
      },

      destroy() {
        watching?.disconnect()
        boxes.clear()
        viewport.remove()
      },
    }
  },
}
