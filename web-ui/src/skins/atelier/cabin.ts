/**
 * The room itself: a log cabin, built from primitives.
 *
 * The walls were flat dark boxes and the floor one slab -- a stage, not a
 * place. A cabin is mostly repetition: planks side by side, logs stacked in
 * courses, and repetition is what primitives are good at. Nothing here is
 * downloaded; the whole room costs a few hundred triangles and no bytes.
 *
 * Variation is hashed from each part's index, never drawn from Math.random,
 * so every bench builds the same cabin every time and replays match live.
 */

/** The footprint the bench already uses; the cabin wraps it exactly. */
const SPAN = 2.6
const WALL_TALL = 2.0

const LOG_RADIUS = 0.115
const PLANK = 0.325

const WOOD = {
  floor: [0x4a3b28, 0x453723, 0x50402c, 0x42351f],
  log: [0x574430, 0x5d4a34, 0x52402b, 0x5a4732],
  beam: 0x3d2f1e,
  frame: 0x33281a,
  pane: 0x1a2028,
}

/** A steady pseudo-random in [0, 1), from an index rather than a die. */
const drift = (seed: number) => {
  const turned = Math.sin(seed * 127.1 + 311.7) * 43758.5453
  return turned - Math.floor(turned)
}

/**
 * Build the cabin: plank floor, two log walls with crossed corner ends, top
 * plates, and a shuttered window. Returns a group standing on y = 0.
 */
export function makeCabin(THREE: any): any {
  const cabin = new THREE.Group()

  const woods = WOOD.log.map(
    (color) => new THREE.MeshStandardMaterial({ color, roughness: 0.95 }),
  )
  const floors = WOOD.floor.map(
    (color) => new THREE.MeshStandardMaterial({ color, roughness: 0.9 }),
  )

  // -- the floor, plank by plank, running toward the camera
  const plankShape = new THREE.BoxGeometry(PLANK * 0.94, 0.1, SPAN)
  const planks = Math.round(SPAN / PLANK)
  for (let i = 0; i < planks; i += 1) {
    const plank = new THREE.Mesh(plankShape, floors[Math.floor(drift(i) * floors.length)])
    plank.position.set(-SPAN / 2 + PLANK * (i + 0.5), -0.05, 0)
    cabin.add(plank)
  }

  // -- log walls: horizontal courses, alternating overshoot at the corner the
  // way real cabin logs cross
  const logShape = new THREE.CylinderGeometry(LOG_RADIUS, LOG_RADIUS, 1, 9)
  logShape.rotateZ(Math.PI / 2)
  const courses = Math.ceil(WALL_TALL / (LOG_RADIUS * 2))
  for (let i = 0; i < courses; i += 1) {
    const y = LOG_RADIUS + i * LOG_RADIUS * 2
    const wood = woods[Math.floor(drift(i * 7 + 3) * woods.length)]

    // back wall, along x; every other course pokes past the corner
    const back = new THREE.Mesh(logShape, wood)
    back.scale.x = SPAN + (i % 2 ? 0.24 : 0)
    back.position.set(i % 2 ? -0.12 : 0, y, -SPAN / 2 + LOG_RADIUS)
    // a hair of bow per course, so the wall is not machine-flat
    back.position.z += (drift(i * 13 + 1) - 0.5) * 0.02
    cabin.add(back)

    const side = new THREE.Mesh(logShape, woods[Math.floor(drift(i * 11 + 5) * woods.length)])
    side.rotation.y = Math.PI / 2
    side.scale.x = SPAN + (i % 2 ? 0 : 0.24)
    side.position.set(-SPAN / 2 + LOG_RADIUS, y, i % 2 ? 0 : -0.12)
    side.position.x += (drift(i * 17 + 9) - 0.5) * 0.02
    cabin.add(side)
  }

  // -- top plates: squared beams capping each wall
  const plate = new THREE.MeshStandardMaterial({ color: WOOD.beam, roughness: 0.9 })
  const backPlate = new THREE.Mesh(new THREE.BoxGeometry(SPAN + 0.3, 0.16, 0.3), plate)
  backPlate.position.set(0, WALL_TALL + 0.08, -SPAN / 2 + LOG_RADIUS)
  cabin.add(backPlate)
  const sidePlate = new THREE.Mesh(new THREE.BoxGeometry(0.3, 0.16, SPAN + 0.3), plate)
  sidePlate.position.set(-SPAN / 2 + LOG_RADIUS, WALL_TALL + 0.08, 0)
  cabin.add(sidePlate)

  // -- a window in the side wall, framed proud of the logs the way a cabin
  // window sits. Not the back wall: the shelf of finished work hangs there.
  const window_ = new THREE.Group()
  window_.position.set(-SPAN / 2 + LOG_RADIUS * 2 + 0.01, 1.3, 0.55)
  window_.rotation.y = Math.PI / 2
  const frame = new THREE.MeshStandardMaterial({ color: WOOD.frame, roughness: 0.9 })
  const acrossTop = new THREE.Mesh(new THREE.BoxGeometry(0.56, 0.07, 0.07), frame)
  acrossTop.position.y = 0.245
  const acrossBottom = acrossTop.clone()
  acrossBottom.position.y = -0.245
  const upLeft = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.56, 0.07), frame)
  upLeft.position.x = -0.245
  const upRight = upLeft.clone()
  upRight.position.x = 0.245
  const pane = new THREE.Mesh(
    new THREE.PlaneGeometry(0.46, 0.46),
    new THREE.MeshBasicMaterial({ color: WOOD.pane }),
  )
  const mullion = new THREE.Mesh(new THREE.BoxGeometry(0.035, 0.5, 0.04), frame)
  const transom = new THREE.Mesh(new THREE.BoxGeometry(0.5, 0.035, 0.04), frame)
  window_.add(acrossTop, acrossBottom, upLeft, upRight, pane, mullion, transom)
  cabin.add(window_)

  // -- a shelf board on the back wall, where the finished work stacks up
  const board = new THREE.Mesh(new THREE.BoxGeometry(1.0, 0.05, 0.24), plate)
  board.position.set(0.82, 1.08, -SPAN / 2 + LOG_RADIUS * 2 + 0.1)
  cabin.add(board)
  for (const at of [0.45, 1.2]) {
    const bracket = new THREE.Mesh(new THREE.BoxGeometry(0.05, 0.18, 0.18), plate)
    bracket.position.set(at, 0.96, -SPAN / 2 + LOG_RADIUS * 2 + 0.08)
    cabin.add(bracket)
  }

  return cabin
}
