/**
 * A strike, as the room actually shows it.
 *
 * pose.html judges the smith on his own, and that is how a swing that misses
 * the anvil by half a metre got signed off: a figure with nothing to hit looks
 * fine doing anything. This builds the real bench -- the same makeBench the
 * skin calls, with its anvil, its forge and its work -- and photographs one
 * whole strike through the workshop's own isometric camera.
 *
 * Two rows: the room's view, and the same moment from the side, where a hammer
 * that lands short is obvious.
 *
 * Not part of the app: vite builds `index.html` only.
 */

import * as THREE from "three"
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js"
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js"
import { clone as cloneSkinned } from "three/examples/jsm/utils/SkeletonUtils.js"

import { makeBench, standAnvil, turnAnvil, turnFigure } from "../src/skins/atelier/index"
import { SPARK_LIFE } from "../src/skins/atelier/strike"
import anvilUrl from "../src/skins/atelier/anvil.glb?url"
import forgeUrl from "../src/skins/atelier/forge.glb?url"
import hammerUrl from "../src/skins/atelier/hammer.glb?url"
import smithUrl from "../src/skins/atelier/smith.glb?url"
import { NOTHING } from "../src/review/rollup"
import type { Worker } from "../src/state/stage"

const FRAMES = 8

const TILE = 300

/**
 * The smith stands turned a quarter into the room, so a profile of him is not
 * a profile of the scene: looking down the room's x axis shows his front, where
 * a swing is foreshortened into almost nothing.
 */
const VIEWS = [
  { name: "the room", from: new THREE.Vector3(10, 10, 10) },
  { name: "across the swing", from: new THREE.Vector3(0, 2.5, 14) },
  // Straight down, where "which way does he face" stops being a matter of
  // squinting at an isometric view. The nudge off vertical keeps lookAt sane.
  { name: "from above", from: new THREE.Vector3(0.01, 14, 0.01) },
]

const canvas = document.querySelector("canvas") as HTMLCanvasElement
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
renderer.setPixelRatio(2)
renderer.setSize(TILE * FRAMES, TILE * VIEWS.length)
renderer.setScissorTest(true)
renderer.setClearColor(0x14120f, 1)

const scene = new THREE.Scene()
// The workshop's own lights, so the forge reads the way it does on the board.
scene.add(new THREE.AmbientLight(0xb9ab95, 1.5))
const key = new THREE.DirectionalLight(0xd8cbb2, 2.2)
key.position.set(4, 8, 6)
scene.add(key)
const fill = new THREE.DirectionalLight(0x8fa0bf, 0.8)
fill.position.set(-5, 3, -4)
scene.add(fill)

const loader = new GLTFLoader()
loader.setMeshoptDecoder(MeshoptDecoder)
const [gltf, anvilGltf, forgeGltf, hammerGltf] = await Promise.all([
  loader.loadAsync(smithUrl),
  loader.loadAsync(anvilUrl),
  loader.loadAsync(forgeUrl),
  loader.loadAsync(hammerUrl),
])
const smith = gltf.scene

// Same sizing the skin does: the model exports around a metre, the room wants
// a person, and he has to stand on the floor rather than in it.
const box = new THREE.Box3().setFromObject(smith)
const tall = 1.45
const scale = tall / (box.max.y - box.min.y || 1)
smith.scale.setScalar(scale)
smith.position.y = -box.min.y * scale

// `?anvil=90` and `?facing=45` (degrees) photograph candidate orientations.
const asked = new URLSearchParams(location.search)
const anvilAsked = asked.get("anvil")
if (anvilAsked !== null) turnAnvil((Number(anvilAsked) * Math.PI) / 180)
const facingAsked = asked.get("facing")
if (facingAsked !== null) turnFigure((Number(facingAsked) * Math.PI) / 180)
// `?face=0.3` puts the anvil's face at a candidate height, which is the one
// number that decides whether the hammer lands on it or sails past it.
const faceAsked = asked.get("face")
if (faceAsked !== null) standAnvil(Number(faceAsked))

