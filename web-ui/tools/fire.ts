/** The forge flame by itself, big, at several moments: judged before shipping. */

import * as THREE from "three"

import { makeFire } from "../src/skins/atelier/fire"

const MOMENTS = [0, 400, 800, 1300]
const TILE = 320

const canvas = document.querySelector("canvas") as HTMLCanvasElement
const renderer = new THREE.WebGLRenderer({ canvas, antialias: true })
renderer.setPixelRatio(2)
renderer.setSize(TILE * MOMENTS.length, TILE)
renderer.setScissorTest(true)
renderer.setClearColor(0x14120f, 1)

const scene = new THREE.Scene()
scene.add(new THREE.AmbientLight(0xb9ab95, 1.2))

// A sill under it, so scale and grounding can be judged.
const sill = new THREE.Mesh(
  new THREE.BoxGeometry(0.9, 0.08, 0.5),
  new THREE.MeshStandardMaterial({ color: 0x38322a, roughness: 1 }),
)
sill.position.y = -0.04
scene.add(sill)

const fire = makeFire(THREE, 0.5, 0.62)
fire.set("burning")
scene.add(fire.group)

const camera = new THREE.OrthographicCamera(-0.55, 0.55, 0.8, -0.3, -10, 10)
camera.position.set(2, 1, 2)
camera.lookAt(0, 0.25, 0)

for (const [index, moment] of MOMENTS.entries()) {
  fire.tick(moment)
  renderer.setViewport(index * TILE, 0, TILE, TILE)
  renderer.setScissor(index * TILE, 0, TILE, TILE)
  renderer.render(scene, camera)
}

document.body.dataset.ready = "yes"
