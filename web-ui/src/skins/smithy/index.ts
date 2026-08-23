/**
 * The smithy in three dimensions.
 *
 * The same room as the atelier skin -- one forge per flow, on the same grid of
 * squares -- but built from a real model and lit by a real light, so the forge
 * actually throws warmth onto the walls and the smith standing at it.
 *
 * The character is the only downloaded asset. Everything else is boxes and
 * cylinders: an anvil and a forge that cost nothing to ship. Three.js and the
 * model arrive through a dynamic import, so a reader who stays on the ledger
 * or the atelier never pays for either.
 */

import { forgetSpots, savedSpots, saveSpot } from "../atelier/placement"
import { figurePose, hammerAngle, lampLit, shelfCount } from "../atelier/scene"
import {
  bounds,
  cellAt,
  cellOrigin,
  clampZoom,
  columnsFor,
  fit,
  occupied,
  place,
} from "../layout"
import type { Cell } from "../layout"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import type { StageState, Worker } from "../../state/stage"
import "./smithy.css"
// Imported rather than served from a fixed path, so Vite hashes it into
// /assets with everything else: one cache policy, and a changed model
// reaches the browser instead of sitting stale behind its own name.
import smithUrl from "./smith.glb?url"

type Three = typeof import("three")

/** Screen pixels per world unit, so the grid keeps its familiar spacing. */
const PER_UNIT = 90

const CLICK_SLOP = 14
const PICK_UP_MS = 380

const HUE = {
  floor: 0x2a241d,
  wall: 0x1e1a15,
  iron: 0x3f3a33,
  anvil: 0x6b6257,
  stone: 0x38322a,
  ember: 0xff8a3d,
  piece: 0xa9b665,
  free: 0xa9b665,
  taken: 0xd16d5a,
}

interface Bench {
  group: any
  place(cell: Cell): void
  paint(worker: Worker): void
  tick(elapsed: number): void
  dispose(): void
}

