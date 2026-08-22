/**
 * The workshop.
 *
 * One bench per flow, drawn from shapes in code — no sprite packs, per the
 * spec. The artisan sits when the flow is waiting, works while a node runs,
 * reaches to the tool wall on a tool call, thinks in a bubble, and shelves a
 * finished piece when a run lands.
 *
 * PixiJS arrives through a dynamic import and nowhere else: it is the heaviest
 * thing that reaches the browser and it serves this one skin, so a reader who
 * stays on the ledger never pays for it.
 */

import { savedSpots, saveSpot } from "./placement"
import {
  bounds,
  bubbleVisible,
  fit,
  fromIso,
  figurePose,
  lampLit,
  place,
  prefersReducedMotion,
  shelfCount,
  toIso,
} from "./scene"
import type { Spot } from "./scene"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import type { StageState, Worker } from "../../state/stage"
import "./atelier.css"

type Pixi = typeof import("pixi.js")

const INK = {
  floor: 0x1f1b16,
  floorEdge: 0x2e2820,
  benchSide: 0x3a332a,
  benchTop: 0x554a3c,
  wall: 0x241f19,
  tool: 0x6b6257,
  toolBad: 0xd16d5a,
  shelf: 0x2e2820,
  piece: 0xa9b665,
  lampOn: 0xd8a657,
  lampOff: 0x3a332a,
  bodyIdle: 0x8a8177,
  bodyWork: 0xd8a657,
  bodyBad: 0xd16d5a,
  bubble: 0x2a251e,
  text: 0xe8e2d8,
  faint: 0x9a9086,
}

/** How far a pointer may travel and still count as a click, not a drag. */
const CLICK_SLOP = 4

interface Bench {
  root: any
  paint(worker: Worker): void
  moveTo(spot: Spot): void
  tick(elapsed: number): void
  destroy(): void
}