const bench = makeBench(THREE, smith, cloneSkinned, 0, gltf.animations ?? [], {
  anvil: anvilGltf.scene,
  forge: forgeGltf.scene,
  hammer: hammerGltf.scene,
})

/** One whole strike, whatever the clip's own length is. */
const swingClip = (gltf.animations ?? []).find((c) => c.name === "swing")
const PERIOD = (swingClip?.duration ?? 0.9) * 1000
scene.add(bench.group)

// Which way is he actually facing? Painted on the floor rather than reasoned
// about: a green arrow out of the figure's own forward, red/blue for the
// world's x and z. The last argument about axes went three rounds and lost.
{
  // The figure is the bench child that has bones in it; climb from a skinned
  // mesh to the node the skin actually rotated.
  const skinned = bench.group.getObjectByProperty("type", "SkinnedMesh")!
  let body: any = skinned
  while (body.parent && body.parent !== bench.group) body = body.parent
  body.updateWorldMatrix(true, false)
  const forward = new THREE.Vector3(0, 0, 1)
    .applyQuaternion(new THREE.Quaternion().setFromRotationMatrix(body.matrixWorld))
    .setY(0)
    .normalize()
  const from = new THREE.Vector3().setFromMatrixPosition(body.matrixWorld).setY(0.02)
  scene.add(new THREE.ArrowHelper(forward, from, 0.9, 0x44ff44, 0.2, 0.12))
  scene.add(new THREE.ArrowHelper(new THREE.Vector3(1, 0, 0), new THREE.Vector3(0, 0.02, 0), 0.6, 0xff5555))
  scene.add(new THREE.ArrowHelper(new THREE.Vector3(0, 0, 1), new THREE.Vector3(0, 0.02, 0), 0.6, 0x5588ff))
}

/** A flow in the middle of a run, which is when the hammer moves. */
const running: Worker = {
  status: "running",
  currentNode: "forge",
  nodeType: "llm",
  step: 3,
  turn: 1,
  lastText: "",
  lastThinking: "",
  recentToolCalls: [],
  lastRun: null,
  recent: NOTHING,
  tracked: true,
}
bench.paint(running)

const camera = new THREE.OrthographicCamera(-1.6, 1.6, 1.6, -1.6, -100, 100)
const middle = new THREE.Vector3(0, 0.9, 0)

const marks = document.getElementById("marks") as HTMLElement
marks.style.gridTemplateColumns = `repeat(${FRAMES}, ${TILE}px)`
marks.style.width = `${TILE * FRAMES}px`