function makeBench(THREE: Three, smith: any): Bench {
  const group = new THREE.Group()

  const floor = new THREE.Mesh(
    new THREE.BoxGeometry(2.6, 0.12, 2.6),
    new THREE.MeshStandardMaterial({ color: HUE.floor, roughness: 0.95 }),
  )
  floor.position.y = -0.06
  group.add(floor)

  const backWall = new THREE.Mesh(
    new THREE.BoxGeometry(2.6, 1.5, 0.12),
    new THREE.MeshStandardMaterial({ color: HUE.wall, roughness: 1 }),
  )
  backWall.position.set(0, 0.75, -1.24)
  group.add(backWall)

  const sideWall = backWall.clone()
  sideWall.rotation.y = Math.PI / 2
  sideWall.position.set(-1.24, 0.75, 0)
  group.add(sideWall)

  // -- the forge: a stone box with a mouth that lights up
  const forge = new THREE.Mesh(
    new THREE.BoxGeometry(0.9, 0.9, 0.5),
    new THREE.MeshStandardMaterial({ color: HUE.stone, roughness: 1 }),
  )
  forge.position.set(-0.8, 0.45, -1.0)
  group.add(forge)

  const mouth = new THREE.Mesh(
    new THREE.PlaneGeometry(0.5, 0.4),
    new THREE.MeshBasicMaterial({ color: HUE.ember }),
  )
  mouth.position.set(-0.8, 0.5, -0.74)
  group.add(mouth)

  const fire = new THREE.PointLight(HUE.ember, 0, 4, 2)
  fire.position.set(-0.8, 0.6, -0.6)
  group.add(fire)

  // -- the anvil on its stump
  const stump = new THREE.Mesh(
    new THREE.CylinderGeometry(0.26, 0.3, 0.5, 10),
    new THREE.MeshStandardMaterial({ color: HUE.iron, roughness: 1 }),
  )
  stump.position.set(0.55, 0.25, 0.1)
  group.add(stump)

  const anvil = new THREE.Mesh(
    new THREE.BoxGeometry(0.7, 0.18, 0.26),
    new THREE.MeshStandardMaterial({ color: HUE.anvil, roughness: 0.55, metalness: 0.6 }),
  )
  anvil.position.set(0.55, 0.59, 0.1)
  group.add(anvil)

  const work = new THREE.Mesh(
    new THREE.BoxGeometry(0.34, 0.06, 0.1),
    new THREE.MeshBasicMaterial({ color: HUE.ember }),
  )
  work.position.set(0.5, 0.71, 0.1)
  group.add(work)

  // -- the smith, the one thing that was downloaded
  const figure = smith.clone(true)
  figure.position.set(-0.15, 0, 0.15)
  figure.rotation.y = Math.PI * 0.15
  group.add(figure)

  // -- finished work on a shelf
  const shelf = new THREE.Group()
  shelf.position.set(0.6, 0.95, -1.1)
  group.add(shelf)

  let working = false
  let hot = false

  return {
    group,

    place(cell: Cell) {
      const at = cellOrigin(cell)
      group.position.set(at.x / PER_UNIT, 0, at.y / PER_UNIT)
    },

    paint(worker: Worker) {
      const pose = figurePose(worker)
      working = pose === "working"
      hot = lampLit(worker)

      mouth.material.color.setHex(hot ? HUE.ember : HUE.wall)
      work.visible = hot
      fire.intensity = hot ? 6 : 0
      if (pose === "alarmed") {
        mouth.material.color.setHex(HUE.taken)
        fire.color.setHex(HUE.taken)
        fire.intensity = 2
      } else {
        fire.color.setHex(HUE.ember)
      }

      while (shelf.children.length) {
        const piece = shelf.children.pop() as any
        piece?.geometry?.dispose?.()
        piece?.material?.dispose?.()
      }
      const stacked = Math.min(shelfCount(worker), 6)
      for (let i = 0; i < stacked; i += 1) {
        const piece = new THREE.Mesh(
          new THREE.BoxGeometry(0.1, 0.1, 0.1),
          new THREE.MeshStandardMaterial({ color: HUE.piece, roughness: 0.8 }),
        )
        piece.position.x = i * 0.14
        shelf.add(piece)
      }
    },

    tick(elapsed: number) {
      // The model is one piece, so the whole body takes the swing: it leans
      // into the blow and comes back up. Half a hammer is better than none.
      const swing = working ? hammerAngle(elapsed) : 0
      figure.rotation.x = working ? (swing + 1.25) * 0.18 : 0
      figure.position.y = working ? Math.max(0, -swing) * 0.04 : 0

      if (hot) {
        // firelight is never steady
        fire.intensity = 5.2 + Math.sin(elapsed / 90) * 0.8 + Math.sin(elapsed / 37) * 0.4
      }
    },

    dispose() {
      group.traverse((node: any) => {
        node.geometry?.dispose?.()
        if (Array.isArray(node.material)) node.material.forEach((m: any) => m.dispose?.())
        else node.material?.dispose?.()
      })
    },
  }
}

