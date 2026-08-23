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

import { makeBench } from "../src/skins/atelier/index"
import { HAMMER, hammerAngle } from "../src/skins/atelier/scene"
import smithUrl from "../src/skins/atelier/smith.glb?url"
import { NOTHING } from "../src/review/rollup"
import type { Worker } from "../src/state/stage"

/** One hammer cycle is 900ms; sample it evenly. */
const PERIOD = 900
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
const gltf = await loader.loadAsync(smithUrl)
const smith = gltf.scene

// Same sizing the skin does: the model exports around a metre, the room wants
// a person, and he has to stand on the floor rather than in it.
const box = new THREE.Box3().setFromObject(smith)
const tall = 1.45
const scale = tall / (box.max.y - box.min.y || 1)
smith.scale.setScalar(scale)
smith.position.y = -box.min.y * scale

const bench = makeBench(THREE, smith, cloneSkinned, 0)
scene.add(bench.group)

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

for (let frame = 0; frame < FRAMES; frame += 1) {
  const elapsed = (frame * PERIOD) / FRAMES
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
  // What the skin is actually asking for at this moment, so a swing that looks
  // short can be told apart from a swing that is never asked to go far.
  const through =
    (hammerAngle(elapsed) - HAMMER.raised) / (HAMMER.struck - HAMMER.raised)
  cell.innerHTML =
    `<b>${Math.round(elapsed)} ms</b>through ${through.toFixed(2)}\n` +
    `${through < 0.5 ? "raising" : "striking"}`
  marks.append(cell)
}

// Playwright waits on this rather than on a timer.
document.body.dataset.ready = "yes"
