/**
 * The plain view: the work as a graph, with one noun on screen.
 *
 * Everything drawn here is a node. A task is a node too -- shut it is a box
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

import { select } from "d3-selection"
import { zoom as d3zoom, zoomIdentity } from "d3-zoom"
import type { D3ZoomEvent } from "d3-zoom"

import { changedTasks } from "../changed"
import { layOutSteps } from "./steps"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import { keyOfTask } from "../../state/stage"
import type { StageState, TaskState } from "../../state/stage"
import {
  BOX, ZOOM, backWire, centreOn, corner, exits, fit, looking, loops, minimap,
  place, wire,
} from "../wiring"
import type { Frame, Placed, View } from "../wiring"
import { shortTime } from "../../when"
import "./basic.css"

const SVG = "http://www.w3.org/2000/svg"

/** How much corner the minimap may take. */
const MAP = { width: 200, height: 140 }

interface Box {
  root: HTMLElement
  name: HTMLElement
  toggle: HTMLElement
  when: HTMLElement
  now: HTMLElement
  inside: HTMLElement
  steps: HTMLElement
  said: HTMLElement
  tools: HTMLElement
  tally: HTMLElement
  warn: HTMLElement
  stale: HTMLElement
}

function element(tag: string, className: string, parent: Element): HTMLElement {
  const node = document.createElement(tag)
  node.className = className
  parent.append(node)
  return node
}

/**
 * What a task has amounted to lately -- results, not attempts.
 *
 * The line used to count every run, including the ones that looked and found
 * nothing to do. For a healthy task that is nearly all of them, so the number
 * grew large and said nothing: "864 runs · 864 found nothing to do" is a
 * sentence a reader learns to skip.
 *
 * What is left is what happened. A task that changed nothing says so in one
 * word and gives the time it last looked -- which is the whole of what tells
 * "fine, and there was nothing to do" apart from "stuck", and the only reason
 * the count was ever wanted.
 */
