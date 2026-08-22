/**
 * The workshop: a smithy, one forge per flow.
 *
 * Drawn from shapes in code — no sprite packs, per the spec. The smith stands
 * at an anvil, lifts a hammer while a node runs and brings it down, sparks on
 * the blow. The forge behind them glows while there is work in it. Tool calls
 * hang on the wall; each run that landed puts a finished piece on the shelf.
 *
 * The room can be dragged and pinched; benches can be moved one at a time and
 * their places are remembered.
 *
 * PixiJS arrives through a dynamic import and nowhere else: it is the heaviest
 * thing that reaches the browser and it serves this one skin, so a reader who
 * stays on the ledger never pays for it.
 */

import { forgetSpots, savedSpots, saveSpot } from "./placement"
import {
  CELL,
  bounds,
  bubbleVisible,
  cellAt,
  cellOrigin,
  clampZoom,
  columnsFor,
  figurePose,
  fit,
  HAMMER,
  hammerAngle,
  lampLit,
  occupied,
  place,
  prefersReducedMotion,
  shelfCount,
  sparking,
} from "./scene"
import type { Cell } from "./scene"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import type { StageState, Worker } from "../../state/stage"
import "./atelier.css"

type Pixi = typeof import("pixi.js")

const INK = {
  floor: 0x211c17,
  floorEdge: 0x2e2820,
  wall: 0x1a1611,
  stump: 0x2e2820,
  stumpTop: 0x3a332a,
  anvil: 0x8c8378,
  anvilDark: 0x5d564d,
  forgeBack: 0x241f19,
  forgeMouth: 0x15120e,
  forgeHot: 0xd8733a,
  ember: 0xffb454,
  white: 0xfff0c0,
  shelf: 0x2e2820,
  piece: 0xa9b665,
  tool: 0x6b6257,
  toolBad: 0xd16d5a,
  skin: 0xc9b79f,
  skinDark: 0xa8977f,
  hair: 0x4a423a,
  apronIdle: 0x6f665b,
  apronWork: 0x8a6a3f,
  apronBad: 0xa8503f,
  shirt: 0x8f8578,
  shirtDark: 0x6b6257,
  leather: 0x5d564d,
  haft: 0x7a6a52,
  iron: 0x4a423a,
  ironDark: 0x3f382f,
  ironLit: 0x6b6257,
  shadow: 0x191510,
  bubble: 0x2a251e,
  text: 0xe8e2d8,
  faint: 0x9a9086,
}

/**
 * How far a pointer may travel and still count as standing still.
 *
 * A finger is not a mouse: a tap on a phone wanders further than a few pixels.
 */
const CLICK_SLOP = 14

/**
 * How long a bench must be held before it can be carried.
 *
 * Dragging is for looking around. Picking a bench up is the rarer thing, so it
 * is the one that asks for a deliberate press.
 */
const PICK_UP_MS = 380

const FREE = 0xa9b665
const TAKEN = 0xd16d5a

interface Bench {
  root: any
  paint(worker: Worker): void
  tick(elapsed: number): void
  moveTo(cell: Cell): void
  destroy(): void
}