// The last frame is pinned just after the blow, where the sparks live; a
// even sampling of a 1.9 s clip misses a 0.28 s burst more often than not.
const strikeAt = (bench.group as any).userData.strikeAt as number
// The clips run below full speed; the pin has to convert clip seconds into
// wall-clock milliseconds through the working action's own time scale.
const pace = (bench.group as any).userData.acts.working.getEffectiveTimeScale()
// `?strike` spends the whole sheet on the blow instead, for judging the flash
// and the sparks: from just before the hit to the last ember going out. The
// span comes from the skin's own SPARK_LIFE, so lengthening the burst widens
// the sheet with it rather than quietly cropping it.
const aroundStrike = asked.get("strike") !== null
const BURST = SPARK_LIFE + 0.1
// The mixer is delta-driven and its first tick counts as zero: without this
// priming tick at t=0, a sheet whose first frame starts mid-clip quietly
// renders the wrong moments -- which is how a flash probe measured the
// recovery crouch and called the flash invisible.
bench.tick(0)
for (let frame = 0; frame < FRAMES; frame += 1) {
  const elapsed = aroundStrike
    ? (strikeAt / pace - 0.05 + (frame * BURST) / (FRAMES - 1)) * 1000
    : frame === FRAMES - 1
      ? ((strikeAt + 0.07) / pace) * 1000
      : (frame * PERIOD) / FRAMES / pace
  bench.tick(elapsed)

  for (const [row, view] of VIEWS.entries()) {
    camera.position.copy(view.from).add(middle)
    camera.lookAt(middle)

    const x = frame * TILE
    // WebGL counts rows from the bottom; the sheet reads top-down.
    const y = (VIEWS.length - 1 - row) * TILE
    renderer.setViewport(x, y, TILE, TILE)
    renderer.setScissor(x, y, TILE, TILE)
    renderer.render(scene, camera)
  }

  const cell = document.createElement("div")
  const acts = (bench.group as any).userData.acts
  const state = ["working", "resting"]
    .map((name) => `${name[0]} w${acts[name].getEffectiveWeight().toFixed(2)} t${acts[name].time.toFixed(2)}`)
    .join("\n")
  // How bright the embers are and how far the highest has climbed, because a
  // still of a dark room cannot be argued with about either.
  const sparks = (bench.group as any).userData.sparks
  const lit = sparks.visible ? (sparks.children[0].material.opacity as number) : 0
  const top = Math.max(...sparks.children.map((e: any) => e.position.y))
  const wide = sparks.children[0].scale.x as number
  const embers = `sparks o${lit.toFixed(2)} top${top.toFixed(2)} @${wide}`
  cell.innerHTML = `<b>${Math.round(elapsed)} ms</b>${state}\n${embers}`
  marks.append(cell)
}

// The hammer's whole path, printed, because arguing from two stills about
// which dip is the blow has now been wrong twice -- and because the head of
// the hammer and the fist holding it are a forearm apart, which is the width
// of an anvil.
{
  const hand = bench.group.getObjectByName("RightHand")
  const hammer = (bench.group as any).userData.hammer
  const anvilTop = (bench.group as any).userData.anvilTop as number
  if (hand && hammer) {
    const fist = new THREE.Vector3()
    const head = new THREE.Vector3()
    const lines = [
      `anvil face at y${anvilTop.toFixed(3)}`,
      "clip    fist              hammer head       (world units)",
    ]
    let lowest = { y: Infinity, at: 0, x: 0, z: 0 }
    for (let step = 0; step <= 36; step += 1) {
      const t = (step / 36) * (swingClip?.duration ?? 1)
      // Wall-clock in, clip seconds out: tick() takes the room's milliseconds
      // and the clip runs at `pace`, so the labels lied by a third.
      bench.tick((t / pace) * 1000)
      hand.getWorldPosition(fist)
      head.copy(hammer.head)
      hammer.holder.localToWorld(head)
      if (head.y < lowest.y) lowest = { y: head.y, at: t, x: head.x, z: head.z }
      const bar = "#".repeat(Math.max(0, Math.round((head.y - 0.1) * 30)))
      lines.push(
        `${t.toFixed(2)}s  y${fist.y.toFixed(2)} x${fist.x.toFixed(2)} z${fist.z.toFixed(2)}` +
          `   y${head.y.toFixed(2)} x${head.x.toFixed(2)} z${head.z.toFixed(2)} ${bar}`,
      )
    }
    lines.push(
      `the head bottoms out at y${lowest.y.toFixed(3)} (x${lowest.x.toFixed(3)} ` +
        `z${lowest.z.toFixed(3)}) at ${lowest.at.toFixed(2)}s -- ` +
        `${(lowest.y - anvilTop).toFixed(3)} from the anvil face`,
    )
    const sheet = document.createElement("pre")
    sheet.style.cssText = "margin:12px 16px;font-size:12px;line-height:1.25"
    sheet.textContent = lines.join("\n")
    document.body.append(sheet)
  }
}

// Playwright waits on this rather than on a timer.
document.body.dataset.ready = "yes"
