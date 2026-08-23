import { beforeEach, expect, test, vi } from "vitest"

import { initialStage } from "../../state/stage"
import type { FlowRow } from "../../types"

/**
 * A PixiJS stand-in.
 *
 * Enough surface for the renderer to build a room and put benches in it. What
 * is being tested here is the loading lifecycle -- what happens before, during
 * and after a dynamic import that may never resolve -- not the drawing, which
 * is verified by looking.
 */
const pixi = vi.hoisted(() => {
  const chainable = () =>
    new Proxy(
      {},
      {
        get(target: any, key) {
          if (key === "then") return undefined
          if (!(key in target)) target[key] = (..._args: unknown[]) => proxy
          return target[key]
        },
      },
    )
  let proxy: any = chainable()

  class FakeContainer {
    children: any[] = []
    position = { set: () => {} }
    scale = { set: () => {}, x: 1, y: 1 }
    anchor = { set: () => {} }
    blendMode = ""
    mask: any = null
    alpha = 1
    rotation = 0
    x = 0
    y = 0
    eventMode = ""
    cursor = ""
    visible = true
    text = ""
    destroyed = false
    listeners: Record<string, Function[]> = {}

    addChild(child: any) {
      this.children.push(child)
      return child
    }
    removeChildren() {
      const gone = this.children
      this.children = []
      return gone
    }
    setChildIndex() {}
    removeAllListeners() {
      this.listeners = {}
    }
    on(name: string, fn: Function) {
      ;(this.listeners[name] ??= []).push(fn)
    }
    destroy() {
      this.destroyed = true
    }
  }

  class FakeGraphics extends FakeContainer {
    poly() {
      return this
    }
    rect() {
      return this
    }
    circle() {
      return this
    }
    ellipse() {
      return this
    }
    roundRect() {
      return this
    }
    fill() {
      return this
    }
    stroke() {
      return this
    }
    clear() {
      return this
    }
  }

  const apps: any[] = []
  class FakeApplication {
    canvas = document.createElement("canvas")
    stage = new FakeContainer()
    screen = { width: 800, height: 600 }
    ticker = { add: () => {} }
    destroyed = false
    constructor() {
      apps.push(this)
    }
    async init() {}
    destroy() {
      this.destroyed = true
    }
  }

  class FakeGradient {}

  return {
    apps,
    module: {
      Application: FakeApplication,
      Container: FakeContainer,
      Graphics: FakeGraphics,
      Text: FakeContainer,
      FillGradient: FakeGradient,
    },
  }
})

vi.mock("pixi.js", () => pixi.module)

const { atelier } = await import("./index")

const FLOWS: FlowRow[] = [
  {
    name: "chores",
    graph: "agent-task",
    trigger: "loop",
    status: "running",
    current_run_id: null,
    last_run: null,
    pending: 0,
    into: "main",
  },
]

const settle = () => new Promise((resolve) => setTimeout(resolve, 0))

beforeEach(() => {
  pixi.apps.length = 0
  localStorage.clear()
})

test("mount returns a handle before the renderer has loaded", () => {
  const el = document.createElement("div")

  const handle = atelier.mount(el, { onSelectWorker: () => {} })

  // Synchronous, like every other skin: no caller waits on this one's problem.
  expect(typeof handle.update).toBe("function")
  expect(el.textContent).toMatch(/workshop/i)
  handle.destroy()
})

test("a stage handed over while loading is applied once the room is ready", async () => {
  const el = document.createElement("div")
  const handle = atelier.mount(el, { onSelectWorker: () => {} })

  handle.update(initialStage(FLOWS))
  await settle()

  // Otherwise the workshop stands empty until the next event, which on a quiet
  // flow can be minutes away.
  expect(pixi.apps).toHaveLength(1)
  expect(el.querySelector("canvas")).not.toBeNull()
  // The note must be gone, not merely reworded: a renderer that threw would
  // land in the catch and rewrite it, and the canvas is appended before that.
  expect(el.querySelector(".atelier-note")).toBeNull()
  // And a bench was actually built. Without this, a renderer that threw
  // halfway still looks like a success from the outside.
  const room = pixi.apps[0].stage.children[0]
  expect(room.children.length).toBeGreaterThan(1)
  handle.destroy()
})

test("destroy before the import resolves leaves nothing behind", async () => {
  const el = document.createElement("div")
  const handle = atelier.mount(el, { onSelectWorker: () => {} })

  handle.destroy()
  await settle()

  // No canvas may appear in an element that was already torn down.
  expect(el.querySelector("canvas")).toBeNull()
  expect(el.childElementCount).toBe(0)
  expect(pixi.apps.every((app) => app.destroyed)).toBe(true)
})

test("a failed import degrades to a message rather than taking the page down", async () => {
  // doMock rather than the hoisted mock: that one is cached, so flipping a
  // flag inside it never actually failed the import -- the first version of
  // this test rendered a canvas and passed for the wrong reason.
  vi.resetModules()
  vi.doMock("pixi.js", () => {
    throw new Error("chunk did not arrive")
  })
  const { atelier: broken } = await import("./index")
  const el = document.createElement("div")

  const handle = broken.mount(el, { onSelectWorker: () => {} })
  expect(() => handle.update(initialStage(FLOWS))).not.toThrow()
  await settle()

  expect(el.querySelector("canvas")).toBeNull()
  expect(el.textContent).toMatch(/could not be drawn/i)

  handle.destroy()
  vi.doUnmock("pixi.js")
})

test("update after destroy is ignored", async () => {
  const el = document.createElement("div")
  const handle = atelier.mount(el, { onSelectWorker: () => {} })
  await settle()

  handle.destroy()
  expect(() => handle.update(initialStage(FLOWS))).not.toThrow()
})