function makeBench(PIXI: Pixi, flow: string): Bench {
  const root = new PIXI.Container()
  root.eventMode = "static"
  root.cursor = "grab"

  const layer = () => {
    const g = new PIXI.Graphics()
    root.addChild(g)
    return g
  }

  // -- the room, which never changes
  const shell = layer()
  shell
    .poly([0, -40, 132, 26, 0, 92, -132, 26])
    .fill(INK.floor)
    .stroke({ color: INK.floorEdge, width: 1 })
  shell.poly([-132, 26, -132, -46, 0, -112, 0, -40]).fill(INK.wall)
  shell.poly([132, 26, 132, -46, 0, -112, 0, -40]).fill(INK.floorEdge)
  // a forge mouth set back into the wall, not a rectangle painted on it
  shell.poly([-118, 10, -56, -22, -56, -64, -118, -34]).fill(INK.forgeBack)
  shell.poly([-110, 4, -64, -20, -64, -54, -110, -32]).fill(INK.forgeMouth)
  shell.poly([20, -56, 118, -6, 118, -28, 20, -78]).fill(INK.shelf)

  const forge = layer()
  const tools = new PIXI.Container()
  root.addChild(tools)
  const pieces = new PIXI.Container()
  root.addChild(pieces)

  // The smith is drawn before the anvil so the anvil stands in front of them.
  const figure = layer()

  const arm = new PIXI.Container()
  const hammer = new PIXI.Graphics()
  // Drawn out along +x from the shoulder, so rotating the container swings it.
  hammer.poly([0, -5, 20, -5, 20, 5, 0, 5]).fill(INK.skinDark)
  hammer.poly([16, -3, 44, -3, 44, 3, 16, 3]).fill(INK.haft)
  hammer.poly([40, -11, 56, -11, 56, 11, 40, 11]).fill(INK.iron)
  hammer.poly([40, -11, 56, -11, 56, -6, 40, -6]).fill(INK.ironLit)
  arm.addChild(hammer)
  root.addChild(arm)

  const anvil = layer()
  anvil.ellipse(40, 64, 32, 9).fill(INK.shadow)
  anvil.poly([16, 24, 60, 24, 54, 62, 22, 62]).fill(INK.stump)
  anvil.poly([16, 24, 60, 24, 57, 32, 19, 32]).fill(INK.stumpTop)
  anvil.rect(30, 10, 16, 15).fill(INK.iron)
  anvil.poly([8, -4, 52, -4, 60, 2, 52, 11, 8, 11]).fill(INK.anvilDark)
  anvil.poly([8, -4, 52, -4, 48, -8, 12, -8]).fill(INK.anvil)
  anvil.poly([52, -6, 78, 0, 52, 8]).fill(INK.anvilDark)

  const work = layer()
  const sparks = layer()

  const bubble = new PIXI.Container()
  root.addChild(bubble)

  const name = new PIXI.Text({
    text: flow,
    style: { fill: INK.text, fontSize: 14, fontFamily: "system-ui, sans-serif" },
  })
  name.anchor.set(0.5, 0)
  name.position.set(0, 98)
  root.addChild(name)

  const doing = new PIXI.Text({
    text: "",
    style: { fill: INK.faint, fontSize: 11, fontFamily: "system-ui, sans-serif" },
  })
  doing.anchor.set(0.5, 0)
  doing.position.set(0, 116)
  root.addChild(doing)

  let current: Worker | null = null

  return {
    root,

    paint(worker: Worker) {
      current = worker
      const pose = figurePose(worker)
      const hot = lampLit(worker)
      const apron =
        pose === "working" ? INK.apronWork : pose === "alarmed" ? INK.apronBad : INK.apronIdle
      const x = pose === "working" ? 4 : 0 // leans in to strike

      forge.clear()
      if (hot) {
        forge.poly([-106, 1, -68, -19, -68, -49, -106, -31]).fill(INK.forgeHot)
        forge.poly([-100, -3, -74, -17, -74, -41, -100, -29]).fill(INK.ember)
      }
      if (worker.status === "error") {
        forge.circle(-87, -25, 24).stroke({ color: INK.apronBad, width: 2 })
      }

      // -- the smith, in profile facing the anvil
      figure.clear()
      figure.ellipse(-34 + x, 62, 24, 8).fill(INK.shadow)
      // a stance: back leg planted, front leg forward
      figure.poly([-54 + x, 26, -42 + x, 26, -40 + x, 62, -52 + x, 62]).fill(INK.iron)
      figure.poly([-38 + x, 26, -26 + x, 26, -20 + x, 60, -32 + x, 60]).fill(INK.ironDark)
      // torso, broad at the shoulders and turned toward the work
      figure.poly([-58 + x, -14, -26 + x, -18, -22 + x, 30, -54 + x, 30]).fill(INK.shirt)
      figure.poly([-58 + x, -14, -46 + x, -16, -44 + x, 30, -54 + x, 30]).fill(INK.shirtDark)
      // the apron hangs over the front rather than being cut out of it
      figure.poly([-52 + x, 0, -22 + x, -3, -20 + x, 36, -50 + x, 36]).fill(apron)
      figure.poly([-44 + x, -14, -39 + x, -15, -35 + x, 2, -40 + x, 2]).fill(INK.leather)

      if (hot) {
        // the forward arm, holding the work down with tongs
        figure.poly([-30 + x, -4, -8 + x, 2, -10 + x, 10, -32 + x, 6]).fill(INK.skin)
        figure.poly([-12 + x, 1, 20, -9, 22, -5, -10 + x, 6]).fill(INK.forgeBack)
        figure.poly([-12 + x, 6, 20, -4, 22, 0, -10 + x, 11]).fill(INK.forgeBack)
      } else {
        figure.poly([-32 + x, -2, -22 + x, 0, -20 + x, 20, -30 + x, 20]).fill(INK.skin)
      }

      // head in profile: brow, nose, beard, and a cap with a brim
      figure.circle(-42 + x, -30, 12).fill(INK.skin)
      figure.poly([-31 + x, -33, -25 + x, -29, -31 + x, -26]).fill(INK.skin)
      figure.poly([-52 + x, -26, -30 + x, -24, -34 + x, -8, -48 + x, -12]).fill(INK.hair)
      figure.poly([-55 + x, -33, -29 + x, -36, -32 + x, -46, -51 + x, -46]).fill(INK.hair)
      figure.poly([-56 + x, -33, -26 + x, -36, -26 + x, -31, -56 + x, -29]).fill(INK.iron)

      arm.position.set(-30 + x, -14)
      arm.visible = pose !== "alarmed"

      // -- the work itself, glowing on the anvil
      work.clear()
      if (hot) {
        work.roundRect(14, -15, 32, 8, 3).fill(INK.ember)
        work.roundRect(18, -14, 22, 6, 2).fill(INK.white)
      }

      // -- the wall of tools: the most recent calls, newest nearest the bench
      tools.removeChildren().forEach((child: any) => child.destroy())
      worker.recentToolCalls.slice(0, 4).forEach((call, index) => {
        const mark = new PIXI.Graphics()
        mark
          .roundRect(60 + index * 20, -86 + index * 10, 13, 22, 3)
          .fill(call.error ? INK.toolBad : INK.tool)
        tools.addChild(mark)
        if (index === 0) {
          const label = new PIXI.Text({
            text: call.name,
            style: { fill: INK.faint, fontSize: 10, fontFamily: "system-ui, sans-serif" },
          })
          label.anchor.set(0, 1)
          label.position.set(42, -92)
          tools.addChild(label)
        }
      })

      // -- the shelf: one piece per run that landed
      pieces.removeChildren().forEach((child: any) => child.destroy())
      const stacked = Math.min(shelfCount(worker), 6)
      for (let i = 0; i < stacked; i += 1) {
        const piece = new PIXI.Graphics()
        piece.roundRect(28 + i * 15, -68 + i * 7, 10, 10, 2).fill(INK.piece)
        pieces.addChild(piece)
      }

      // -- what it is thinking, if anything
      bubble.removeChildren().forEach((child: any) => child.destroy())
      bubble.visible = bubbleVisible(worker)
      if (bubble.visible) {
        const pad = new PIXI.Graphics()
        pad.roundRect(-46, -136, 172, 32, 9).fill(INK.bubble)
        pad.circle(-38, -98, 5).fill(INK.bubble)
        pad.circle(-46, -86, 3).fill(INK.bubble)
        bubble.addChild(pad)

        const said = new PIXI.Text({
          text: worker.lastThinking.slice(0, 36),
          style: { fill: INK.faint, fontSize: 10, fontFamily: "system-ui, sans-serif" },
        })
        said.position.set(-38, -128)
        bubble.addChild(said)
      }

      doing.text = worker.currentNode
        ? `${worker.currentNode}${worker.turn > 0 ? ` · turn ${worker.turn}` : ""}`
        : "idle"
    },

    tick(elapsed: number) {
      if (!current) return
      arm.rotation =
        figurePose(current) === "working" ? hammerAngle(elapsed) : HAMMER.resting

      sparks.clear()
      if (sparking(current, elapsed)) {
        for (let i = 0; i < 6; i += 1) {
          const away = (i - 2.5) * 9
          sparks.circle(30 + away, -12 - Math.abs(away) * 0.35, 2).fill(INK.ember)
        }
      }
    },

    moveTo(cell: Cell) {
      const at = cellOrigin(cell)
      root.position.set(at.x, at.y)
    },

    destroy() {
      root.removeAllListeners?.()
      root.destroy({ children: true })
    },
  }
}