function describeRecent(flowState: TaskState): string {
  const recent = flowState.recent
  if (recent.runs === 0) return "nothing has run yet"

  const parts: string[] = []
  if (recent.succeeded) {
    // A task with no private copy has nothing to change against, so a run
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

/** The distinct models a task's nodes would call, in the order they appear. */
function modelsOf(flowState: TaskState): string[] {
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
 * said here -- this line is legible with the border shut, and ten tasks shut
 * is the glance the board is for. More than one cannot be said in a word, so
 * the count says so and the nodes inside carry the detail. Opening buys the
 * answer, exactly as it does for a handoff arrow.
 */
function describeWhen(flowState: TaskState): string {
  const models = modelsOf(flowState)
  if (models.length === 0) return flowState.trigger
  return `${flowState.trigger} · ${models.length === 1 ? models[0] : `${models.length} models`}`
}

function buildBox(task: string, callbacks: SkinCallbacks): Box {
  let inside: HTMLElement
  const root = document.createElement("div")
  root.className = "basic-task"
  root.dataset.task = task
  // The one width, from the constant the arrows are drawn against. Written in
  // the stylesheet it was free to drift from them, and it had.
  root.style.width = `${BOX.width}px`

  const head = element("div", "basic-head", root)
  // Two things to click, so neither has to mean two things: the name selects
  // the task, exactly as a card did, and the chevron opens the box.
  const pick = element("button", "basic-pick", head)
  ;(pick as HTMLButtonElement).type = "button"
  pick.addEventListener("click", () => callbacks.onSelectTask(task))
  element("span", "basic-dot", pick)
  const name = element("span", "basic-name", pick)

  const toggle = element("button", "basic-toggle", head)
  ;(toggle as HTMLButtonElement).type = "button"
  toggle.textContent = "▾"

  return {
    root,
    toggle,
    when: element("div", "basic-when", root),
    // Under the schedule, because it is the same kind of fact -- what this
    // task is, rather than what it is doing this minute -- and above `now`,
    // because it is true whether or not anything is running.
    warn: element("div", "basic-warn", root),
    // Beside it, and the same kind of fact: what is true of this task rather
    // than what it is doing. Its own line because a card can be both -- one
    // that edits your files directly *and* one whose last edit did not take --
    // and either of those crowding the other out is the wrong trade.
    stale: element("div", "basic-stale", root),
    // Shut, this is the whole of what a task says about right now. It sits
    // above the graph because it is the answer to the question a person came
    // to the board with, and the graph is the answer to the next one.
    name,
    now: element("div", "basic-now", root),
    // Both, in order: the group is what a too-wide graph is scaled by, and it
    // has to be inside the part that scrolls when scaling has hit its floor.
    inside: (inside = element("div", "basic-inside", root)),
    steps: element("div", "basic-steps-group", inside),
    said: element("p", "basic-said", root),
    tools: element("ul", "basic-tools", root),
    tally: element("div", "basic-tally", root),
  }
}

/**
 * What a task is doing at this moment, in one line.
 *
 * Shut, a border used to say only its name, its schedule and a tally of
 * nights past -- and the space where its graph would be sat blank, hidden
 * rather than removed so the border kept one height. That blank was the
 * largest area on the board and it answered nothing.
 *
 * Running, this is where the run is: which step, and how many model calls it
 * has spent there.
 *
 * **Not running, it says so in words rather than going blank.** It used to go
 * blank, on the reasoning that a card with nothing to report should take no
 * room -- which left the state that matters most, a task somebody stopped,
 * with nothing on screen at all. Ten quiet cards and one stopped one looked
 * like eleven quiet cards, and the difference is the whole reason to open the
 * board. The colour band beside it carries the same fact from further away;
 * this is the half that says which quiet it is.
 */
function describeNow(flowState: TaskState): string {
  if (flowState.status === "error") return "stopped"
  if (flowState.status === "paused") return "paused"
  if (flowState.status !== "running") return "waiting for its next turn"
  const parts = [flowState.currentNode ?? "starting"]
  if (flowState.turn > 1) parts.push(`turn ${flowState.turn}`)
  return parts.join(" · ")
}


/**
 * What this task can do that the morning cannot take back.
 *
 * A run works in a private copy and lands the night as one change to accept
 * or discard, and that is what makes a step that edits files unremarkable --
 * it is the whole promise of the thing. When the folder is not a repository
 * there is no copy to make: the run edits the folder itself, and the morning
 * has nothing to hand back. Neither half of that is worth a word on its own,
 * and together they are the one fact on a board of healthy-looking cards a
 * reader must not have to open anything to find.
 *
 * Said in plain words rather than the design documents' "hands": a person
 * meeting this board has read neither, and a screen is not a glossary.
 *
 * A copy the daemon could not read arrives here as no copy at all, so a task
 * whose git has broken is warned about too. That is the direction to be wrong
 * in -- it names a folder that really is unprotected until somebody looks.
 */
function describeRisk(flowState: TaskState): string {
  if (flowState.tracked) return ""
  if (!flowState.shape.nodes.some((node) => node.tools.length > 0)) return ""
  return "edits your files directly — no undo"
}

/**
 * That the card on disk is not what is running, in one line.
 *
 * Only a prompt is really re-read before a run. A schedule, a folder or an
 * `enabled:` reaches a trigger that was built when the daemon started, so the
 * daemon refuses to half-adopt the edit -- and said so only in its own log,
 * where a person who saved the file in an editor was never going to see it. A
 * card edited at noon kept its old schedule all day and the board agreed with
 * it.
 *
 * Said as what the reader must *do*, not as what the daemon declined to do:
 * the sentence they need is the next action, and the daemon's own words are on
 * the tooltip for whoever wants the rest.
 */
function describeStale(flowState: TaskState): string {
  return flowState.stale ? "edited — restart the daemon for it to take" : ""
}

/**
 * The graph inside a border, drawn once: it moves only when a file does.
 *
 * **Drawn on a shut border, not only an open one.** That is what makes the
 * board worth being a canvas: the work is readable at a glance, and a handoff
 * arrow between two borders lands beside the steps it leaves from. It costs
 * nothing to hold still, because what a task walks is structure -- it changes
 * when a file does, never between one frame and the next.
 *
 * A task of one step draws that step. It drew nothing while the steps were
 * hidden until asked for, when a lone pill named `work` was noise somebody
 * had opened a border to find; with every other task showing its steps
 * unasked, the same blank reads as broken instead.
 */
function fillInside(box: Box, flowState: TaskState): void {
  const leaves = new Set(exits(flowState.shape))
  // Only when they differ. A task on one model has already said so on the
  // header, and repeating it four times would be noise for one answer.
  const differ = modelsOf(flowState).length > 1
  const handsOff = flowState.then.length > 0

  // Built first and measured, then placed: how wide a step is drawn depends on
  // its label and on whether it carries a model or a pair of hands, and the
  // layout cannot rank what it cannot size. Off-screen rather than hidden --
  // `display: none` has no width to read.
  const pills = new Map<string, HTMLElement>()
  for (const spec of flowState.shape.nodes) {
    const pill = document.createElement("span")
    pill.className = "basic-node"
    pill.dataset.node = spec.id
    pill.dataset.type = spec.type
    // Where a handoff leaves from, once you can see the steps at all.
    if (leaves.has(spec.id) && handsOff) pill.dataset.exit = "true"
    pill.append(spec.id)
    // A router has no model because it calls none, and the gap is itself
    // information: it is why branching is free.
    if (differ && spec.model) {
      element("span", "basic-node-model", pill).textContent = spec.model
    }
    // Unconditional, unlike the model above: two steps on one model say it
    // once on the header, but "this one can rewrite the project" is never
    // answered by another step having said it. Named rather than drawn: a
    // glyph would be one more thing to learn, and this is read by people who
    // have learned nothing yet. Said as what happens rather than as "hands",
    // which is the word the design documents use among themselves. Which
    // toolsets is the detail, and hangs off it.
    if (spec.tools.length > 0) {
      const hands = element("span", "basic-node-hands", pill)
      hands.textContent = "edits files"
      hands.title = spec.tools.join(", ")
    }
    pills.set(spec.id, pill)
  }

  const laid = layOutSteps(flowState.shape, (spec) => {
    const pill = pills.get(spec.id)
    // `offsetWidth` is zero where nothing lays anything out -- jsdom, and a
    // border not yet on the page. The estimate keeps the shape of the graph
    // right there rather than collapsing every step onto one point.
    const width = pill?.offsetWidth || 22 + spec.id.length * 6.5 + (spec.tools.length ? 62 : 0)
    return { width, height: pill?.offsetHeight || 24 }
  })

  const svg = document.createElementNS(SVG, "svg")
  svg.setAttribute("class", "basic-steps")
  svg.setAttribute("width", String(laid.width))
  svg.setAttribute("height", String(laid.height))
  for (const edge of laid.edges) {
    const line = document.createElementNS(SVG, "path")
    line.setAttribute("class", "basic-step-wire")
    line.setAttribute("d", through(edge.points))
    svg.append(line)
    const last = edge.points[edge.points.length - 1]
    const before = edge.points[edge.points.length - 2] ?? last
    svg.append(head(last, before))
    if (edge.label && edge.at) {
      const word = document.createElementNS(SVG, "text")
      word.setAttribute("class", "basic-step-word")
      word.setAttribute("x", String(edge.at.x))
      word.setAttribute("y", String(edge.at.y))
      word.textContent = edge.label
      svg.append(word)
    }
  }

  for (const step of laid.steps) {
    if (step.stop) {
      const stop = document.createElementNS(SVG, "circle")
      stop.setAttribute("class", "basic-step-stop")
      stop.setAttribute("cx", String(step.x))
      stop.setAttribute("cy", String(step.y))
      stop.setAttribute("r", "4")
      // Where a run can end. Its own mark per arm, because two different ways
      // of ending are two different facts and must not collapse into one.
      stop.append(title("the run ends here"))
      svg.append(stop)
      continue
    }
    const pill = pills.get(step.id)
    if (pill === undefined) continue
    // Its own top-left, worked out from the centre dagre answered with, rather
    // than the centre plus a `translate(-50%, -50%)`. Layout ignores a
    // transform, so a pill placed that way had a *layout* box reaching half its
    // own width past where it was drawn -- and the well went on scrolling for
    // room nothing occupied, clipping the last step in every branching graph.
    pill.style.left = `${step.x - step.width / 2}px`
    pill.style.top = `${step.y - step.height / 2}px`
    if (step.ends) pill.dataset.ends = "true"
  }

  // A graph wider than the border it lives in is shrunk to fit rather than
  // scrolled out of sight: a step you have to go looking for is a step you do
  // not know is there, and the whole point of drawing this unasked is that it
  // is read at a glance. There is a floor -- past it the type stops being type
  // -- and below that the border scrolls, which is why the overflow rule stays.
  // Measured, not guessed from `BOX.width`: the graph sits in a well with its
  // own padding and border, inside a border with its own padding, and a
  // constant here went stale the moment the well was added. `clientWidth`
  // counts the padding, so it is taken off -- that twenty pixels is exactly
  // what was clipping the last step of every branching graph. The fallback is
  // for a border not yet laid out, and for jsdom.
  const pad = getComputedStyle(box.inside)
  const room =
    box.inside.clientWidth - (parseFloat(pad.paddingLeft) || 0) - (parseFloat(pad.paddingRight) || 0) ||
    BOX.width - 54
  const shrink = laid.width > room ? Math.max(0.66, room / laid.width) : 1
  box.inside.style.height = `${Math.ceil(laid.height * shrink)}px`
  // The **scaled** size, not the laid-out one. A transform changes what is
  // painted and not the box it is painted in, so a group left at its full
  // width goes on asking the border to scroll for room that is no longer used
  // -- a scrollbar under a graph that is wholly visible.
  box.steps.style.width = `${Math.ceil(laid.width * shrink)}px`
  box.steps.style.height = `${Math.ceil(laid.height * shrink)}px`
  box.steps.style.transform = shrink === 1 ? "" : `scale(${shrink})`
  box.steps.replaceChildren(svg, ...pills.values())
  box.inside.replaceChildren(box.steps)
}

/** A path through dagre's points for an edge. */
function through(points: { x: number; y: number }[]): string {
  return points.map((at, index) => `${index ? "L" : "M"}${at.x} ${at.y}`).join(" ")
}

/** The arrowhead, pointed the way the line arrives. */
function head(at: { x: number; y: number }, from: { x: number; y: number }): SVGElement {
  const turn = (Math.atan2(at.y - from.y, at.x - from.x) * 180) / Math.PI
  const tip = document.createElementNS(SVG, "path")
  tip.setAttribute("class", "basic-step-tip")
  // Bigger than it was: at five pixels the head vanished before the line did,
  // and the head is what says which way a run goes.
  tip.setAttribute("d", "M0 0 L-7 3.4 L-7 -3.4 Z")
  tip.setAttribute("transform", `translate(${at.x} ${at.y}) rotate(${turn})`)
  return tip
}

function title(said: string): SVGElement {
  const node = document.createElementNS(SVG, "title")
  node.textContent = said
  return node
}

/** What moves: which node is lit, and what the task has been saying. */
function paint(box: Box, flowState: TaskState, open: boolean): void {
  // The name on the card, not the key it is filed under: that carries the
  // project as well, which is the board's business and not the reader's.
  box.name.textContent = flowState.name
  box.root.dataset.status = flowState.status
  box.root.dataset.open = String(open)
  box.toggle.textContent = open ? "▾" : "▸"
  box.toggle.setAttribute("aria-expanded", String(open))
  box.when.textContent = describeWhen(flowState)
  box.warn.textContent = describeRisk(flowState)
  box.stale.textContent = describeStale(flowState)
  // The daemon's own sentence, which is long and exact where the line is short:
  // the summary is what a scan of the board needs, and this is what the person
  // who just saved the file needs.
  box.stale.title = flowState.stale
  box.now.textContent = describeNow(flowState)

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
      item.dataset.error = String(call.failed)
      // The subject and not the result: this row is one line of a card whose
      // height must not move, and what a tool answered can be long. The
      // drawer is where a reader goes for that.
      item.textContent = call.subject ? `${call.name} ${call.subject}` : call.name
      item.title = call.result || call.name
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
    const height = boxes.get(one.task)?.root.offsetHeight || BOX.height
    heights[one.task] = height
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
  const at = new Map(placed.map((one) => [one.task, one]))
  const lastRow = placed.reduce((low, one) => Math.max(low, one.row), 0)
  const lines: SVGElement[] = []

  for (const [task, flowState] of Object.entries(stage.tasks)) {
    const from = at.get(task)
    if (from === undefined) continue
    for (const arrow of flowState.then) {
      // `then:` names a task in the sender's own project, which is the only
      // place a handoff can reach -- so the key is built from that project.
      const to =
        arrow.to === null
          ? undefined
          : at.get(keyOfTask(flowState.project, arrow.to))
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
      // crosses a border. A bare line says two tasks are related; it does not
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
 * arrows are measured off those heights. Left out, a task that starts running
 * grows and every arrow keeps the geometry of the board before it did.
 */
function wiringKey(stage: StageState, open: (task: string, at: TaskState) => boolean): string {
  return Object.entries(stage.tasks)
    .map(
      ([task, flowState]) =>
        // Open, and every line that appears and disappears under the header:
        // all of them change a border's height, and the rows and the arrows
        // are measured off those heights. Left out, a card that grows a line
        // keeps the geometry of the board before it had one.
        `${task}>${flowState.then.map((a) => a.to).join(",")}${open(task, flowState) ? "+" : "-"}` +
        `${describeRisk(flowState) ? "r" : ""}${describeStale(flowState) ? "s" : ""}`,
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

    // The whole board, small, in a corner -- and a rectangle for the part of it
    // the window is showing. Sits outside the board, because it must not be
    // panned or scaled along with what it is describing.
    const map = element("div", "basic-minimap", viewport)
    const seen = element("div", "basic-seen", map)
    // What the minimap is drawn at, kept from the last relayout so `show` can
    // place the rectangle without measuring the board again on every frame.
    let mapped = { zoom: 1, width: 0, height: 0 }

    const boxes = new Map<string, Box>()
    const painted = new Map<string, TaskState>()
    // Only tasks the reader has touched. Everything else follows the rule
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

    map.addEventListener("pointerdown", (event) => {
      event.stopPropagation()
      const go = (to: PointerEvent) => {
        const box = map.getBoundingClientRect()
        chosen = centreOn(
          where(),
          { x: (to.clientX - box.left) / mapped.zoom, y: (to.clientY - box.top) / mapped.zoom },
          { width: viewport.clientWidth, height: viewport.clientHeight },
        )
        show()
      }
      go(event)
      map.setPointerCapture(event.pointerId)
      const done = () => {
        map.removeEventListener("pointermove", go)
        map.removeEventListener("pointerup", done)
      }
      map.addEventListener("pointermove", go)
      map.addEventListener("pointerup", done)
    })

    /**
     * Dragging and scaling the board, which `d3-zoom` owns.
     *
     * It was written here, in pointer events, and it worked for a mouse. What
     * it did not have is what a reader on a laptop reaches for first: a
     * trackpad pinch, two fingers on a touchscreen, and the double-tap and
     * keyboard paths that come with them. Those are not a few more lines; they
     * are the reason this library exists, and every one of them is now free.
     *
     * poieo keeps the `View` -- a fit is still poieo's arithmetic, and the
     * minimap still centres on a point -- and hands over only *how a hand
     * moves it*. `settling` is what keeps the two in step: pushing poieo's own
     * view into d3 fires the same event a drag does, and without the guard the
     * board would count its own fit as the reader having chosen one.
     */
    let settling = false
    const zoomer = d3zoom<HTMLDivElement, unknown>()
      .scaleExtent([ZOOM.min, ZOOM.max])
      // A box's own controls are buttons, and a press on one is a click on the
      // box rather than a grab of the board behind it.
      .filter((event: Event) => {
        if (!grabbable(event)) return false
        if (event.type === "wheel") return true
        return !(event as MouseEvent).button
      })
      .on("start", () => {
        viewport.dataset.grabbing = "true"
      })
      .on("end", () => {
        viewport.dataset.grabbing = "false"
      })
      .on("zoom", (event: D3ZoomEvent<HTMLDivElement, unknown>) => {
        const view = { x: event.transform.x, y: event.transform.y, zoom: event.transform.k }
        if (!settling) chosen = view
        draw(view)
      })

    const held = select(viewport as HTMLDivElement)
    held.call(zoomer)
    // d3 zooms in on a double click; here that gesture is the way back to the
    // whole board, which is handled below.
    held.on("dblclick.zoom", null)

    // The way back. A board a reader has lost themselves in is otherwise only
    // recoverable by reloading the page.
    viewport.addEventListener("dblclick", (event) => {
      if (!grabbable(event)) return
      chosen = null
      show()
    })

    /**
     * Shut until somebody opens it, and open until they shut it again.
     *
     * A running task used to open itself, which is how the blank space under
     * a shut border came to be: opening and shutting on every run meant every
     * border grew and shrank all day and every arrow moved with it, so the
     * room had to stay reserved whether or not anything was in it.
     *
     * The `now` line answers what the auto-open was for -- which step, how
     * many turns -- without the border changing size. So the size changes
     * only when a person asks, the room is given back when it is not wanted,
     * and the board holds still while it is being read.
     */
    const isOpen = (task: string, _state: TaskState): boolean =>
      byHand.get(task) ?? false

    function relayout(stage: StageState): void {
      const tasks = Object.keys(stage.tasks)
      const handoffs: Record<string, string[]> = {}
      for (const [task, flowState] of Object.entries(stage.tasks)) {
        // Keyed the way the board is: `then:` names a task in the sender's
        // own project, which is the only place a handoff can reach.
        handoffs[task] = flowState.then
          .map((arrow) => arrow.to)
          .filter((to): to is string => to !== null)
          .map((to) => keyOfTask(flowState.project, to))
      }
      // How many independent tasks stand across before wrapping. Read off the
      // window rather than fixed: a grid that runs off the side of a laptop is
      // the column problem again, one axis over. The gap is added back before
      // dividing because the last box in a row has no gap after it -- without
      // that, three boxes that fit are laid out two and one.
      const across = Math.max(1, Math.floor((viewport.clientWidth + BOX.gapX) / (BOX.width + BOX.gapX)))
      const placed = place(tasks, handoffs, across)
      const rows = measure(placed, boxes)
      for (const one of placed) {
        const box = boxes.get(one.task)
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
      drawMap(placed, rows)
      show()
    }

    /** The board again, small enough to sit in a corner: one speck per task. */
    function drawMap(placed: Placed[], rows: Frame): void {
      mapped = minimap(
        { width: board.offsetWidth, height: board.offsetHeight },
        { width: MAP.width, height: MAP.height },
      )
      map.style.width = `${mapped.width}px`
      map.style.height = `${mapped.height}px`

      const specks = placed.map((one) => {
        const spot = corner(one, rows)
        const speck = document.createElement("div")
        speck.className = "basic-speck"
        // Not `data-task`: that already means "a border on the board", and one
        // selector answering with two different kinds of thing is a trap.
        speck.dataset.speck = one.task
        speck.style.left = `${spot.x * mapped.zoom}px`
        speck.style.top = `${spot.y * mapped.zoom}px`
        speck.style.width = `${BOX.width * mapped.zoom}px`
        speck.style.height = `${(rows.heights[one.task] ?? BOX.height) * mapped.zoom}px`
        return speck
      })
      map.replaceChildren(seen, ...specks)
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

    /** Put a view on screen, and say where the window is looking. */
    function draw(view: View): void {
      board.style.transform = `translate(${view.x}px, ${view.y}px) scale(${view.zoom})`

      const window = { width: viewport.clientWidth, height: viewport.clientHeight }
      const patch = looking(view, window, {
        zoom: mapped.zoom,
        board: { width: board.offsetWidth, height: board.offsetHeight },
      })
      seen.style.left = `${patch.x}px`
      seen.style.top = `${patch.y}px`
      seen.style.width = `${patch.width}px`
      seen.style.height = `${patch.height}px`
      // Only worth the corner it takes when there is board off the screen. A
      // minimap of something wholly visible is a second, smaller copy of it.
      const all = patch.width >= mapped.width - 1 && patch.height >= mapped.height - 1
      map.dataset.needed = String(!all && mapped.width > 0)
    }

    /**
     * The view poieo wants, handed to d3 and then drawn.
     *
     * Through `zoomer.transform` rather than by setting the style directly, so
     * that d3's own idea of where the board is never drifts from where it is:
     * a fit written straight to the transform would be forgotten the moment a
     * hand touched the board, and it would jump back.
     */
    function show(): void {
      const view = where()
      settling = true
      held.call(zoomer.transform, zoomIdentity.translate(view.x, view.y).scale(view.zoom))
      settling = false
    }

    return {
      update(stage: StageState) {
        let moved = false
        for (const [task, flowState] of changedTasks(stage.tasks, painted)) {
          let box = boxes.get(task)
          if (box === undefined) {
            box = buildBox(task, callbacks)
            box.toggle.addEventListener("click", () => {
              byHand.set(task, !isOpen(task, painted.get(task) ?? flowState))
              const now = painted.get(task)
              if (now !== undefined) paint(box!, now, isOpen(task, now))
              if (last !== null) relayout(last)
            })
            boxes.set(task, box)
            board.append(box.root)
            moved = true
          }
          fillInside(box, flowState)
          paint(box, flowState, isOpen(task, flowState))
        }
        for (const [task, box] of boxes) {
          if (!(task in stage.tasks)) {
            box.root.remove()
            boxes.delete(task)
            byHand.delete(task)
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
