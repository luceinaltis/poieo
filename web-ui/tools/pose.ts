/**
 * A pose sheet: the swing laid out as stills, big and lit, so it can be judged.
 *
 * The workshop shows the smith small, dark, and at an angle -- fine to watch,
 * useless to diagnose. This page renders the same pose code (imported, not
 * copied, from the skin) at several points through the swing, from the side and
 * from the front, and prints the joint angles under each. A screenshot of it is
 * the keyframe sheet an animator would flip through.
 *
 * Not part of the app: vite builds `index.html` only, so this is a dev-server
 * page that ships nowhere.
 */

import * as THREE from "three"
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js"
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js"

import { EYE, LID, headFrame, makeFace } from "../src/skins/atelier/face"
import smithUrl from "../src/skins/atelier/smith.glb?url"
import type { Tuning } from "../src/skins/atelier/pose"
import {
  ELBOW,
  HAMMER_HAND,
  LEAN,
  SHOULDER,
  SWING_AXIS,
  TONG_ELBOW,
  TONG_SHOULDER,
  poseAt,
  riggingOf,
} from "../src/skins/atelier/pose"

/** Where through the swing to take a still. 0 is raised, 1 is struck. */
const PHASES = [0, 0.25, 0.5, 0.75, 1]

const TILE = 300

/**
 * Every joint is a knob on the query string, so a candidate swing can be shot
 * and compared without the skin being edited between runs:
 *
 *   ?shoulder=-2,0.05&elbow=-1.2,-0.35&lean=-0.05,0.35&tongs=0.55,-1.1&axis=1,0,0
 *
 * Angles are radians, matching the skin's own constants, so a sheet that looks
 * right can be copied straight into pose.ts.
 */
const asked = new URLSearchParams(location.search)

const numbers = (key: string) => asked.get(key)?.split(",").map(Number)

const spanOf = (key: string, fallback: { raised: number; struck: number }) => {
  const pair = numbers(key)
  return pair?.length === 2 ? { raised: pair[0], struck: pair[1] } : fallback
}

const tongs = numbers("tongs")
const axisAsked = numbers("axis")

const tuning: Required<Tuning> = {
  shoulder: spanOf("shoulder", SHOULDER),
  elbow: spanOf("elbow", ELBOW),
  lean: spanOf("lean", LEAN),
  tongShoulder: tongs?.[0] ?? TONG_SHOULDER,
  tongElbow: tongs?.[1] ?? TONG_ELBOW,
  axis:
    axisAsked?.length === 3
      ? { x: axisAsked[0], y: axisAsked[1], z: axisAsked[2] }
      : SWING_AXIS,
}

/**
 * Ways to look. The swing is judged across and down it; the face gets its own
 * close-up, because eyelids hung on a head bone are a millimetre problem and
 * invisible at figure scale.
 */
const VIEWS = [
  { name: "profile", from: new THREE.Vector3(1, 0.18, 0), close: false },
  { name: "front", from: new THREE.Vector3(0, 0.18, 1), close: false },
  { name: "face", from: new THREE.Vector3(0.35, 0.1, 1), close: true },
]

/** A moment the lids are certainly open, for every row but the close-up. */
const SHUT_LATER = 1000

const canvas = document.querySelector("canvas") as HTMLCanvasElement
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
renderer.setPixelRatio(2)
renderer.setSize(TILE * PHASES.length, TILE * VIEWS.length)
renderer.setScissorTest(true)

const scene = new THREE.Scene()
scene.background = new THREE.Color(0x14110d)
// Deliberately flat and bright. The workshop's firelight is atmosphere; here
// the only job is to see where the limbs are.
scene.add(new THREE.HemisphereLight(0xffffff, 0x554433, 2.2))
const key = new THREE.DirectionalLight(0xffffff, 2.0)
key.position.set(2, 3, 2)
scene.add(key)
const fill = new THREE.DirectionalLight(0xffe0c0, 1.0)
fill.position.set(-2, 1, -2)
scene.add(fill)

const loader = new GLTFLoader()
loader.setMeshoptDecoder(MeshoptDecoder)
const gltf = await loader.loadAsync(smithUrl)
const figure = gltf.scene
scene.add(figure)

