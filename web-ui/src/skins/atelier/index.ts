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
  bounds,
  bubbleVisible,
  clampZoom,
  columnsFor,
  figurePose,
  fit,
  fromIso,
  hammerAngle,
  lampLit,
  place,
  prefersReducedMotion,
  shelfCount,
  sparking,
  toIso,
} from "./scene"
import type { Spot } from "./scene"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import type { StageState, Worker } from "../../state/stage"
import "./atelier.css"

type Pixi = typeof import("pixi.js")

const INK = {
  floor: 0x211c17,
  floorEdge: 0x2e2820,
  wall: 0x1a1611,
  benchSide: 0x3a332a,
  anvil: 0x8c8378,
  anvilDark: 0x5d564d,
  forgeCold: 0x2a241d,
  forgeHot: 0xd8733a,
  ember: 0xffb454,
  tool: 0x6b6257,
  toolBad: 0xd16d5a,
  shelf: 0x2e2820,
  piece: 0xa9b665,
  skin: 0xcbbfae,
  apronIdle: 0x6f665b,
  apronWork: 0x8a6a3f,
  apronBad: 0xa8503f,
  hammer: 0x9a9086,
  bubble: 0x2a251e,
  text: 0xe8e2d8,
  faint: 0x9a9086,
}

/**
 * How far a pointer may travel and still count as a click, not a drag.
 *
 * A finger is not a mouse: a tap on a phone wanders further than a few pixels,
 * and at four the workshop was quietly pinning benches wherever a tap wobbled.
 */
const CLICK_SLOP = 14

interface Bench {
  root: any
  paint(worker: Worker): void
  tick(elapsed: number): void
  moveTo(spot: Spot): void
  destroy(): void
}