function makeBench(PIXI: Pixi, flow: string): Bench {
  const root = new PIXI.Container()
  root.eventMode = "static"
  root.cursor = "grab"

  // -- the room around the bench
  const floor = new PIXI.Graphics()
  floor
    .poly([0, -46, 128, 18, 0, 82, -128, 18])
    .fill(INK.floor)
    .stroke({ color: INK.floorEdge, width: 1 })
  root.addChild(floor)

  const wall = new PIXI.Graphics()
  wall.poly([-128, 18, -128, -46, 0, -110, 0, -46]).fill(INK.wall)
  root.addChild(wall)

  const tools = new PIXI.Container()
  root.addChild(tools)

  const shelf = new PIXI.Graphics()
  shelf.poly([0, -46, 128, 18, 128, -14, 0, -78]).fill(INK.shelf)
  root.addChild(shelf)

  const pieces = new PIXI.Container()
  root.addChild(pieces)

  // -- the bench itself, drawn over the figure's legs
  const slab = new PIXI.Graphics()
  slab.poly([0, -6, 78, 32, 0, 70, -78, 32]).fill(INK.benchTop)
  slab.poly([-78, 32, 0, 70, 0, 82, -78, 44]).fill(INK.benchSide)
  slab.poly([78, 32, 0, 70, 0, 82, 78, 44]).fill(INK.benchSide)
  root.addChild(slab)

  const lamp = new PIXI.Graphics()
  root.addChild(lamp)

  const figure = new PIXI.Graphics()
  root.addChild(figure)

  const bubble = new PIXI.Container()
  root.addChild(bubble)

  const name = new PIXI.Text({
    text: flow,
    style: { fill: INK.text, fontSize: 14, fontFamily: "system-ui, sans-serif" },
  })
  name.anchor.set(0.5, 0)
  name.position.set(0, 88)
  root.addChild(name)

  const doing = new PIXI.Text({
    text: "",
    style: { fill: INK.faint, fontSize: 11, fontFamily: "system-ui, sans-serif" },
  })
  doing.anchor.set(0.5, 0)
  doing.position.set(0, 106)
  root.addChild(doing)

  let working = false

  return {
    root,

    paint(worker: Worker) {
      const pose = figurePose(worker)
      working = pose === "working"
      const body =
        pose === "working" ? INK.bodyWork : pose === "alarmed" ? INK.bodyBad : INK.bodyIdle

      // Leans in to work, settles back when waiting. The slab is drawn after
      // this, so the lower body is hidden and the figure stands behind it.
      const lean = pose === "working" ? -8 : 0
      const drop = pose === "sitting" ? 8 : 0
      figure.clear()
      figure.ellipse(lean, 8 + drop, 17, 30).fill(body)
      figure.roundRect(lean - 18, -20 + drop, 36, 14, 6).fill(body)
      figure.circle(lean, -34 + drop, 11).fill(body)
      if (pose === "working") {
        // an arm out across the bench
        figure.ellipse(lean + 26, 2, 18, 6).fill(body)
      }

      lamp.clear()
      lamp.rect(62, -34, 3, 30).fill(INK.benchSide)
      lamp
        .circle(64, -40, 8)
        .fill(lampLit(worker) ? INK.lampOn : INK.lampOff)
      if (worker.status === "error") {
        lamp.circle(64, -40, 13).stroke({ color: INK.bodyBad, width: 2 })
      }

      // -- the wall of tools: the most recent calls, newest nearest the bench
      tools.removeChildren().forEach((child: any) => child.destroy())
      worker.recentToolCalls.slice(0, 4).forEach((call, index) => {
        const mark = new PIXI.Graphics()
        mark
          .rect(-104 + index * 24, -74 + index * 12, 16, 16)
          .fill(call.error ? INK.toolBad : INK.tool)
        tools.addChild(mark)
        if (index === 0) {
          const label = new PIXI.Text({
            text: call.name,
            style: { fill: INK.faint, fontSize: 10, fontFamily: "system-ui, sans-serif" },
          })
          label.position.set(-104, -94)
          tools.addChild(label)
        }
      })

      // -- the shelf: one piece per run that landed
      pieces.removeChildren().forEach((child: any) => child.destroy())
      const stacked = Math.min(shelfCount(worker), 6)
      for (let i = 0; i < stacked; i += 1) {
        const piece = new PIXI.Graphics()
        piece.rect(24 + i * 16, -62 + i * 8, 11, 11).fill(INK.piece)
        pieces.addChild(piece)
      }

      // -- what it is thinking, if anything
      bubble.removeChildren().forEach((child: any) => child.destroy())
      bubble.visible = bubbleVisible(worker)
      if (bubble.visible) {
        const pad = new PIXI.Graphics()
        pad.roundRect(-26, -108, 150, 30, 8).fill(INK.bubble)
        pad.circle(-14, -72, 4).fill(INK.bubble)
        pad.circle(-22, -62, 3).fill(INK.bubble)
        bubble.addChild(pad)

        const said = new PIXI.Text({
          text: worker.lastThinking.slice(0, 34),
          style: { fill: INK.faint, fontSize: 10, fontFamily: "system-ui, sans-serif" },
        })
        said.position.set(-18, -100)
        bubble.addChild(said)
      }

      doing.text = worker.currentNode
        ? `${worker.currentNode}${worker.turn > 0 ? ` · turn ${worker.turn}` : ""}`
        : "idle"
    },

    tick(elapsed: number) {
      // The only motion in the room: a bench in use breathes a little.
      figure.y = working ? Math.sin(elapsed / 260) * 2 : 0
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
  app.canvas.classList.add("atelier-canvas")
  el.append(app.canvas)

  // The room is drawn around an origin the benches hang off, so the whole
  // workshop can be nudged without touching any bench's own spot.
  const room = new PIXI.Container()
  app.stage.addChild(room)
  let arrangedFor = ""

  app.stage.eventMode = "static"
  app.stage.hitArea = app.screen

  const benches = new Map<string, Bench>()
  const spots: Record<string, Spot> = {}
  const reduced = prefersReducedMotion()
  let elapsed = 0
  if (!reduced) {
    app.ticker.add((ticker: any) => {
      elapsed += ticker.deltaMS
      for (const bench of benches.values()) bench.tick(elapsed)
    })
  }

  let dragging: { flow: string; dx: number; dy: number; moved: boolean } | null = null

  app.stage.on("pointermove", (event: any) => {
    if (!dragging) return
    const bench = benches.get(dragging.flow)
    if (!bench) return
    const point = event.getLocalPosition(room)
    const next = { x: point.x - dragging.dx, y: point.y - dragging.dy }
    if (Math.abs(next.x - bench.root.x) > CLICK_SLOP || Math.abs(next.y - bench.root.y) > CLICK_SLOP) {
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
    bench.moveTo(placedAt)
  }
  app.stage.on("pointerup", drop)
  app.stage.on("pointerupoutside", drop)

  return {
    update(stage: StageState) {
      const flows = Object.keys(stage.workers)
      const arranged = place(flows, savedSpots())

      for (const [flow, bench] of benches) {
        if (!(flow in stage.workers)) {
          bench.destroy()
          benches.delete(flow)
        }
      }

      // Centre the room when the set of benches changes -- but never once the
      // reader has arranged it, or every event would tug their layout around.
      const signature = `${flows.join("|")}@${app.screen.width}x${app.screen.height}`
      if (signature !== arrangedFor && Object.keys(savedSpots()).length === 0) {
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
      }
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
