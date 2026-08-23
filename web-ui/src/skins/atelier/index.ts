/**
 * The workshop: a smithy, one forge per flow, in three dimensions.
 *
 * Benches stand on the shared grid of squares. The forge is a real light, so
 * its warmth falls on the walls and on the smith rather than being painted on.
 *
 * The character is the only downloaded asset. Everything else is boxes and
 * cylinders: an anvil and a forge that cost nothing to ship. Three.js and the
 * model arrive through a dynamic import, so a reader who stays on the ledger
 * or the atelier never pays for either.
 */

import { forgetSpots, savedSpots, saveSpot } from "./placement"
import { makeCabin } from "./cabin"
import { makeFace } from "./face"
import { makeFire } from "./fire"
import { figurePose, lampLit, shelfCount } from "./scene"
import {
  bounds,
  cellAt,
  cellOrigin,
  clampZoom,
  columnsFor,
  occupied,
  place,
} from "../layout"
import type { Cell } from "../layout"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import type { StageState, Worker } from "../../state/stage"
import "./atelier.css"
// Imported rather than served from a fixed path, so Vite hashes it into
// /assets with everything else: one cache policy, and a changed model
// reaches the browser instead of sitting stale behind its own name.
import anvilUrl from "./anvil.glb?url"
import forgeUrl from "./forge.glb?url"
import smithUrl from "./smith.glb?url"

type Three = typeof import("three")

/** Screen pixels per world unit, so the grid keeps its familiar spacing. */
const PER_UNIT = 70

/** Half the height the camera sees at zoom 1, in world units. */
const BASE_HALF = 3.2

/**
 * Which way the imported model has to turn so his chest faces his anvil.
 *
 * Not derivable: this rig's rest pose is visibly twisted -- the right shoulder
 * sits a whole hand-width behind the left -- so the angle that reads as
 * "facing the work" was chosen by sweeping candidates in tools/bench.html
 * (?facing=45 and so on) and looking at the room view.
 */
export let FACING = Math.PI * 0.25

/** Tool-only override, so bench.html can photograph facing candidates. */
export function turnFigure(angle: number) {
  FACING = angle
}

/** Which way the anvil lies under him; see tools/bench.html. */
export let ANVIL_TURN = 0

/** Tool-only override, so bench.html can photograph the candidates. */
export function turnAnvil(angle: number) {
  ANVIL_TURN = angle
}

/** Which hand the model holds its hammer in. */
const HAMMER_HAND = "Right"

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

export interface Bench {
  group: any
  place(cell: Cell): void
  paint(worker: Worker): void
  tick(elapsed: number): void
  dispose(): void
}

/** A steady per-flow offset, so neighbouring smiths blink out of step. */
function stagger(flow: string): number {
  let hash = 0
  for (const letter of flow) hash = (hash * 31 + letter.charCodeAt(0)) % 3600
  return hash
}

/** Exported for tools/bench.html, which judges the swing over a real anvil. */
export interface Props {
  anvil: any
  forge: any
}

/**
 * Stand a downloaded prop on the floor at a given height, measured rather
 * than assumed: each generation of a model is a different size.
 */
function grounded(THREE: Three, model: any, tall: number): any {
  const stood = model.clone()
  const box = new THREE.Box3().setFromObject(stood)
  const scale = tall / (box.max.y - box.min.y || 1)
  stood.scale.multiplyScalar(scale)
  const measured = new THREE.Box3().setFromObject(stood)
  stood.position.y -= measured.min.y
  stood.position.x -= (measured.min.x + measured.max.x) / 2
  stood.position.z -= (measured.min.z + measured.max.z) / 2
  return stood
}