async function build(PIXI: Pixi, el: HTMLElement, callbacks: SkinCallbacks) {
  const app = new PIXI.Application()
  await app.init({ background: 0x14120f, antialias: true, resizeTo: el })
  const canvas: HTMLCanvasElement = app.canvas
  canvas.classList.add("atelier-canvas")
  el.append(canvas)

  const room = new PIXI.Container()
  app.stage.addChild(room)
  app.stage.eventMode = "static"
  app.stage.hitArea = app.screen

  // A stray drag can put a bench somewhere useless, and the arrangement is
  // remembered -- so there has to be a way back.
  const tidy = document.createElement("button")
  tidy.type = "button"
  tidy.className = "atelier-tidy"
  tidy.textContent = "tidy up"
  tidy.hidden = true
  el.append(tidy)

  const benches = new Map<string, Bench>()
  let spots: Record<string, Cell> = {}

  // Shows which square a carried bench would land on, and whether it may.
  const ghost = new PIXI.Graphics()
  ghost.visible = false
  room.addChild(ghost)
  let arrangedFor = ""
  /** The reader has moved or zoomed something; stop arranging it for them. */
  let handled = false

  let elapsed = 0
  if (!prefersReducedMotion()) {
    app.ticker.add((ticker: any) => {
      elapsed += ticker.deltaMS
      for (const bench of benches.values()) bench.tick(elapsed)
    })
  }

  // -- carrying one bench ----------------------------------------------------
  let dragging: { flow: string; dx: number; dy: number } | null = null
  /** A press waiting to become a carry, or to turn out to be a tap. */
  let press: { flow: string; timer: number; x: number; y: number } | null = null

  const dropPress = () => {
    if (!press) return
    window.clearTimeout(press.timer)
    press = null
  }

  const showGhost = (cell: Cell, blocked: boolean) => {
    const at = cellOrigin(cell)
    ghost.clear()
    ghost
      .roundRect(
        at.x - CELL.width / 2 + 10,
        at.y - CELL.height / 2 + 10,
        CELL.width - 20,
        CELL.height - 20,
        12,
      )
      .stroke({ color: blocked ? TAKEN : FREE, width: 3 })
    ghost.visible = true
  }

  app.stage.on("pointermove", (event: any) => {
    if (!dragging) return
    const bench = benches.get(dragging.flow)
    if (!bench) return
    const point = event.getLocalPosition(room)
    bench.root.position.set(point.x - dragging.dx, point.y - dragging.dy)

    const cell = cellAt(bench.root.x, bench.root.y)
    showGhost(cell, occupied(spots, cell, dragging.flow))
  })

  const drop = () => {
    if (!dragging) return
    const { flow } = dragging
    const bench = benches.get(flow)
    dragging = null
    ghost.visible = false
    if (!bench) return

    bench.root.cursor = "grab"
    bench.root.alpha = 1

    // Benches stand on squares, one to a square. A square that is taken
    // refuses the bench rather than stacking two smiths in one room.
    const cell = cellAt(bench.root.x, bench.root.y)
    if (occupied(spots, cell, flow)) {
      bench.moveTo(spots[flow])
      return
    }
    spots[flow] = cell
    saveSpot(flow, cell)
    handled = true
    bench.moveTo(cell)
  }
  app.stage.on("pointerup", drop)
  app.stage.on("pointerupoutside", drop)

  // -- moving and scaling the whole room -------------------------------------
  const pointers = new Map<number, { x: number; y: number }>()
  let panning: { x: number; y: number } | null = null
  let pressedAt: { x: number; y: number } | null = null
  let pinch: { gap: number; scale: number; x: number; y: number } | null = null

  const local = (event: PointerEvent | WheelEvent) => {
    const box = canvas.getBoundingClientRect()
    return { x: event.clientX - box.left, y: event.clientY - box.top }
  }

  /** Scale about a point, so whatever is under the fingers stays under them. */
  const zoomAbout = (scale: number, x: number, y: number) => {
    const next = clampZoom(scale)
    const before = room.scale.x
    const worldX = (x - room.x) / before
    const worldY = (y - room.y) / before
    room.scale.set(next)
    room.position.set(x - worldX * next, y - worldY * next)
    handled = true
  }

  const spread = () => {
    const [a, b] = [...pointers.values()]
    return { gap: Math.hypot(a.x - b.x, a.y - b.y), x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
  }

  canvas.addEventListener("pointerdown", (event) => {
    pointers.set(event.pointerId, local(event))
    if (pointers.size === 2) {
      // Two fingers are for the room, never for a bench.
      dragging = null
      panning = null
      const { gap, x, y } = spread()
      pinch = { gap, scale: room.scale.x, x, y }
    } else if (pointers.size === 1 && !dragging) {
      const at = local(event)
      panning = { x: at.x - room.x, y: at.y - room.y }
      pressedAt = at
    }
  })

  canvas.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return
    pointers.set(event.pointerId, local(event))

    if (pinch && pointers.size >= 2) {
      dropPress()
      const { gap, x, y } = spread()
      if (pinch.gap > 0) zoomAbout(pinch.scale * (gap / pinch.gap), x, y)
      return
    }

    // Moving before the bench has been held long enough means the reader is
    // looking around, not rearranging.
    if (press && pressedAt) {
      const at = local(event)
      if (Math.abs(at.x - pressedAt.x) > CLICK_SLOP || Math.abs(at.y - pressedAt.y) > CLICK_SLOP) {
        dropPress()
      }
    }
    if (panning && !dragging) {
      const at = local(event)
      room.position.set(at.x - panning.x, at.y - panning.y)
      handled = true
    }
  })

  const release = (event: PointerEvent, lifted: boolean) => {
    // Letting go before the bench came up is a tap, and a tap opens it. A
    // cancelled gesture or a pointer leaving the canvas is neither.
    if (press) {
      const flow = press.flow
      dropPress()
      if (lifted) callbacks.onSelectWorker(flow)
    }
    pointers.delete(event.pointerId)
    if (pointers.size < 2) pinch = null
    if (pointers.size === 0) {
      panning = null
      pressedAt = null
    }
  }
  canvas.addEventListener("pointerup", (event) => release(event, true))
  canvas.addEventListener("pointercancel", (event) => release(event, false))
  canvas.addEventListener("pointerleave", (event) => release(event, false))

  canvas.addEventListener(
    "wheel",
    (event) => {
      event.preventDefault()
      const at = local(event)
      zoomAbout(room.scale.x * (event.deltaY < 0 ? 1.12 : 1 / 1.12), at.x, at.y)
    },
    { passive: false },
  )

  // -- drawing ---------------------------------------------------------------
  const render = (stage: StageState) => {
    const flows = Object.keys(stage.workers)
    const arranged = place(flows, savedSpots(), columnsFor(app.screen.width))

    for (const [flow, bench] of benches) {
      if (!(flow in stage.workers)) {
        bench.destroy()
        benches.delete(flow)
      }
    }

    // Centre when the set of benches changes -- but never once the reader has
    // arranged or zoomed it, or every event would tug their view around.
    const signature = `${flows.join("|")}@${app.screen.width}x${app.screen.height}`
    if (signature !== arrangedFor && !handled && Object.keys(savedSpots()).length === 0) {
      arrangedFor = signature
      const box = bounds(Object.values(arranged))
      const scale = fit(box, app.screen)
      room.scale.set(scale)
      room.position.set(
        (app.screen.width - box.width * scale) / 2 - box.x * scale,
        (app.screen.height - box.height * scale) / 2 - box.y * scale,
      )
    }

    for (const flow of flows) {
      let bench = benches.get(flow)
      if (!bench) {
        bench = makeBench(PIXI, flow)
        bench.root.on("pointerdown", (event: any) => {
          if (pointers.size >= 2) return
          const point = event.getLocalPosition(room)
          const held = bench!
          dropPress()
          press = {
            flow,
            x: point.x,
            y: point.y,
            timer: window.setTimeout(() => {
              press = null
              // A carry takes over from looking around.
              panning = null
              dragging = { flow, dx: point.x - held.root.x, dy: point.y - held.root.y }
              held.root.cursor = "grabbing"
              held.root.alpha = 0.85
              room.setChildIndex(held.root, room.children.length - 1)
              showGhost(cellAt(held.root.x, held.root.y), false)
            }, PICK_UP_MS),
          }
        })
        benches.set(flow, bench)
        room.addChild(bench.root)
      }
      spots[flow] = arranged[flow]
      if (dragging?.flow !== flow) bench.moveTo(arranged[flow])
      bench.paint(stage.workers[flow])
      bench.tick(elapsed)
    }

    tidy.hidden = !handled && Object.keys(savedSpots()).length === 0
  }

  let latest: StageState | null = null
  tidy.addEventListener("click", () => {
    forgetSpots()
    handled = false
    arrangedFor = ""
    if (latest) render(latest)
  })

  return {
    update(stage: StageState) {
      latest = stage
      render(stage)
    },

    destroy() {
      for (const bench of benches.values()) bench.destroy()
      benches.clear()
      app.destroy(true, { children: true })
    },
  }
}

export const atelier: Skin = {
  id: "atelier",
  label: "Atelier",

  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle {
    let disposed = false
    let latest: StageState | null = null
    let renderer: { update(stage: StageState): void; destroy(): void } | null = null

    // Something to look at while the renderer arrives. `mount` stays
    // synchronous so no other skin has to learn about loading.
    const note = document.createElement("p")
    note.className = "atelier-note"
    note.textContent = "opening the workshop…"
    el.append(note)

    void import("pixi.js")
      .then(async (PIXI) => {
        if (disposed) return
        const built = await build(PIXI, el, callbacks)
        if (disposed) {
          built.destroy()
          return
        }
        renderer = built
        note.remove()
        // Hand over the board as it stands; the next event may be minutes off.
        if (latest) renderer.update(latest)
      })
      .catch(() => {
        if (disposed) return
        note.textContent = "The workshop could not be drawn. The ledger view still works."
      })

    return {
      update(stage: StageState) {
        latest = stage
        renderer?.update(stage)
      },

      destroy() {
        disposed = true
        renderer?.destroy()
        renderer = null
        el.replaceChildren()
      },
    }
  },
}