const rig = riggingOf(figure)
// The lids blink on a schedule; the sheet shows them shut in every still, since
// a still of an open eye says nothing about where they were put.
const eyeAsked = numbers("eye")
const lidAsked = numbers("lid")
const placing = {
  eye:
    eyeAsked?.length === 3
      ? { up: eyeAsked[0], out: eyeAsked[1], forward: eyeAsked[2] }
      : EYE,
  lid: lidAsked?.length === 2 ? { wide: lidAsked[0], tall: lidAsked[1] } : LID,
}
const face = makeFace(THREE, figure, 0, placing)

// Frame the figure once, from its own size, so a re-rigged model still fits.
poseAt(THREE, figure, rig, 0.5, tuning)
figure.updateWorldMatrix(true, true)
const box = new THREE.Box3().setFromObject(figure)
const middle = box.getCenter(new THREE.Vector3())
const span = box.getSize(new THREE.Vector3())
// A swinging arm reaches past the resting silhouette, so leave room for it.
const reach = Math.max(span.x, span.y, span.z) * 1.35

/** A hard floor line, so a lean reads as a lean and not as the whole body sliding. */
const grid = new THREE.GridHelper(reach * 2, 12, 0x4a4034, 0x2a241d)
grid.position.y = box.min.y
scene.add(grid)

// Where the head is, for the close-up. Measured, not assumed: a re-generated
// character is a different height.
const skull = headFrame(THREE, figure)
const headAt = skull ? skull.centre.clone() : middle.clone()
const headSpan = skull ? skull.tall * 1.5 : reach

const camera = new THREE.OrthographicCamera(-reach / 2, reach / 2, reach / 2, -reach / 2, 0.01, 100)

const angles = document.getElementById("angles") as HTMLElement
angles.style.gridTemplateColumns = `repeat(${PHASES.length}, ${TILE}px)`
angles.style.width = `${TILE * PHASES.length}px`

const degrees = (radians: number) => `${Math.round((radians * 180) / Math.PI)}°`
const between = (s: { raised: number; struck: number }, t: number) =>
  s.raised + (s.struck - s.raised) * t

for (const [column, through] of PHASES.entries()) {
  for (const [row, view] of VIEWS.entries()) {
    poseAt(THREE, figure, rig, through, tuning)
    face?.at(view.close ? 0 : SHUT_LATER)

    const at = view.close ? headAt : middle
    const wide = view.close ? headSpan : reach
    camera.left = -wide / 2
    camera.right = wide / 2
    camera.top = wide / 2
    camera.bottom = -wide / 2
    camera.updateProjectionMatrix()
    camera.position.copy(view.from).normalize().multiplyScalar(reach).add(at)
    camera.lookAt(at)

    // Tiles are given in CSS pixels: three scales them by the pixel ratio
    // itself, and doubling them here draws each still over its neighbours.
    const x = column * TILE
    // WebGL counts rows from the bottom; the sheet reads top-down.
    const y = (VIEWS.length - 1 - row) * TILE
    renderer.setViewport(x, y, TILE, TILE)
    renderer.setScissor(x, y, TILE, TILE)
    renderer.render(scene, camera)
  }

  const cell = document.createElement("div")
  cell.innerHTML =
    `<b>${through.toFixed(2)}</b>` +
    [
      `${HAMMER_HAND.toLowerCase()} shoulder ${degrees(between(tuning.shoulder, through))}`,
      `elbow ${degrees(between(tuning.elbow, through))}`,
      `lean ${degrees(between(tuning.lean, through))}`,
    ].join("\n")
  angles.append(cell)
}

// Playwright waits on this rather than on a timer.
// Say what was drawn, so a sheet found later is not a mystery.
document.querySelector("h1")!.textContent +=
  ` — axis ${tuning.axis.x},${tuning.axis.y},${tuning.axis.z}` +
  ` · tongs ${tuning.tongShoulder},${tuning.tongElbow}` +
  ` · eye ${Object.values(placing.eye).join(",")}` +
  ` lid ${Object.values(placing.lid).join(",")}`

// Playwright waits on this rather than on a timer.
document.body.dataset.ready = "yes"