export function makeBench(
  THREE: Three,
  smith: any,
  cloneSkinned: (node: any) => any,
  blinkOffset: number,
  clips: any[],
  props: Props,
): Bench {
  const group = new THREE.Group()

  // The room is a log cabin, drawn from primitives in its own module.
  group.add(makeCabin(THREE))

  // -- the forge, downloaded; its fire, drawn.
  const hearth = new THREE.Group()
  hearth.position.set(-0.78, 0, -0.88)
  const forge = grounded(THREE, props.forge, 1.5)
  hearth.add(forge)

  // The flame stands in the hearth's mouth. Where that is on a generated
  // model cannot be known ahead, so these are constants found by
  // photographing tools/bench.html and nudging.
  const flame = makeFire(THREE, 0.38, 0.5)
  flame.group.position.set(0.02, 0.52, 0.1)
  hearth.add(flame.group)
  group.add(hearth)

  // Firelight is the whole point of the room; it has to reach the walls.
  const fire = new THREE.PointLight(HUE.ember, 0, 6, 1.6)
  fire.position.set(-0.7, 0.7, -0.4)
  group.add(fire)

  // -- the anvil, downloaded with its stump
  const bench = new THREE.Group()
  // A smith works at the anvil's broad side, not at the horn end; chosen by
  // photographing both in tools/bench.html and looking.
  bench.rotation.y = ANVIL_TURN
  group.add(bench)

  const anvil = grounded(THREE, props.anvil, 0.78)
  bench.add(anvil)
  const anvilTop = new THREE.Box3().setFromObject(anvil).max.y

  // The piece being worked still glows from code, so it can cool when idle.
  const work = new THREE.Mesh(
    new THREE.BoxGeometry(0.26, 0.035, 0.07),
    new THREE.MeshBasicMaterial({ color: 0xd8551a }),
  )
  work.position.y = anvilTop + 0.02
  bench.add(work)
  // Hex colours, not setRGB: raw components are read as linear these days and
  // come out washed -- the hot bar rendered as a pat of butter.
  const iron = { cool: new THREE.Color(0xc93f0f), hot: new THREE.Color(0xff9a2e) }

  // -- the smith, the one thing that was downloaded.
  // A skinned mesh needs SkeletonUtils: a plain clone shares one skeleton, so
  // every bench would swing whenever any of them did.
  const figure = cloneSkinned(smith)
  figure.position.set(-0.18, 0, 0.45)
  // Turned to the anvil rather than the camera. Which way that is depends on
  // the model's own facing, so it is a constant to look at rather than derive.
  figure.rotation.y = FACING
  group.add(figure)
  const face = makeFace(THREE, figure, blinkOffset)

  // -- finished work on a shelf
  const shelf = new THREE.Group()
  // On the board the cabin nailed to its back wall.
  shelf.position.set(0.42, 1.16, -1.06)
  group.add(shelf)

  // Hand-tuned joint angles never stopped looking hand-tuned; these clips are
  // motion capture, retargeted onto the rig by the same service that rigged it.
  const mixer = new THREE.AnimationMixer(figure)
  const clipNamed = (name: string) =>
    clips.find((clip) => clip.name === name) ?? clips[0]
  const acts = {
    working: mixer.clipAction(clipNamed("swing")),
    resting: mixer.clipAction(clipNamed("idle")),
  }
  // Fades MULTIPLY an action's weight rather than replace it, so the weight
  // itself always stays 1 and only setEffectiveWeight is used to pick which
  // action shows. Writing .weight = 0 directly once froze every smith solid:
  // the later fade-in was 0 times a fade, which is 0 for good.
  for (const action of Object.values(acts)) {
    action.setEffectiveWeight(0)
    action.play()
  }

  // The anvil stands where the blow lands. Nobody wrote the strike down any
  // more, so find it: run the swing through once and follow the hammer hand
  // to its lowest point.
  acts.working.setEffectiveWeight(1)
  const grip = new THREE.Vector3()
  const hand = figure.getObjectByName(`${HAMMER_HAND}Hand`) ?? figure
  {
    const swing = clipNamed("swing")
    const probe = new THREE.Vector3()
    let lowest = Infinity
    for (let step = 0; step <= 60; step += 1) {
      mixer.setTime((step / 60) * swing.duration)
      figure.updateWorldMatrix(true, true)
      hand.getWorldPosition(probe)
      if (probe.y < lowest) {
        lowest = probe.y
        grip.copy(probe)
      }
    }
    mixer.setTime(0)
  }

  // Just clear of the fist, along the way he faces, so the hammer lands on the
  // face of the anvil rather than through it -- or, as the first guess had it,
  // a foot short of it with the smith punching the air.
  const ahead = new THREE.Vector3(0, 0, 1)
    .applyQuaternion(figure.quaternion)
    .setY(0)
    .normalize()
    .multiplyScalar(0.12)
  bench.position.set(grip.x + ahead.x, 0, grip.z + ahead.z)
  acts.working.setEffectiveWeight(0)
  acts.resting.setEffectiveWeight(1)
  figure.updateWorldMatrix(true, true)

  let hot = false
  let was = -1
  let mode: "working" | "resting" = "resting"
  // For tools/bench.html only: lets the sheet print what the mixer is doing.
  ;(group as any).userData.acts = acts

  return {
    group,

    place(cell: Cell) {
      const at = cellOrigin(cell)
      group.position.set(at.x / PER_UNIT, 0, at.y / PER_UNIT)
    },

    paint(worker: Worker) {
      const pose = figurePose(worker)
      const working = pose === "working"
      hot = lampLit(worker)

      // Cross-fade rather than cut, so a run starting reads as picking the
      // hammer up rather than teleporting it overhead.
      const next = working ? "working" : "resting"
      if (next !== mode) {
        const toward = acts[next]
        const away = acts[mode]
        mode = next
        toward.reset()
        toward.setEffectiveWeight(1)
        away.crossFadeTo(toward, 0.35, false)
      }

      work.visible = hot
      fire.intensity = hot ? 9 : 0
      flame.set(pose === "alarmed" ? "alarmed" : hot ? "burning" : "cold")
      if (pose === "alarmed") {
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
      // Driven by the board's shared clock rather than a Clock of its own, so
      // a filmed replay strikes exactly where the live run did.
      if (was < 0) was = elapsed
      mixer.update((elapsed - was) / 1000)
      was = elapsed

      face?.at(elapsed)

      flame.tick(elapsed)
      if (hot) {
        // firelight is never steady
        fire.intensity = 8 + Math.sin(elapsed / 90) * 1.2 + Math.sin(elapsed / 37) * 0.6
        // and neither is hot iron: the piece breathes between orange and yellow
        const breath = 0.5 + Math.sin(elapsed / 340) * 0.5
        ;(work.material as any).color.copy(iron.cool).lerp(iron.hot, breath)
      }
    },

    dispose() {
      face?.dispose()
      flame.dispose()
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
  const { clone: cloneSkinned } = await import("three/examples/jsm/utils/SkeletonUtils.js")

  const loader = new GLTFLoader()
  loader.setMeshoptDecoder(MeshoptDecoder)
  // The character and both props ride one connection each, in parallel.
  const [gltf, anvilGltf, forgeGltf] = await Promise.all([
    loader.loadAsync(smithUrl),
    loader.loadAsync(anvilUrl),
    loader.loadAsync(forgeUrl),
  ])

  const smith = gltf.scene
  const clips = gltf.animations ?? []
  const props = { anvil: anvilGltf.scene, forge: forgeGltf.scene }
  // Meshy exports around a metre; scale it to the room and stand it on the floor.
  const box = new THREE.Box3().setFromObject(smith)
  const height = box.max.y - box.min.y
  const tall = 1.45
  smith.scale.setScalar(tall / (height || 1))
  smith.position.y = -box.min.y * (tall / (height || 1))

  const renderer = new THREE.WebGLRenderer({ antialias: true })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  renderer.setSize(el.clientWidth, el.clientHeight)
  renderer.setClearColor(0x14120f, 1)
  el.append(renderer.domElement)
  renderer.domElement.classList.add("atelier-canvas")

  const scene = new THREE.Scene()
  // Enough to read the room by; the forge does the rest.
  scene.add(new THREE.AmbientLight(0xb9ab95, 1.5))
  const key = new THREE.DirectionalLight(0xd8cbb2, 2.2)
  key.position.set(4, 8, 6)
  scene.add(key)
  const fill = new THREE.DirectionalLight(0x8fa0bf, 0.8)
  fill.position.set(-5, 3, -4)
  scene.add(fill)

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

  // Names are HTML over the canvas rather than geometry in it: text in a 3D
  // scene either faces the wrong way or costs a texture per label.
  const labels = document.createElement("div")
  labels.className = "atelier-labels"
  el.append(labels)
  const tags = new Map<string, HTMLElement>()

  const tagFor = (flow: string) => {
    let tag = tags.get(flow)
    if (!tag) {
      tag = document.createElement("div")
      tag.className = "atelier-tag"
      tag.innerHTML = `<b></b><span></span>`
      labels.append(tag)
      tags.set(flow, tag)
    }
    return tag
  }

  const placeLabels = () => {
    for (const [flow, bench] of benches) {
      const tag = tags.get(flow)
      if (!tag) continue
      // The room's near corner, so the name sits under the bench rather than
      // across the anvil.
      const at = bench.group.position.clone()
      at.x += 1.3
      at.z += 1.3
      at.project(camera)
      tag.style.left = `${((at.x + 1) / 2) * canvasWidth()}px`
      tag.style.top = `${((-at.y + 1) / 2) * canvasHeight() + 10}px`
    }
  }

  const tidy = document.createElement("button")
  tidy.type = "button"
  tidy.className = "atelier-tidy"
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
    const half = BASE_HALF / zoom
    camera.left = -half * (w / h)
    camera.right = half * (w / h)
    camera.top = half
    camera.bottom = -half
    camera.position.set(10 + centre.x, 10, 10 + centre.y)
    camera.lookAt(centre.x, 0, centre.y)
    camera.updateProjectionMatrix()
    renderer.setSize(w, h, false)
  }

  const canvasWidth = () => el.clientWidth || 1
  const canvasHeight = () => el.clientHeight || 1

  /** Zoom until the room's own corners sit inside the frame. */
  const fitToContent = () => {
    const box3 = new THREE.Box3().setFromObject(room)
    if (box3.isEmpty()) return

    zoom = 1
    frame()
    camera.updateMatrixWorld()

    let wide = 0
    let high = 0
    for (const x of [box3.min.x, box3.max.x]) {
      for (const y of [box3.min.y, box3.max.y]) {
        for (const z of [box3.min.z, box3.max.z]) {
          const at = new THREE.Vector3(x, y, z).applyMatrix4(camera.matrixWorldInverse)
          wide = Math.max(wide, Math.abs(at.x))
          high = Math.max(high, Math.abs(at.y))
        }
      }
    }

    const aspect = canvasWidth() / canvasHeight()
    // 0.88 leaves a margin, and room for the name under each bench.
    zoom = clampZoom(Math.min((BASE_HALF * aspect) / wide, BASE_HALF / high) * 0.88)
  }

  const draw = () => {
    frame()
    renderer.render(scene, camera)
    placeLabels()
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
      const scale = ((BASE_HALF / zoom) * 2) / (canvas.clientHeight || 1)
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
      centre.x = (box.x + box.width / 2) / PER_UNIT
      centre.y = (box.y + box.height / 2) / PER_UNIT

      // Estimating the on-screen extent of an isometric scene is a good way to
      // be wrong twice; ask the camera where the corners land instead.
      fitToContent()
    }

    for (const flow of flows) {
      let bench = benches.get(flow)
      if (!bench) {
        bench = makeBench(THREE, smith, cloneSkinned, stagger(flow), clips, props)
        benches.set(flow, bench)
        room.add(bench.group)
      }
      spots[flow] = arranged[flow]
      if (dragging !== flow) bench.place(arranged[flow])
      bench.paint(stage.workers[flow])

      const worker = stage.workers[flow]
      const tag = tagFor(flow)
      tag.dataset.status = worker.status
      tag.querySelector("b")!.textContent = flow
      tag.querySelector("span")!.textContent = worker.currentNode
        ? `${worker.currentNode}${worker.turn > 0 ? ` · turn ${worker.turn}` : ""}`
        : "idle"
    }

    for (const [flow, tag] of tags) {
      if (!(flow in stage.workers)) {
        tag.remove()
        tags.delete(flow)
      }
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

export const atelier: Skin = {
  id: "atelier",
  label: "Atelier",

  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle {
    let disposed = false
    let latest: StageState | null = null
    let renderer: { update(stage: StageState): void; destroy(): void } | null = null

    const note = document.createElement("p")
    note.className = "atelier-note"
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
