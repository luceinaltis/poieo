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
 *
 * All that repetition is ninety-odd meshes per bench, and nothing in the room
 * ever moves. So the last thing makeCabin does is weld it into a handful of
 * meshes, built once at the origin. The colours -- twenty-odd shades of plank,
 * log and flagstone -- go into the vertices, so a shade is no longer a reason
 * to draw a separate mesh. On a desktop the difference does not show; a phone
 * counts draw calls long before it counts triangles.
 */

/** The footprint the bench already uses; the cabin wraps it exactly. */
const SPAN = 2.6
const WALL_TALL = 2.0

const LOG_RADIUS = 0.115
const PLANK = 0.325

/**
 * Where the logs actually stop, on the two walled sides.
 *
 * The room is open toward the camera and closed behind and to the left, and
 * anything swung inside it has to stay clear of these two lines or it goes
 * through the wall. Exported because the smith's stance is worked out from
 * them rather than nudged until it looked right.
 */
export const INSIDE = -SPAN / 2 + LOG_RADIUS * 2

const WOOD = {
  floor: [0x322818, 0x2d2415, 0x372c1b, 0x2a2113],
  log: [0x42331f, 0x473722, 0x3d2f1c, 0x443521],
  beam: 0x2b2114,
  frame: 0x241b10,
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

/**
 * The attributes every primitive in here carries, and the only ones welding
 * knows how to carry across.
 */
const WELDED = ["position", "normal", "uv"]

/**
 * What actually makes two materials different to draw, once colour has been
 * moved into the vertices. Everything in this room is untextured, so the
 * shade was the only thing keeping most of these meshes apart.
 */
export function likeness(material: any): string {
  return [
    material.type,
    material.roughness,
    material.metalness,
    material.transparent,
    material.opacity,
    material.side,
    material.emissive ? material.emissive.getHexString() : "-",
    material.map ? "textured" : "-",
  ].join("|")
}

/** One piece on its way into a merged geometry. */
export interface Piece {
  index: ArrayLike<number>
  vertices: number
}

/**
 * Write the merged index buffer: each piece's indices point into its own
 * vertices, so they have to be shifted past every vertex that came before.
 *
 * Getting this wrong does not throw. It draws triangles between corners of
 * different planks, and the room comes out as a spray of shards -- which is
 * why it is a function with a test rather than two nested loops in the middle
 * of another one.
 */
export function threaded(into: { [i: number]: number }, pieces: Piece[]): void {
  let at = 0
  let base = 0
  for (const piece of pieces) {
    for (let i = 0; i < piece.index.length; i += 1) into[at + i] = piece.index[i] + base
    at += piece.index.length
    base += piece.vertices
  }
}

/**
 * One geometry from many, or nothing if any of them is not the plain indexed
 * primitive this expects. Nothing is not a failure -- the caller keeps the
 * room it already has, which draws slowly and correctly.
 */
function weld(THREE: any, pieces: any[]): any {
  let vertices = 0
  let indices = 0
  for (const piece of pieces) {
    if (!piece.index) return null
    for (const name of WELDED) {
      const attribute = piece.attributes[name]
      // Interleaved or packed attributes cannot be copied straight across,
      // and no primitive built here produces one.
      if (!attribute || attribute.isInterleavedBufferAttribute) return null
      if (!(attribute.array instanceof Float32Array)) return null
      if (attribute.itemSize !== pieces[0].attributes[name].itemSize) return null
    }
    vertices += piece.attributes.position.count
    indices += piece.index.count
  }

  const merged = new THREE.BufferGeometry()
  for (const name of WELDED.concat(pieces[0].attributes.color ? ["color"] : [])) {
    const width = pieces[0].attributes[name].itemSize
    const all = new Float32Array(vertices * width)
    let at = 0
    for (const piece of pieces) {
      all.set(piece.attributes[name].array, at)
      at += piece.attributes[name].count * width
    }
    merged.setAttribute(name, new THREE.BufferAttribute(all, width))
  }

  const index = vertices > 65535 ? new Uint32Array(indices) : new Uint16Array(indices)
  threaded(
    index,
    pieces.map((piece: any) => ({
      index: piece.index.array,
      vertices: piece.attributes.position.count,
    })),
  )
  merged.setIndex(new THREE.BufferAttribute(index, 1))
  return merged
}

/**
 * Collapse a group of static meshes into one mesh per material, in place.
 *
 * Each part's own transform is baked into its vertices first, which is what
 * lets them share a mesh at all -- and is why this only works on a room that
 * never moves a plank again.
 */
function fuse(THREE: any, room: any): void {
  room.updateMatrixWorld(true)
  const parts: any[] = []
  room.traverse((piece: any) => {
    if (piece.isMesh && !Array.isArray(piece.material)) parts.push(piece)
  })

  const byLikeness = new Map<string, { material: any; pieces: any[] }>()
  for (const part of parts) {
    const baked = part.geometry.clone().applyMatrix4(part.matrixWorld)
    // The part's own colour, written once per vertex, so the merged mesh can
    // keep twenty shades of plank under one material.
    const count = baked.attributes.position.count
    const shade = new Float32Array(count * 3)
    const { r, g, b } = part.material.color ?? { r: 1, g: 1, b: 1 }
    for (let v = 0; v < count; v += 1) shade.set([r, g, b], v * 3)
    baked.setAttribute("color", new THREE.BufferAttribute(shade, 3))

    const key = likeness(part.material)
    const already = byLikeness.get(key)
    if (already) already.pieces.push(baked)
    else byLikeness.set(key, { material: part.material, pieces: [baked] })
  }

  const welded: any[] = []
  for (const { material, pieces } of byLikeness.values()) {
    const merged = weld(THREE, pieces)
    if (!merged) return
    const shared = material.clone()
    shared.vertexColors = true
    // White, because the shade now arrives per vertex and three multiplies
    // the two together.
    if (shared.color) shared.color.setRGB(1, 1, 1)
    welded.push(new THREE.Mesh(merged, shared))
  }

  // Shared between many parts, so disposing twice is normal and harmless.
  for (const part of parts) part.geometry.dispose()
  room.clear()
  for (const mesh of welded) room.add(mesh)
}

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
  // Shuttered, not glazed: cottage glass was half of why the room read as a
  // holiday hut. A crack of night shows between the boards.
  const night = new THREE.Mesh(
    new THREE.PlaneGeometry(0.46, 0.46),
    new THREE.MeshBasicMaterial({ color: WOOD.pane }),
  )
  const shutters = new THREE.Group()
  for (const side of [-1, 1]) {
    const shutter = new THREE.Mesh(new THREE.BoxGeometry(0.2, 0.48, 0.03), frame)
    shutter.position.set(side * 0.125, 0, 0.02)
    shutters.add(shutter)
    const strap = new THREE.Mesh(new THREE.BoxGeometry(0.16, 0.03, 0.035), frame)
    strap.position.set(side * 0.125, 0.12, 0.025)
    shutters.add(strap)
  }
  window_.add(acrossTop, acrossBottom, upLeft, upRight, night, shutters)
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

  // -- the clutter that says work happens here ---------------------------------

  const darkWood = new THREE.MeshStandardMaterial({ color: 0x3a2d1c, roughness: 1 })

  // A workbench against the side wall, heavy top on post legs, tools on it.
  const benchTable = new THREE.Group()
  // Clear of the wall face, which sits at x -1.01: the first placement put
  // half the bench inside the logs.
  benchTable.position.set(-0.82, 0, 0.35)
  const top = new THREE.Mesh(new THREE.BoxGeometry(0.42, 0.07, 1.05), darkWood)
  top.position.y = 0.52
  benchTable.add(top)
  for (const [dx, dz] of [[-0.15, -0.44], [0.15, -0.44], [-0.15, 0.44], [0.15, 0.44]]) {
    const leg = new THREE.Mesh(new THREE.BoxGeometry(0.07, 0.5, 0.07), darkWood)
    leg.position.set(dx, 0.25, dz)
    benchTable.add(leg)
  }
  // work on the bench: a bar, an offcut, a mallet head
  const strewn = [
    { size: [0.3, 0.03, 0.04], at: [0.02, 0.57, -0.2], turn: 0.4 },
    { size: [0.1, 0.05, 0.05], at: [-0.06, 0.58, 0.18], turn: -0.2 },
    { size: [0.16, 0.045, 0.045], at: [0.08, 0.58, 0.34], turn: 1.2 },
  ]
  for (const piece of strewn) {
    const bit = new THREE.Mesh(new THREE.BoxGeometry(...piece.size), ironWare)
    bit.position.set(...(piece.at as [number, number, number]))
    bit.rotation.y = piece.turn
    benchTable.add(bit)
  }
  cabin.add(benchTable)

  // Iron stock leaning on the back wall, right of the shelf.
  for (let i = 0; i < 4; i += 1) {
    const bar = new THREE.Mesh(
      new THREE.CylinderGeometry(0.014, 0.014, 1.15, 5),
      ironWare,
    )
    bar.position.set(1.05 + i * 0.07, 0.55, -1.12 + drift(i * 3) * 0.05)
    bar.rotation.z = 0.28 + (drift(i * 7 + 2) - 0.5) * 0.1
    bar.rotation.y = drift(i * 5) * 0.4
    cabin.add(bar)
  }

  // The coal heap by the forge: a low mound of dark lumps.
  const coal = new THREE.MeshStandardMaterial({ color: 0x191612, roughness: 1 })
  for (let i = 0; i < 7; i += 1) {
    const lump = new THREE.Mesh(new THREE.SphereGeometry(0.09 + drift(i) * 0.05, 6, 5), coal)
    // Beside the hearth's mouth, on the flags, where it can be seen -- the
    // first heap hid behind the forge's own stonework.
    lump.position.set(
      0.05 + drift(i * 3 + 1) * 0.3,
      0.05,
      -0.62 + drift(i * 5 + 2) * 0.2,
    )
    lump.scale.y = 0.55
    cabin.add(lump)
  }

  // Dropped work by the anvil: a horseshoe and a hammer someone will trip on.
  const flatShoe = new THREE.Mesh(shoe, ironWare)
  flatShoe.rotation.x = -Math.PI / 2
  flatShoe.position.set(0.5, 0.11, 0.55)
  cabin.add(flatShoe)
  const droppedHandle = new THREE.Mesh(
    new THREE.CylinderGeometry(0.016, 0.02, 0.3, 6),
    darkWood,
  )
  droppedHandle.rotation.set(Math.PI / 2, 0, 0.8)
  droppedHandle.position.set(-0.5, 0.12, 0.9)
  cabin.add(droppedHandle)

  // Soot shadows worked into the boards around the fire and the anvil.
  const grime = new THREE.MeshBasicMaterial({
    color: 0x0d0a07,
    transparent: true,
    opacity: 0.35,
  })
  for (const stain of [
    { r: 0.6, x: -0.55, z: -0.75 },
    { r: 0.42, x: 0.1, z: 0.35 },
    { r: 0.3, x: 0.7, z: -0.3 },
  ]) {
    const mark = new THREE.Mesh(new THREE.CircleGeometry(stain.r, 14), grime)
    mark.rotation.x = -Math.PI / 2
    mark.position.set(stain.x, 0.015, stain.z)
    cabin.add(mark)
  }

  fuse(THREE, cabin)
  return cabin
}
