/**
 * Look at a downloaded prop on its own.
 *
 * There was no way to do this, and it cost: the generator welds a prop into
 * the character's fist, and a 0.15-unit lump with no handle shipped as the
 * smith's hammer for a week because the only place anyone ever saw it was a
 * 300-pixel tile of a dark room, half behind an anvil.
 *
 *   prop.html?of=hammer          the newest thing meshy.py fetched
 *   prop.html?of=anvil&grid=0.1  with a floor ruled in tenths
 *
 * Four views around it, on a ruled floor, with its measured size printed --
 * a prop that is the wrong shape has nowhere left to hide.
 *
 * Not part of the app: vite builds `index.html` only.
 */

import * as THREE from "three"
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js"
import { MeshoptDecoder } from "three/examples/jsm/libs/meshopt_decoder.module.js"

const TILE = 420

/** Around the object and once from above, so nothing is hidden by itself. */
const VIEWS = [
  { name: "front", from: new THREE.Vector3(0, 0.3, 3) },
  { name: "side", from: new THREE.Vector3(3, 0.3, 0) },
  { name: "three quarters", from: new THREE.Vector3(2.2, 1.6, 2.2) },
  { name: "above", from: new THREE.Vector3(0.01, 3, 0.01) },
]

const asked = new URLSearchParams(location.search)
const of = asked.get("of") ?? "hammer"
const ruled = Number(asked.get("grid") ?? 0.1)

// Every glb in the skin's folder, so a new download needs no edit here.
const models = import.meta.glob("../src/skins/atelier/*.glb", {
  query: "?url",
  import: "default",
  eager: true,
}) as Record<string, string>
const url = Object.entries(models).find(([path]) => path.endsWith(`/${of}.glb`))?.[1]

const canvas = document.querySelector("canvas") as HTMLCanvasElement
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
renderer.setPixelRatio(2)
renderer.setSize(TILE * VIEWS.length, TILE)
renderer.setScissorTest(true)
renderer.setClearColor(0x14120f, 1)

const marks = document.getElementById("marks") as HTMLElement
if (!url) {
  marks.textContent = `no ${of}.glb in src/skins/atelier -- have ${Object.keys(models)
    .map((p) => p.split("/").pop())
    .join(", ")}`
  document.body.dataset.ready = "yes"
} else {
  const scene = new THREE.Scene()
  scene.add(new THREE.AmbientLight(0xb9ab95, 1.6))
  const key = new THREE.DirectionalLight(0xd8cbb2, 2.4)
  key.position.set(4, 8, 6)
  scene.add(key)
  const fill = new THREE.DirectionalLight(0x8fa0bf, 0.9)
  fill.position.set(-5, 3, -4)
  scene.add(fill)

  const loader = new GLTFLoader()
  loader.setMeshoptDecoder(MeshoptDecoder)
  const gltf = await loader.loadAsync(url)
  const model = gltf.scene

  // Sized to fill the frame whatever it was exported at, and stood on the
  // floor: a prop's own scale means nothing until it is put next to something.
  const box = new THREE.Box3().setFromObject(model)
  const size = new THREE.Vector3()
  const middle = new THREE.Vector3()
  box.getSize(size)
  box.getCenter(middle)
  const scale = 1.6 / (Math.max(size.x, size.y, size.z) || 1)
  model.scale.setScalar(scale)
  model.position.copy(middle).multiplyScalar(-scale)
  model.position.y += (size.y / 2) * scale
  scene.add(model)

  // A ruled floor in the prop's own units, so "how long is the handle" is read
  // off the picture rather than guessed.
  const squares = Math.ceil(1.6 / (ruled * scale)) * 2
  const grid = new THREE.GridHelper(squares * ruled * scale, squares, 0x6a5c48, 0x342c22)
  scene.add(grid)

  const camera = new THREE.PerspectiveCamera(35, 1, 0.01, 100)
  const look = new THREE.Vector3(0, (size.y / 2) * scale, 0)
  for (const [column, view] of VIEWS.entries()) {
    camera.position.copy(view.from).multiplyScalar(0.9).add(look)
    camera.lookAt(look)
    camera.updateProjectionMatrix()
    renderer.setViewport(column * TILE, 0, TILE, TILE)
    renderer.setScissor(column * TILE, 0, TILE, TILE)
    renderer.render(scene, camera)
  }

  // What it actually is, in its own units: the numbers a later step has to
  // divide by, and the ones that say whether it is hammer-shaped at all.
  let vertices = 0
  let triangles = 0
  model.traverse((node: any) => {
    if (!node.geometry) return
    vertices += node.geometry.attributes.position.count
    triangles += (node.geometry.index?.count ?? node.geometry.attributes.position.count) / 3
  })
  marks.textContent = [
    `${of}.glb`,
    `  ${vertices} vertices, ${Math.round(triangles)} triangles, ` +
      `${gltf.scene.children.length} node(s), ` +
      `${(gltf.parser.json.materials ?? []).length} material(s)`,
    `  measures ${size.x.toFixed(3)} x ${size.y.toFixed(3)} x ${size.z.toFixed(3)} ` +
      `in its own units`,
    `  floor ruled every ${ruled} of those units`,
  ].join("\n")
  document.body.dataset.ready = "yes"
}
