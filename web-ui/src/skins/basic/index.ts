/**
 * The plain view: the work as a graph, with one noun on screen.
 *
 * Each task carries a vertical graph with a visible start and endings.
 * Opening the border adds the live text and tool calls;
 * View steps opens the spatial graph at an independent reading size.
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
import { stepName } from "./steps"
import { drawCardSteps } from "./card"
import { createGraphDialog } from "./graph"
import { drawConnections, taskConnections } from "./connections"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import { keyOfTask } from "../../state/stage"
import type { StageState, TaskState } from "../../state/stage"
import {
  BOX, ZOOM, centreOn, corner, fit, looking, minimap,
  place, readingView, typeScale,
} from "../wiring"
import type { Frame, Placed, View } from "../wiring"
import { shortTime } from "../../when"
import "./basic.css"

const SVG = "http://www.w3.org/2000/svg"

/** How much corner the minimap may take. */
const MAP = { width: 200, height: 140 }

interface Box {
  structure: string
  root: HTMLElement
  name: HTMLElement
  toggle: HTMLElement
  when: HTMLElement
  now: HTMLElement
  graphHead: HTMLElement
  graphCount: HTMLElement
  viewSteps: HTMLElement
  inside: HTMLElement
  steps: HTMLElement
  said: HTMLElement
  tools: HTMLElement
  tally: HTMLElement
  warn: HTMLElement
  stale: HTMLElement
  apply: HTMLElement
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
function describeRecent(taskState: TaskState): string {
  const recent = taskState.recent
  if (recent.runs === 0) return "nothing has run yet"

  const parts: string[] = []
  if (recent.succeeded) {
    // A task with no private copy has nothing to change against, so a run
    // that ran is the whole of what there is to say about it.
    const what = taskState.tracked ? "change" : "run"
    parts.push(`${recent.succeeded} ${what}${recent.succeeded === 1 ? "" : "s"}`)
  }
  if (recent.insertions || recent.deletions) {
    parts.push(`+${recent.insertions} / -${recent.deletions}`)
  }
  if (recent.failed) parts.push(`${recent.failed} failed`)

  if (parts.length > 0) return parts.join(" · ")
  const last = taskState.lastRun?.finished_at
  return last ? `quiet · last looked ${shortTime(last)}` : "quiet"
}

/** The distinct models a task's nodes would call, in the order they appear. */
function modelsOf(taskState: TaskState): string[] {
  const seen: string[] = []
  for (const node of taskState.shape.nodes) {
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
function describeWhen(taskState: TaskState): string {
  const models = modelsOf(taskState)
  if (models.length === 0) return taskState.trigger
  return `${taskState.trigger} · ${models.length === 1 ? models[0] : `${models.length} models`}`
}

function buildBox(task: string, callbacks: SkinCallbacks, onView: (opener: HTMLElement) => void): Box {
  let inside: HTMLElement
  let graphHead: HTMLElement
  const root = document.createElement("div")
  root.className = "basic-task"
  root.dataset.task = task
  // Independent cards stay compact. Connected graphs may need a wider border.
  root.style.width = `${BOX.width}px`

  const head = element("div", "basic-head", root)
  // Two things to click, so neither has to mean two things: the name selects
  // the task, exactly as a card did, and the chevron opens the box.
  const pick = element("button", "basic-pick", head)
  ;(pick as HTMLButtonElement).type = "button"
  pick.addEventListener("click", () => callbacks.onSelectTask(task, pick))
  element("span", "basic-dot", pick)
  const name = element("span", "basic-name", pick)

  const toggle = element("button", "basic-toggle", head)
  ;(toggle as HTMLButtonElement).type = "button"
  toggle.textContent = "▾"

  const box: Box = {
    structure: "",
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
    // The same kind of fact again -- what this task may do to the project
    // without anyone deciding -- and worth its own line for the same reason
    // the warning above has one: it is the one thing on a board of quiet
    // cards a reader must not have to open anything to find.
    apply: element("div", "basic-apply", root),
    // Shut, this is the whole of what a task says about right now. It sits
    // above the graph because it is the answer to the question a person came
    // to the board with, and the graph is the answer to the next one.
    name,
    now: element("div", "basic-now", root),
    graphHead: (graphHead = element("div", "basic-graph-head", root)),
    graphCount: element("span", "", graphHead),
    viewSteps: element("button", "basic-view-steps", graphHead),
    inside: (inside = element("div", "basic-inside", root)),
    steps: element("div", "basic-steps-group", inside),
    said: element("p", "basic-said", root),
    tools: element("ul", "basic-tools", root),
    tally: element("div", "basic-tally", root),
  }
  box.viewSteps.textContent = "View steps"
  box.viewSteps.setAttribute("type", "button")
  box.viewSteps.addEventListener("click", () => onView(box.viewSteps))
  return box
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
function describeNow(taskState: TaskState): string {
  if (taskState.status === "error") return "stopped"
  // Two kinds of stopped, one band. A pause is runtime state and a button
  // undoes it; a card switched off in its file needs an edit and a restart,
  // and telling a reader to press resume would send them somewhere that
  // refuses them.
  if (taskState.status === "paused") {
    if (!taskState.enabled) return "switched off in its card"
    // The daemon's reason when it has one: "paused" alone reads as a button
    // somebody pressed, and a task that parked itself after three failures,
    // or over a change it could not apply, is the one a reader came to find.
    return taskState.heldBecause || "paused"
  }
  if (taskState.status !== "running") return "waiting for its next turn"
  const current = taskState.shape.nodes.find(node => node.id === taskState.currentNode)
  const parts = [current ? stepName(current) : taskState.currentNode ?? "starting"]
  if (taskState.turn > 1) parts.push(`turn ${taskState.turn}`)
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
function describeRisk(taskState: TaskState): string {
  if (taskState.tracked) return ""
  if (!taskState.shape.nodes.some((node) => node.tools.length > 0)) return ""
  return "edits your files directly — no undo"
}

/**
 * That this task lands its own work, in one line -- or nothing.
 *
 * A task in review mode is the ordinary case and says nothing; the promise of
 * the board is that its changes wait. One that applies itself has been given
 * a permission to skip that wait once its checks pass, and the commands it
 * trusts are on the tooltip, for whoever wants to know what "checked" means.
 */
function describeApply(taskState: TaskState): string {
  return taskState.applies === "auto" ? "applies its checked changes itself" : ""
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
function describeStale(taskState: TaskState): string {
  return taskState.stale ? "edited — restart the daemon for it to take" : ""
}

/** Connections at card width. Structure stays put while run state changes. */
function fillInside(box: Box, taskState: TaskState, receives: boolean): boolean {
  const structure = JSON.stringify([taskState.name, taskState.shape, taskState.then, receives])
  if (box.structure === structure) return false
  box.structure = structure
  const connected = receives || taskState.then.some(way => way.to !== null)
  box.root.dataset.connected = String(connected)
  box.root.style.width = `${BOX.width}px`
  box.inside.hidden = taskState.shape.nodes.length === 0 && !connected
  box.inside.tabIndex = 0
  box.inside.setAttribute("role", "region")
  box.inside.setAttribute("aria-label", `Step connections in ${taskState.name}`)
  const width = drawCardSteps(box.steps, taskState, receives)
  if (connected) box.root.style.width = `${Math.max(BOX.width, width + 32)}px`
  return true
}

/** What moves: which node is lit, and what the task has been saying. */
function paint(box: Box, taskState: TaskState, open: boolean): void {
  // The name on the card, not the key it is filed under: that carries the
  // project as well, which is the board's business and not the reader's.
  box.name.textContent = taskState.name
  box.root.dataset.status = taskState.status
  box.root.dataset.open = String(open)
  box.toggle.textContent = open ? "▾" : "▸"
  box.toggle.setAttribute("aria-expanded", String(open))
  box.when.textContent = describeWhen(taskState)
  box.warn.textContent = describeRisk(taskState)
  box.stale.textContent = describeStale(taskState)
  // The daemon's own sentence, which is long and exact where the line is short:
  // the summary is what a scan of the board needs, and this is what the person
  // who just saved the file needs.
  box.stale.title = taskState.stale
  box.apply.textContent = describeApply(taskState)
  box.apply.title = taskState.applies === "auto" ? `checks: ${taskState.applyChecks.join(" · ")}` : ""
  box.now.textContent = describeNow(taskState)
  // The line is cut at the card's edge; the whole sentence is on the tooltip.
  box.now.title = taskState.status === "paused" ? taskState.heldBecause : ""
  const count = taskState.shape.nodes.length
  box.graphHead.hidden = count === 0
  box.graphCount.textContent = `${count} ${count === 1 ? "step" : "steps"}`
  box.viewSteps.setAttribute("aria-label", `View steps in ${taskState.name}`)

  for (const pill of box.steps.querySelectorAll<HTMLElement>("[data-node]")) {
    pill.dataset.here = String(taskState.status === "running" && pill.dataset.node === taskState.currentNode)
  }

  const thinking = !taskState.lastText && Boolean(taskState.lastThinking)
  box.said.dataset.thinking = String(thinking)
  box.said.textContent = taskState.lastText || taskState.lastThinking || ""

  box.tools.replaceChildren(
    ...taskState.recentToolCalls.map((call) => {
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
  box.tally.textContent = describeRecent(taskState)
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
      ([task, taskState]) =>
        // Open, and every line that appears and disappears under the header:
        // all of them change a border's height, and the rows and the arrows
        // are measured off those heights. Left out, a card that grows a line
        // keeps the geometry of the board before it had one.
        `${task}>${taskState.then.map((a) => a.to).join(",")}${open(task, taskState) ? "+" : "-"}` +
        `${describeRisk(taskState) ? "r" : ""}${describeStale(taskState) ? "s" : ""}${describeApply(taskState) ? "a" : ""}`,
    )
    .join("|")
}

export const basic: Skin = {
  id: "basic",
  label: "Basic",

  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle {
    const graphDialog = createGraphDialog(el)
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
    const help = element("div", "basic-move-help", viewport)
    help.textContent = "Drag to see more tasks. Double-click to fit."
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

    // Independent graphs scroll locally. Full connected graphs move with the board.
    const grabbable = (event: Event): boolean =>
      !(event.target as Element | null)?.closest('button, [data-port], .basic-connection, .basic-task[data-connected="false"] .basic-inside')

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
      chosen = fit(
        { width: board.offsetWidth, height: board.offsetHeight },
        { width: viewport.clientWidth, height: viewport.clientHeight },
        24,
        typeScale(),
      )
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
      help.textContent = taskConnections(stage).length
        ? "Click a connection to follow it. Drag to move; double-click to fit."
        : "Drag to see more tasks. Double-click to fit."
      const handoffs: Record<string, string[]> = {}
      for (const [task, taskState] of Object.entries(stage.tasks)) {
        // Keyed the way the board is: `then:` names a task in the sender's
        // own project, which is the only place a handoff can reach.
        handoffs[task] = taskState.then
          .map((arrow) => arrow.to)
          .filter((to): to is string => to !== null)
          .map((to) => keyOfTask(taskState.project, to))
      }
      // How many independent tasks stand across before wrapping. Read off the
      // window rather than fixed: a grid that runs off the side of a laptop is
      // the column problem again, one axis over. The gap is added back before
      // dividing because the last box in a row has no gap after it -- without
      // that, three boxes that fit are laid out two and one.
      const across = Math.max(1, Math.floor((viewport.clientWidth + BOX.gapX) / (BOX.width + BOX.gapX)))
      const placed = place(tasks, handoffs, across)
      const rows = measure(placed, boxes)
      const columns = Math.max(1, ...placed.map(one => one.column + 1))
      const widths = Array.from({ length: columns }, () => BOX.width)
      for (const one of placed) widths[one.column] = Math.max(widths[one.column], parseFloat(boxes.get(one.task)!.root.style.width))
      const positions = new Map(placed.map(one => [one.task, one]))
      const outer = taskConnections(stage).some(link => positions.get(link.to)!.column !== positions.get(link.from)!.column + 1)
      const lefts: number[] = []
      let left = outer ? 24 : 0
      for (const width of widths) { lefts.push(left); left += width + BOX.gapX }
      for (const one of placed) {
        const box = boxes.get(one.task)!
        box.root.style.left = `${lefts[one.column]}px`
        box.root.style.top = `${corner(one, rows).y}px`
      }
      board.style.width = `${left - BOX.gapX + (outer ? 24 : 0)}px`
      const bottom = drawConnections(svg, stage, placed, boxes, rows.bottom, follow, trace)
      board.style.height = `${bottom}px`
      trace(null)
      drawMap(placed, rows)
      show()
    }

    function trace(from: string | null, to?: string) {
      // A pointer leaving a wire after following it must not clear the Input
      // that still has keyboard focus. Hover temporarily takes precedence.
      if (from === null && to === undefined && board.contains(document.activeElement)) {
        const focused = document.activeElement!
        const connection = focused.closest<SVGElement>(".basic-connection")
        const port = focused.closest<HTMLElement>("[data-port]")
        if (connection) { from = connection.dataset.from!; to = connection.dataset.to! }
        else if (port) {
          const task = port.closest<HTMLElement>(".basic-task")!.dataset.task!
          if (port.dataset.port === "output") from = task
          else to = task
        }
      }
      const clear = from === null && to === undefined
      const linked = new Set([from, to].filter((key): key is string => Boolean(key)))
      for (const connection of svg.querySelectorAll<SVGElement>(".basic-connection")) {
        const active = (from === null || connection.dataset.from === from) && (to === undefined || connection.dataset.to === to)
        if (clear) delete connection.dataset.active
        else connection.dataset.active = String(active)
        if (active) { linked.add(connection.dataset.from!); linked.add(connection.dataset.to!) }
      }
      for (const [key, box] of boxes) {
        if (clear) delete box.root.dataset.linked
        else box.root.dataset.linked = String(linked.has(key))
      }
    }

    function follow(task: string) {
      const box = boxes.get(task)
      if (!box) return
      const current = where()
      chosen = { ...current,
        x: Math.max(16, (viewport.clientWidth - parseFloat(box.root.style.width) * current.zoom) / 2) - parseFloat(box.root.style.left) * current.zoom,
        y: 24 - parseFloat(box.root.style.top) * current.zoom,
      }
      show()
      box.steps.querySelector<HTMLElement>('[data-port="input"]')?.focus({ preventScroll: true })
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
        const root = boxes.get(one.task)!.root
        const spot = { x: parseFloat(root.style.left), y: parseFloat(root.style.top) }
        const speck = document.createElement("div")
        speck.className = "basic-speck"
        // Not `data-task`: that already means "a border on the board", and one
        // selector answering with two different kinds of thing is a trap.
        speck.dataset.speck = one.task
        speck.style.left = `${spot.x * mapped.zoom}px`
        speck.style.top = `${spot.y * mapped.zoom}px`
        speck.style.width = `${parseFloat(root.style.width) * mapped.zoom}px`
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
        readingView(
          { width: board.offsetWidth, height: board.offsetHeight },
          { width: viewport.clientWidth, height: viewport.clientHeight },
          // As far as the page's type has grown, and no further: the board
          // keeps pace with the bar and the drawer beside it.
          typeScale(),
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
      help.hidden = all || mapped.width <= 0
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
        const receiving = new Set(taskConnections(stage).map(link => link.to))
        for (const [task, taskState] of changedTasks(stage.tasks, painted)) {
          let box = boxes.get(task)
          if (box === undefined) {
            box = buildBox(task, callbacks, opener => {
              const current = last?.tasks[task]
              if (current) graphDialog.open(task, current, opener)
            })
            box.toggle.addEventListener("click", () => {
              byHand.set(task, !isOpen(task, painted.get(task) ?? taskState))
              const now = painted.get(task)
              if (now !== undefined) paint(box!, now, isOpen(task, now))
              if (last !== null) relayout(last)
            })
            const tracePort = (event: Event) => {
              const port = (event.target as Element).closest<HTMLElement>("[data-port]")
              if (port) trace(port.dataset.port === "output" ? task : null, port.dataset.port === "input" ? task : undefined)
            }
            box.root.addEventListener("focusin", tracePort)
            box.root.addEventListener("pointerover", tracePort)
            box.root.addEventListener("focusout", () => trace(null))
            box.root.addEventListener("pointerleave", () => { if (!box!.root.contains(document.activeElement)) trace(null) })
            boxes.set(task, box)
            board.append(box.root)
            moved = true
          }
          paint(box, taskState, isOpen(task, taskState))
        }
        for (const [task, box] of boxes) {
          if (!(task in stage.tasks)) {
            box.root.remove()
            boxes.delete(task)
            byHand.delete(task)
            moved = true
          }
        }
        for (const [task, box] of boxes) {
          const taskState = stage.tasks[task]
          if (fillInside(box, taskState, receiving.has(task))) {
            moved = true
            paint(box, taskState, isOpen(task, taskState))
          }
        }
        last = stage
        graphDialog.update(stage)
        const fresh = wiringKey(stage, isOpen)
        if (moved || fresh !== key) {
          key = fresh
          relayout(stage)
        }
      },

      destroy() {
        graphDialog.destroy()
        watching?.disconnect()
        boxes.clear()
        viewport.remove()
      },
    }
  },
}