async function build(THREE: Three, el: HTMLElement, callbacks: SkinCallbacks) {
  const { GLTFLoader } = await import("three/examples/jsm/loaders/GLTFLoader.js")
  const { MeshoptDecoder } = await import("three/examples/jsm/libs/meshopt_decoder.module.js")

  const loader = new GLTFLoader()
  loader.setMeshoptDecoder(MeshoptDecoder)
  const gltf = await loader.loadAsync(smithUrl)

  const smith = gltf.scene
  // Meshy exports around a metre; scale it to the room and stand it on the floor.
  const box = new THREE.Box3().setFromObject(smith)
  const height = box.max.y - box.min.y
  smith.scale.setScalar(1.25 / (height || 1))
  smith.position.y = -box.min.y * (1.25 / (height || 1))

  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setSize(el.clientWidth, el.clientHeight)
  renderer.setClearColor(0x14120f, 1)
  el.append(renderer.domElement)
  renderer.domElement.classList.add("smithy-canvas")

  const scene = new THREE.Scene()
  scene.add(new THREE.AmbientLight(0x6b6257, 0.5))
  const key = new THREE.DirectionalLight(0xbfae94, 0.5)
  key.position.set(3, 6, 4)
  scene.add(key)

  const room = new THREE.Group()
  scene.add(room)

  // A true isometric view: equal foreshortening on both floor axes.
  const camera = new THREE.OrthographicCamera(-1, 1, 1, -1, -100, 100)
  camera.position.set(10, 10, 10)
  camera.lookAt(0, 0, 0)

  const ghost = new THREE.Mesh(
    new THREE.BoxGeometry(2.6, 0.02, 2.6),
    new THREE.MeshBasicMaterial({ color: HUE.free, transparent: true, opacity: 0.35 }),
  )
  ghost.visible = false
  room.add(ghost)

  const tidy = document.createElement("button")
  tidy.type = "button"
  tidy.className = "smithy-tidy"
  tidy.textContent = "tidy up"
  tidy.hidden = true
  el.append(tidy)

  const benches = new Map<string, Bench>()
  let spots: Record<string, Cell> = {}
  let arrangedFor = ""
  let handled = false
  let elapsed = 0

  // -- the view ---------------------------------------------------------------
  let zoom = 1
  const centre = { x: 0, y: 0 }

  const frame = () => {
    const w = el.clientWidth || 1
    const h = el.clientHeight || 1
    const half = 3.2 / zoom
    camera.left = -half * (w / h)
    camera.right = half * (w / h)
    camera.top = half
    camera.bottom = -half
    camera.position.set(10 + centre.x, 10, 10 + centre.y)
    camera.lookAt(centre.x, 0, centre.y)
    camera.updateProjectionMatrix()
    renderer.setSize(w, h, false)
  }

  const draw = () => {
    frame()
    renderer.render(scene, camera)
  }

  let running = true
  const loop = () => {
    if (!running) return
    elapsed += 16
    for (const bench of benches.values()) bench.tick(elapsed)
    draw()
    requestAnimationFrame(loop)
  }
  requestAnimationFrame(loop)

  // -- pointers ---------------------------------------------------------------
  const canvas = renderer.domElement
  const raycaster = new THREE.Raycaster()
  const pointer = new THREE.Vector2()
  const pointers = new Map<number, { x: number; y: number }>()
  let panning: { x: number; y: number } | null = null
  let pinch: { gap: number; zoom: number } | null = null
  let pressedAt: { x: number; y: number } | null = null
  let press: { flow: string; timer: number } | null = null
  let dragging: string | null = null

  const local = (event: PointerEvent | WheelEvent) => {
    const box = canvas.getBoundingClientRect()
    return { x: event.clientX - box.left, y: event.clientY - box.top }
  }

  /** Which bench, if any, is under the pointer. */
  const pick = (at: { x: number; y: number }): string | null => {
    pointer.set((at.x / canvas.clientWidth) * 2 - 1, -(at.y / canvas.clientHeight) * 2 + 1)
    raycaster.setFromCamera(pointer, camera)
    const hits = raycaster.intersectObjects(room.children, true)
    for (const hit of hits) {
      let node: any = hit.object
      while (node) {
        for (const [flow, bench] of benches) if (bench.group === node) return flow
        node = node.parent
      }
    }
    return null
  }

  /** Where on the floor the pointer is, in grid pixels. */
  const floorAt = (at: { x: number; y: number }) => {
    pointer.set((at.x / canvas.clientWidth) * 2 - 1, -(at.y / canvas.clientHeight) * 2 + 1)
    raycaster.setFromCamera(pointer, camera)
    const ground = new THREE.Plane(new THREE.Vector3(0, 1, 0), 0)
    const point = new THREE.Vector3()
    raycaster.ray.intersectPlane(ground, point)
    return { x: point.x * PER_UNIT, y: point.z * PER_UNIT }
  }

  const dropPress = () => {
    if (!press) return
    window.clearTimeout(press.timer)
    press = null
  }

  canvas.addEventListener("pointerdown", (event) => {
    const at = local(event)
    pointers.set(event.pointerId, at)

    if (pointers.size === 2) {
      dropPress()
      dragging = null
      panning = null
      const [a, b] = [...pointers.values()]
      pinch = { gap: Math.hypot(a.x - b.x, a.y - b.y), zoom }
      return
    }

    const flow = pick(at)
    pressedAt = at
    if (flow) {
      press = {
        flow,
        timer: window.setTimeout(() => {
          press = null
          panning = null
          dragging = flow
          handled = true
        }, PICK_UP_MS),
      }
    }
    panning = { x: at.x, y: at.y }
  })

  canvas.addEventListener("pointermove", (event) => {
    if (!pointers.has(event.pointerId)) return
    const at = local(event)
    pointers.set(event.pointerId, at)

    if (pinch && pointers.size >= 2) {
      const [a, b] = [...pointers.values()]
      const gap = Math.hypot(a.x - b.x, a.y - b.y)
      if (pinch.gap > 0) zoom = clampZoom(pinch.zoom * (gap / pinch.gap))
      handled = true
      return
    }

    if (dragging) {
      const bench = benches.get(dragging)
      const on = floorAt(at)
      if (bench) {
        bench.group.position.set(on.x / PER_UNIT, 0, on.y / PER_UNIT)
        const cell = cellAt(on.x, on.y)
        const blocked = occupied(spots, cell, dragging)
        const origin = cellOrigin(cell)
        ghost.position.set(origin.x / PER_UNIT, 0.02, origin.y / PER_UNIT)
        ghost.material.color.setHex(blocked ? HUE.taken : HUE.free)
        ghost.visible = true
      }
      return
    }

    if (press && pressedAt) {
      if (Math.abs(at.x - pressedAt.x) > CLICK_SLOP || Math.abs(at.y - pressedAt.y) > CLICK_SLOP) {
        dropPress()
      }
    }
    if (panning && pressedAt) {
      const scale = (3.2 / zoom) * 2 / (canvas.clientHeight || 1)
      centre.x -= (at.x - panning.x) * scale * 0.7
      centre.y -= (at.y - panning.y) * scale * 0.7
      panning = at
      handled = true
    }
  })

  const release = (event: PointerEvent, lifted: boolean) => {
    if (dragging) {
      const flow = dragging
      const bench = benches.get(flow)
      dragging = null
      ghost.visible = false
      if (bench) {
        const cell = cellAt(bench.group.position.x * PER_UNIT, bench.group.position.z * PER_UNIT)
        if (occupied(spots, cell, flow)) {
          bench.place(spots[flow])
        } else {
          spots[flow] = cell
          saveSpot(flow, cell)
          bench.place(cell)
        }
      }
    } else if (press) {
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
      zoom = clampZoom(zoom * (event.deltaY < 0 ? 1.12 : 1 / 1.12))
      handled = true
    },
    { passive: false },
  )

  // -- drawing ----------------------------------------------------------------
  const render = (stage: StageState) => {
    const flows = Object.keys(stage.workers)
    const arranged = place(flows, savedSpots(), columnsFor(el.clientWidth))

    for (const [flow, bench] of benches) {
      if (!(flow in stage.workers)) {
        room.remove(bench.group)
        bench.dispose()
        benches.delete(flow)
      }
    }

    const signature = `${flows.join("|")}@${el.clientWidth}x${el.clientHeight}`
    if (signature !== arrangedFor && !handled && Object.keys(savedSpots()).length === 0) {
      arrangedFor = signature
      const box = bounds(Object.values(arranged))
      zoom = clampZoom(fit(box, { width: el.clientWidth, height: el.clientHeight }) * 1.6)
      centre.x = (box.x + box.width / 2) / PER_UNIT
      centre.y = (box.y + box.height / 2) / PER_UNIT
    }

    for (const flow of flows) {
      let bench = benches.get(flow)
      if (!bench) {
        bench = makeBench(THREE, smith)
        benches.set(flow, bench)
        room.add(bench.group)
      }
      spots[flow] = arranged[flow]
      if (dragging !== flow) bench.place(arranged[flow])
      bench.paint(stage.workers[flow])
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
      running = false
      for (const bench of benches.values()) bench.dispose()
      benches.clear()
      renderer.dispose()
    },
  }
}

export const smithy: Skin = {
  id: "smithy",
  label: "Smithy (3D)",

  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle {
    let disposed = false
    let latest: StageState | null = null
    let renderer: { update(stage: StageState): void; destroy(): void } | null = null

    const note = document.createElement("p")
    note.className = "smithy-note"
    note.textContent = "lighting the forge…"
    el.append(note)

    // The catch covers the arrival of three.js and the model, and nothing
    // after it: a bug while drawing is not a failed download.
    void import("three")
      .then((THREE) => (disposed ? null : build(THREE, el, callbacks)))
      .catch(() => {
        if (!disposed) {
          note.textContent = "The smithy could not be loaded. The other views still work."
        }
        return null
      })
      .then((built) => {
        if (!built) return
        if (disposed) {
          built.destroy()
          return
        }
        renderer = built
        note.remove()
        if (latest) renderer.update(latest)
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
