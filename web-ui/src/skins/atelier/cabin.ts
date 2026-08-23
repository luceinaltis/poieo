/**
 * The room itself: a smithy in a log cabin, built from primitives.
 *
 * The walls were flat dark boxes and the floor one slab -- a stage, not a
 * place. A cabin is mostly repetition: planks side by side, logs stacked in
 * courses, and repetition is what primitives are good at. What makes it a
 * smithy rather than a holiday hut is wear: soot climbing the upper courses,
 * stone flags where planks would char, iron hung on the walls. Nothing here
 * is downloaded; the whole room costs a few hundred triangles and no bytes.
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
  floor: [0x3e3222, 0x39301e, 0x443626, 0x352c1a],
  log: [0x4c3c2a, 0x51402c, 0x473826, 0x4e3e2b],
  beam: 0x33281a,
  frame: 0x2c2216,
  pane: 0x1a2028,
}

/** Iron, and the stone the forge stands on. */
const IRON = 0x2e2a26
const FLAG = [0x3a3733, 0x413d38, 0x36332f]

/** How hard the smoke has worked on the top of the wall. */
const SOOT = 0.55

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
  // Smoke lives under the ceiling: each course is dimmer than the one below,
  // so the wall shades from timber at the floor to soot at the plates.
  const sooted = new Map<any, any>()
  const smoke = (material: any, i: number) => {
    const key = `${material.uuid}:${i}`
    if (!sooted.has(key)) {
      const darker = material.clone()
      darker.color.multiplyScalar(1 - (i / courses) * SOOT)
      sooted.set(key, darker)
    }
    return sooted.get(key)
  }
  for (let i = 0; i < courses; i += 1) {
    const y = LOG_RADIUS + i * LOG_RADIUS * 2
    const wood = smoke(woods[Math.floor(drift(i * 7 + 3) * woods.length)], i)

    // back wall, along x; every other course pokes past the corner
    const back = new THREE.Mesh(logShape, wood)
    back.scale.x = SPAN + (i % 2 ? 0.24 : 0)
    back.position.set(i % 2 ? -0.12 : 0, y, -SPAN / 2 + LOG_RADIUS)
    // a hair of bow per course, so the wall is not machine-flat
    back.position.z += (drift(i * 13 + 1) - 0.5) * 0.02
    cabin.add(back)

    const side = new THREE.Mesh(
      logShape,
      smoke(woods[Math.floor(drift(i * 11 + 5) * woods.length)], i),
    )
    side.rotation.y = Math.PI / 2
    side.scale.x = SPAN + (i % 2 ? 0 : 0.24)
    side.position.set(-SPAN / 2 + LOG_RADIUS, y, i % 2 ? 0 : -0.12)
    side.position.x += (drift(i * 17 + 9) - 0.5) * 0.02
    cabin.add(side)
  }

  // -- stone flags where the fire lives: nobody stands a forge on planks.
  // An apron of irregular slabs across the back-left quarter of the floor.
  const flagstones = FLAG.map(
    (color) => new THREE.MeshStandardMaterial({ color, roughness: 1 }),
  )
  let laid = 0
  for (let row = 0; row < 3; row += 1) {
    for (let col = 0; col < 4; col += 1) {
      const wide = 0.42 + drift(laid * 3 + 1) * 0.12
      const deep = 0.38 + drift(laid * 5 + 2) * 0.1
      const slab = new THREE.Mesh(
        new THREE.BoxGeometry(wide, 0.04, deep),
        flagstones[laid % flagstones.length],
      )
      slab.position.set(
        -SPAN / 2 + 0.35 + col * 0.44 + (drift(laid * 7) - 0.5) * 0.05,
        0.02,
        -SPAN / 2 + 0.3 + row * 0.42 + (drift(laid * 11) - 0.5) * 0.05,
      )
      slab.rotation.y = (drift(laid * 13) - 0.5) * 0.12
      cabin.add(slab)
      laid += 1
    }
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

  // -- horseshoes nailed to the side wall: the smithy's own signage
  const shoe = new THREE.TorusGeometry(0.07, 0.02, 6, 10, Math.PI * 1.3)
  const ironWare = new THREE.MeshStandardMaterial({
    color: IRON,
    roughness: 0.6,
    metalness: 0.5,
  })
  for (const [index, at] of [
    { y: 1.62, z: 0.3 },
    { y: 1.55, z: -0.05 },
    { y: 1.66, z: -0.38 },
  ].entries()) {
    const hung = new THREE.Mesh(shoe, ironWare)
    hung.position.set(-SPAN / 2 + LOG_RADIUS * 2 + 0.02, at.y, at.z)
    hung.rotation.y = Math.PI / 2
    hung.rotation.z = Math.PI * 0.85 + (drift(index * 29) - 0.5) * 0.3
    cabin.add(hung)
  }

  // -- the tool rail: a hammer and tongs hung on the side wall. A downloaded
  // rack was tried and weighed 400 kB after every trick; four boxes and two
  // cylinders read the same from an isometric camera and weigh nothing.
  const rail = new THREE.Group()
  rail.position.set(-SPAN / 2 + LOG_RADIUS * 2 + 0.03, 1.18, -0.55)
  rail.rotation.y = Math.PI / 2

  const woodRail = new THREE.Mesh(new THREE.BoxGeometry(0.72, 0.05, 0.05), frame)
  rail.add(woodRail)

  const handleWood = new THREE.MeshStandardMaterial({ color: 0x6b563c, roughness: 0.9 })
  const hammerHead = new THREE.Mesh(new THREE.BoxGeometry(0.13, 0.055, 0.055), ironWare)
  hammerHead.position.set(-0.18, -0.05, 0.01)
  rail.add(hammerHead)
  const hammerHandle = new THREE.Mesh(
    new THREE.CylinderGeometry(0.016, 0.02, 0.3, 6),
    handleWood,
  )
  hammerHandle.position.set(-0.18, -0.21, 0.01)
  rail.add(hammerHandle)

  for (const lean of [-0.06, 0.06]) {
    const jaw = new THREE.Mesh(new THREE.BoxGeometry(0.022, 0.34, 0.022), ironWare)
    jaw.position.set(0.2 + lean, -0.2, 0.01)
    jaw.rotation.z = lean * 2.2
    rail.add(jaw)
  }
  const pivot = new THREE.Mesh(new THREE.CylinderGeometry(0.02, 0.02, 0.03, 6), ironWare)
  pivot.rotation.x = Math.PI / 2
  pivot.position.set(0.2, -0.14, 0.01)
  rail.add(pivot)
  cabin.add(rail)

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