function makeBench(PIXI: Pixi, flow: string): Bench {
  const root = new PIXI.Container()
  root.eventMode = "static"
  root.cursor = "grab"

  const floor = new PIXI.Graphics()
  floor
    .poly([0, -40, 132, 26, 0, 92, -132, 26])
    .fill(INK.floor)
    .stroke({ color: INK.floorEdge, width: 1 })
  root.addChild(floor)

  const wall = new PIXI.Graphics()
  wall.poly([-132, 26, -132, -46, 0, -112, 0, -40]).fill(INK.wall)
  wall.poly([132, 26, 132, -46, 0, -112, 0, -40]).fill(INK.floorEdge)
  root.addChild(wall)

  // set into the left wall
  const forge = new PIXI.Graphics()
  root.addChild(forge)

  // on the right wall
  const tools = new PIXI.Container()
  root.addChild(tools)

  const shelf = new PIXI.Graphics()
  shelf.poly([16, -54, 118, -3, 118, -25, 16, -76]).fill(INK.shelf)
  root.addChild(shelf)

  const pieces = new PIXI.Container()
  root.addChild(pieces)

  // The smith is drawn before the anvil, so the anvil stands in front of them.
  const figure = new PIXI.Graphics()
  root.addChild(figure)

  const arm = new PIXI.Container()
  const hammer = new PIXI.Graphics()
  // Drawn out along +x from the shoulder, so rotating the container swings it.
  hammer.roundRect(0, -3, 40, 6, 3).fill(INK.hammer)
  hammer.roundRect(34, -11, 15, 22, 3).fill(INK.anvilDark)
  arm.addChild(hammer)
  root.addChild(arm)

  const anvil = new PIXI.Graphics()
  anvil.poly([6, 32, 54, 32, 48, 60, 12, 60]).fill(INK.benchSide)
  anvil.poly([2, 24, 58, 24, 52, 34, 8, 34]).fill(INK.anvilDark)
  anvil.rect(22, 14, 16, 11).fill(INK.anvilDark)
  anvil.poly([0, 2, 44, 2, 52, 8, 44, 15, 0, 15]).fill(INK.anvil)
  anvil.poly([44, 4, 70, 8, 44, 13]).fill(INK.anvil)
  root.addChild(anvil)

  const sparks = new PIXI.Graphics()
  root.addChild(sparks)

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
      const apron =
        pose === "working" ? INK.apronWork : pose === "alarmed" ? INK.apronBad : INK.apronIdle

      // Leans in over the anvil to work, straightens when waiting.
      const lean = pose === "working" ? 6 : 0
      const drop = pose === "sitting" ? 6 : 0

      figure.clear()
      figure.roundRect(-52 + lean, 26 + drop, 12, 32, 5).fill(INK.apronIdle)
      figure.roundRect(-36 + lean, 26 + drop, 12, 32, 5).fill(INK.apronIdle)
      figure.roundRect(-56 + lean, -18 + drop, 40, 48, 8).fill(apron)
      // the apron itself, darker over the front
      figure
        .poly([
          -54 + lean, 4 + drop,
          -18 + lean, 4 + drop,
          -22 + lean, 42 + drop,
          -50 + lean, 42 + drop,
        ])
        .fill(INK.anvilDark)
      // the far arm, resting on the anvil
      figure.roundRect(-24 + lean, -8 + drop, 32, 8, 4).fill(INK.skin)
      figure.circle(-36 + lean, -32 + drop, 12).fill(INK.skin)
      // a flat cap
      figure
        .poly([
          -50 + lean, -36 + drop,
          -22 + lean, -36 + drop,
          -26 + lean, -47 + drop,
          -46 + lean, -47 + drop,
        ])
        .fill(apron)

      arm.position.set(-34 + lean, -6 + drop)
      arm.visible = pose !== "alarmed"

      forge.clear()
      forge.poly([-118, 6, -60, -24, -60, -60, -118, -30]).fill(INK.floorEdge)
      const hot = lampLit(worker)
      forge
        .poly([-108, 0, -70, -20, -70, -46, -108, -26])
        .fill(hot ? INK.forgeHot : INK.forgeCold)
      if (hot) {
        forge.poly([-102, -4, -76, -18, -76, -34, -102, -20]).fill(INK.ember)
      }
      if (worker.status === "error") {
        forge.circle(-89, -22, 22).stroke({ color: INK.apronBad, width: 2 })
      }

      tools.removeChildren().forEach((child: any) => child.destroy())
      worker.recentToolCalls.slice(0, 4).forEach((call, index) => {
        const mark = new PIXI.Graphics()
        mark
          .roundRect(58 + index * 20, -84 + index * 10, 13, 22, 3)
          .fill(call.error ? INK.toolBad : INK.tool)
        tools.addChild(mark)
        if (index === 0) {
          const label = new PIXI.Text({
            text: call.name,
            style: { fill: INK.faint, fontSize: 10, fontFamily: "system-ui, sans-serif" },
          })
          label.anchor.set(0, 1)
          label.position.set(40, -90)
          tools.addChild(label)
        }
      })

      pieces.removeChildren().forEach((child: any) => child.destroy())
      const stacked = Math.min(shelfCount(worker), 6)
      for (let i = 0; i < stacked; i += 1) {
        const piece = new PIXI.Graphics()
        piece.roundRect(24 + i * 15, -66 + i * 7, 10, 10, 2).fill(INK.piece)
        pieces.addChild(piece)
      }

      bubble.removeChildren().forEach((child: any) => child.destroy())
      bubble.visible = bubbleVisible(worker)
      if (bubble.visible) {
        const pad = new PIXI.Graphics()
        pad.roundRect(-46, -132, 172, 32, 9).fill(INK.bubble)
        pad.circle(-38, -94, 5).fill(INK.bubble)
        pad.circle(-46, -82, 3).fill(INK.bubble)
        bubble.addChild(pad)

        const said = new PIXI.Text({
          text: worker.lastThinking.slice(0, 36),
          style: { fill: INK.faint, fontSize: 10, fontFamily: "system-ui, sans-serif" },
        })
        said.position.set(-38, -124)
        bubble.addChild(said)
      }

      doing.text = worker.currentNode
        ? `${worker.currentNode}${worker.turn > 0 ? ` · turn ${worker.turn}` : ""}`
        : "idle"
    },

    tick(elapsed: number) {
      if (!current) return
      arm.rotation = figurePose(current) === "working" ? hammerAngle(elapsed) : -0.55

      sparks.clear()
      if (sparking(current, elapsed)) {
        for (let i = 0; i < 5; i += 1) {
          const spread = (i - 2) * 8
          sparks.circle(26 + spread, 2 - Math.abs(spread) * 0.6, 2).fill(INK.ember)
        }
      }
    },

    moveTo(spot: Spot) {
      const screen = toIso(spot.x, spot.y)
      root.position.set(screen.x, screen.y)
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
  const spots: Record<string, Spot> = {}
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

  // -- moving one bench ------------------------------------------------------
  let dragging: { flow: string; dx: number; dy: number; moved: boolean } | null = null

  app.stage.on("pointermove", (event: any) => {
    if (!dragging) return
    const bench = benches.get(dragging.flow)
    if (!bench) return
    const point = event.getLocalPosition(room)
    const next = { x: point.x - dragging.dx, y: point.y - dragging.dy }
    if (
      Math.abs(next.x - bench.root.x) > CLICK_SLOP ||
      Math.abs(next.y - bench.root.y) > CLICK_SLOP
    ) {
      dragging.moved = true
    }
    bench.root.position.set(next.x, next.y)
  })

  const drop = () => {
    if (!dragging) return
    const { flow, moved } = dragging
    const bench = benches.get(flow)
    dragging = null
    if (!bench) return
    bench.root.cursor = "grab"
    if (!moved) {
      // A press that went nowhere is a click: open the worker.
      callbacks.onSelectWorker(flow)
      bench.moveTo(spots[flow])
      return
    }
    // Store where it stands on the floor, not where it landed on screen, so
    // the arrangement survives any change to the projection.
    const placedAt = fromIso(bench.root.x, bench.root.y)
    spots[flow] = placedAt
    saveSpot(flow, placedAt)
    handled = true
    bench.moveTo(placedAt)
  }
  app.stage.on("pointerup", drop)
  app.stage.on("pointerupoutside", drop)

  // -- moving and scaling the whole room -------------------------------------
  const pointers = new Map<number, { x: number; y: number }>()
  let panning: { x: number; y: number } | null = null
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
    }
  })

  canvas.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return
    pointers.set(event.pointerId, local(event))

    if (pinch && pointers.size >= 2) {
      const { gap, x, y } = spread()
      if (pinch.gap > 0) zoomAbout(pinch.scale * (gap / pinch.gap), x, y)
      return
    }
    if (panning && !dragging) {
      const at = local(event)
      room.position.set(at.x - panning.x, at.y - panning.y)
      handled = true
    }
  })

  const release = (event: PointerEvent) => {
    pointers.delete(event.pointerId)
    if (pointers.size < 2) pinch = null
    if (pointers.size === 0) panning = null
  }
  canvas.addEventListener("pointerup", release)
  canvas.addEventListener("pointercancel", release)
  canvas.addEventListener("pointerleave", release)

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
          dragging = {
            flow,
            dx: point.x - bench!.root.x,
            dy: point.y - bench!.root.y,
            moved: false,
          }
          bench!.root.cursor = "grabbing"
          // Whichever bench is being handled belongs in front.
          room.setChildIndex(bench!.root, room.children.length - 1)
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
