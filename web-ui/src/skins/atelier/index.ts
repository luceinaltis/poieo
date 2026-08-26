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
import { INSIDE, makeCabin } from "./cabin"
import { makeFace } from "./face"
import { makeFire } from "./fire"
import { flexion, sideways, stretcher } from "./reach"
import { figurePose, lampLit, shelfCount } from "./scene"
import {
  REST_PACE,
  SPARKS,
  SPARK_LIFE,
  WORK_PACE,
  flashFade,
  flashSpread,
  lightPower,
  sparkFade,
  spray,
} from "./strike"
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
import { changedWorkers } from "../changed"
import type { Skin, SkinCallbacks, SkinHandle } from "../contract"
import type { StageState, Worker } from "../../state/stage"
import "./atelier.css"
// Imported rather than served from a fixed path, so Vite hashes it into
// /assets with everything else: one cache policy, and a changed model
// reaches the browser instead of sitting stale behind its own name.
import anvilUrl from "./anvil.glb?url"
import forgeUrl from "./forge.glb?url"
import hammerUrl from "./hammer.glb?url"
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

/**
 * How far the anvil's face stands off the floor.
 *
 * The clip Meshy retargeted is a ground-level swing: the hammer head bottoms
 * out at y0.096 and the fist holding it only reaches y0.39, so a face much
 * above that is never actually struck. Height and size used to be the same
 * number -- the model arrives as an anvil on a stump, and standing the whole
 * thing on the floor meant a low face could only be bought by shrinking the
 * iron to a toy.
 *
 * They are separate now. ANVIL_LONG says how big the anvil is and this says
 * how high it stands; the difference goes under the floorboards, where nothing
 * can see it. At 0.38 a hand of stump still shows above the stone, which is
 * what makes it read as an anvil rather than a wedge lying on the floor, and
 * the face is close enough to the blow that the hammer meets it.
 */
export let ANVIL_FACE = 0.38

/** How long the anvil is, nose to heel; its height follows from the model. */
const ANVIL_LONG = 0.92

/** Tool-only override, so bench.html can photograph the candidates. */
export function standAnvil(face: number) {
  ANVIL_FACE = face
}

/** Which hand the model holds its hammer in. */
const HAMMER_HAND = "Right"

/**
 * How long the hammer is, butt to head, in world units. A smith's hand hammer
 * is about a third of a metre and the figure stands 1.45, so this is measured
 * against him rather than against the downloaded prop, which arrives at
 * whatever scale the generator felt like.
 */
const HAMMER_LONG = 0.34

/**
 * How much daylight to leave between the hammer and the log walls.
 *
 * A hammer's length, not a fingernail. The room is closed on two sides and
 * two metres tall, so anything raised overhead is drawn in front of a wall
 * whatever happens -- but at arm's reach from the logs it reads as a hammer
 * in a room, and at a centimetre it reads as a hammer in the wall. The left
 * wall is the one that matters: it carries the shelf and the tool rail, and
 * the backswing goes up behind that shoulder.
 */
const HAMMER_CLEAR = HAMMER_LONG

/**
 * How far a resting upper arm hangs clear of the ribs. A person's is 5 to 10
 * degrees; this rig's idle presses it 9 to 18 degrees the other way.
 */
const ARM_OUT = (8 * Math.PI) / 180

/**
 * How much a resting elbow bends. A person's is 10 to 20 degrees; this rig's
 * idle bends it 45, which crosses the forearms over the belly.
 */
const ELBOW_REST = (15 * Math.PI) / 180

/**
 * How much further out to set this rig's elbow and wrist. 1.33 takes his
 * upper arm from 12% of his height to 16%; a person's is 18% to 19%.
 */
const ARM_STRETCH = 1.33

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
  hammer: any
}

/**
 * How wide a fist is, in the units a bone's own frame counts in.
 *
 * Two spaces, and they are not the same one. Vertices are measured in the
 * mesh's units -- this figure is 1.70 of them tall -- and then carried into a
 * bone's frame, which on a rig exported from centimetres is a hundred times
 * larger. Comparing a distance in one against a radius from the other quietly
 * matches nothing at all: `fistOf` fell back to the wrist on this character
 * for as long as he has been in the room, and it took printing the numbers to
 * see it, because a silent fallback looks exactly like a slightly wrong grip.
 */
function fistReach(THREE: Three, mesh: any, intoBone: any): number {
  mesh.geometry.computeBoundingBox()
  const box = mesh.geometry.boundingBox
  const into = new THREE.Matrix4().copy(intoBone).multiply(mesh.bindMatrix)
  const scale = new THREE.Vector3().setFromMatrixScale(into).x || 1
  return (box.max.y - box.min.y) * 0.06 * scale
}

/**
 * The middle of a closed fist, in that hand bone's own frame.
 *
 * Where to put a tool, in other words. The bone's own origin is the wrist,
 * which is a knuckle's width short of where a handle actually sits, and these
 * rigs have no finger bones to ask instead -- so the fist is measured from the
 * skin: the vertices this bone owns.
 *
 * Only the ones near it, though. What a hand bone owns is up to the rigger,
 * and they do not agree: one gave the hand 503 vertices reaching a tenth of a
 * unit, the next gave it 3,970 and half a sleeve, reaching nearly a fifth.
 * Averaging everything it owned put the grip a hand's width up the forearm and
 * the hammer floated beside the man. A fist is a fist.
 */
export function fistOf(THREE: Three, figure: any, boneName: string): any {
  const mesh = figure.getObjectByProperty("type", "SkinnedMesh")
  const bone = figure.getObjectByName(boneName)
  const slot = mesh && bone ? mesh.skeleton.bones.indexOf(bone) : -1
  const middle = new THREE.Vector3()
  if (slot < 0) return middle

  const intoBone = mesh.skeleton.boneInverses[slot]
  const wrist = new THREE.Vector3().setFromMatrixPosition(
    new THREE.Matrix4().copy(intoBone).invert(),
  )
  const position = mesh.geometry.attributes.position
  const bones = mesh.geometry.attributes.skinIndex
  const pull = mesh.geometry.attributes.skinWeight
  const reach = fistReach(THREE, mesh, intoBone)

  const rest = new THREE.Vector3()
  let found = 0
  for (let v = 0; v < position.count; v += 1) {
    let most = 0
    let follows = -1
    for (let s = 0; s < 4; s += 1) {
      const share = pull.getComponent(v, s)
      if (share > most) {
        most = share
        follows = bones.getComponent(v, s)
      }
    }
    if (follows !== slot) continue
    rest.fromBufferAttribute(position, v).applyMatrix4(mesh.bindMatrix).applyMatrix4(intoBone)
    if (rest.distanceTo(wrist) > reach) continue
    middle.add(rest)
    found += 1
  }
  return found ? middle.divideScalar(found) : wrist
}

/**
 * Which way a hand's palm faces, in that hand bone's own frame.
 *
 * Not measured off the skin. That was tried: the palm was taken to be the
 * flattest direction through the hand's vertices, and it failed twice over --
 * the sign of a cross product is arbitrary, so the mirrored left and right
 * hands came out facing opposite ways, and a half-closed fist is round enough
 * that its flattest direction wanders toward the fingertips, which no roll
 * about the forearm can fix. The probes printed a right hand 65 degrees from
 * where it was told to face.
 *
 * What is actually known is simpler. This generator poses its characters with
 * their palms turned up -- every preview sheet showed it -- so while the
 * figure still stands in its bind pose, "up" carried into the bone's frame IS
 * the palm. Call it before any mixer has moved a bone.
 */
export function palmOf(THREE: Three, figure: any, boneName: string): any {
  const bone = figure.getObjectByName(boneName)
  if (!bone) return null
  figure.updateWorldMatrix(true, true)
  const turned = new THREE.Quaternion()
  bone.getWorldQuaternion(turned)
  return new THREE.Vector3(0, 1, 0).applyQuaternion(turned.invert()).normalize()
}

/** The dominant direction of a cloud of points, by power iteration. */
function longestWay(THREE: Three, points: any[], middle: any): any {
  const covariance = new Array(9).fill(0)
  const away = new THREE.Vector3()
  for (const p of points) {
    away.copy(p).sub(middle)
    const v = [away.x, away.y, away.z]
    for (let r = 0; r < 3; r += 1)
      for (let c = 0; c < 3; c += 1) covariance[r * 3 + c] += v[r] * v[c]
  }
  let axis = new THREE.Vector3(1, 0.3, 0.2).normalize()
  for (let turn = 0; turn < 24; turn += 1) {
    const v = [axis.x, axis.y, axis.z]
    axis = new THREE.Vector3(
      covariance[0] * v[0] + covariance[1] * v[1] + covariance[2] * v[2],
      covariance[3] * v[0] + covariance[4] * v[1] + covariance[5] * v[2],
      covariance[6] * v[0] + covariance[7] * v[1] + covariance[8] * v[2],
    )
    if (axis.lengthSq() < 1e-20) return new THREE.Vector3(0, 1, 0)
    axis.normalize()
  }
  return axis
}

/**
 * A downloaded hammer, sized and turned so it can be handed to a bone.
 *
 * Nothing here is a chosen angle. The handle is the long way through the
 * mesh; the head is whichever end of it is fatter; the grip sits a quarter of
 * the way up from the butt, where a hand goes. What comes back is a node
 * whose origin is the grip and whose local -Y runs down the handle to the
 * middle of the head, so pointing the blow somewhere is one setFromUnitVectors
 * away.
 */
function hammerHeld(THREE: Three, model: any, long: number): any {
  const held = model.clone()
  held.updateWorldMatrix(true, true)

  const points: any[] = []
  const at = new THREE.Vector3()
  held.traverse((node: any) => {
    const position = node.geometry?.attributes?.position
    if (!position) return
    // Every eighth vertex: this is a direction and a length, not a silhouette.
    for (let v = 0; v < position.count; v += 8) {
      points.push(at.fromBufferAttribute(position, v).applyMatrix4(node.matrixWorld).clone())
    }
  })
  const holder = new THREE.Group()
  if (points.length < 8) {
    holder.add(held)
    return { holder, head: new THREE.Vector3() }
  }

  const middle = points
    .reduce((sum: any, p: any) => sum.add(p), new THREE.Vector3())
    .divideScalar(points.length)
  const guess = longestWay(THREE, points, middle)

  // Which end is the head: the fatter quarter. A handle is thin all the way.
  const reach = points.map((p: any) => p.clone().sub(middle).dot(guess))
  const ends = [Math.min(...reach), Math.max(...reach)]
  const girth = (from: number, to: number) => {
    let total = 0
    let seen = 0
    points.forEach((p: any, i: number) => {
      if (reach[i] < from || reach[i] > to) return
      total += p.clone().sub(middle).addScaledVector(guess, -reach[i]).length()
      seen += 1
    })
    return seen ? total / seen : 0
  }
  const quarter = (ends[1] - ends[0]) * 0.25
  const butt = girth(ends[0], ends[0] + quarter) > girth(ends[1] - quarter, ends[1])
  // From here on the axis runs butt to head, whichever way the mesh was drawn.
  const axis = butt ? guess.negate() : guess

  const along = points.map((p: any) => p.clone().sub(middle).dot(axis))
  const low = Math.min(...along)
  const span = Math.max(...along) - low || 1
  // A hand sits a quarter of the way up from the butt.
  const grip = middle.clone().addScaledVector(axis, low + span * 0.25)

  // Turn the handle onto -Y, so aiming the blow is one rotation of this node
  // and nothing inside it ever has to move again.
  const turn = new THREE.Quaternion().setFromUnitVectors(axis, new THREE.Vector3(0, -1, 0))
  const scale = long / span

  held.applyMatrix4(new THREE.Matrix4().makeTranslation(-grip.x, -grip.y, -grip.z))
  held.applyMatrix4(new THREE.Matrix4().makeRotationFromQuaternion(turn))
  held.applyMatrix4(new THREE.Matrix4().makeScale(scale, scale, scale))
  holder.add(held)

  // Where the blow lands, in the holder's frame: straight down the handle.
  // The corners come too -- a head is a block, and clearing a wall by the one
  // point in the middle of it clears nothing.
  holder.updateWorldMatrix(false, true)
  const box = new THREE.Box3().setFromObject(held)
  const corners = []
  for (const x of [box.min.x, box.max.x])
    for (const y of [box.min.y, box.max.y])
      for (const z of [box.min.z, box.max.z]) corners.push(new THREE.Vector3(x, y, z))
  return { holder, head: new THREE.Vector3(0, -long * 0.75, 0), corners }
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

  // Sized by its length and then sunk until its face is where it belongs, so
  // the two decisions stop fighting: the stump ends up under the boards, and
  // whatever is left above them is a whole anvil.
  const anvil = props.anvil.clone()
  const raw = new THREE.Box3().setFromObject(anvil)
  anvil.scale.multiplyScalar(ANVIL_LONG / Math.max(raw.max.x - raw.min.x, raw.max.z - raw.min.z))
  const stood = new THREE.Box3().setFromObject(anvil)
  anvil.position.x -= (stood.min.x + stood.max.x) / 2
  anvil.position.z -= (stood.min.z + stood.max.z) / 2
  anvil.position.y += ANVIL_FACE - stood.max.y
  bench.add(anvil)
  const anvilTop = ANVIL_FACE

  // A quarter ton of iron does not stand on floorboards. With the stump buried
  // the pad is what it comes out of rather than what it sits on -- a collar of
  // stone set into the floor, sized off the anvil so it follows if the anvil
  // grows.
  const pad = new THREE.Mesh(
    new THREE.CylinderGeometry(ANVIL_LONG * 0.42, ANVIL_LONG * 0.46, 0.07, 9),
    new THREE.MeshStandardMaterial({ color: 0x3c3934, roughness: 1 }),
  )
  pad.position.y = 0.035
  pad.rotation.y = 0.4
  bench.add(pad)

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
  // A step from the hearth: hot iron does not survive a walk across the room.
  figure.position.set(-0.3, 0, 0.14)
  // Turned to the anvil rather than the camera. Which way that is depends on
  // the model's own facing, so it is a constant to look at rather than derive.
  figure.rotation.y = FACING
  group.add(figure)
  const face = makeFace(THREE, figure, blinkOffset)

  // Captured here, while the figure still stands in its bind pose: the first
  // mixer probe below moves the bones, and the palms' rest direction with it.
  const palms = ["Left", "Right"]
    .map((side) => ({
      bone: figure.getObjectByName(`${side}Hand`),
      elbow: figure.getObjectByName(`${side}ForeArm`),
      faces: palmOf(THREE, figure, `${side}Hand`),
    }))
    .filter((palm) => palm.bone?.parent && palm.elbow && palm.faces)

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
  // more, so find it: run the swing through once and follow the head of the
  // hammer -- not the fist -- to its lowest point.
  //
  // The fist was what this followed before, plus a hand's width forward along
  // the way he faces, and that guess was wrong twice over. The head hangs a
  // forearm below the fist and a little across it, which is the width of an
  // anvil; and "forward" is not where a swing ends, it only happened to be
  // close. Following the iron itself needs no constant at all.
  acts.working.setEffectiveWeight(1)
  const swing = clipNamed("swing")
  const hand = figure.getObjectByName(`${HAMMER_HAND}Hand`) ?? figure

  // His arms are two thirds of a person's; see reach.ts. Set the elbow and
  // the wrist out along their own bones, and call it after every write the
  // mixer makes -- the clips carry translation tracks for these.
  const stretchArms = stretcher(
    ["LeftForeArm", "LeftHand", "RightForeArm", "RightHand"]
      .map((name) => figure.getObjectByName(name))
      .filter(Boolean),
    ARM_STRETCH,
  )
  stretchArms()

  // What a man's arms do while he stands still: the upper arm hangs a few
  // degrees clear of the ribs and the elbow is nearly straight. This rig's
  // idle does neither, and the two together are what read as a man tied up.
  // Both are turned to an absolute target rather than nudged, so running it
  // every frame lands in the same place -- nudging compounds, because the
  // mixer does not rewrite a track whose value has not changed.
  const arms = (["Left", "Right"] as const)
    .map((side) => ({
      side,
      arm: figure.getObjectByName(`${side}Arm`),
      fore: figure.getObjectByName(`${side}ForeArm`),
      fist: figure.getObjectByName(`${side}Hand`),
    }))
    .filter((a) => a.arm && a.fore && a.fist)
  const hips = figure.getObjectByName("Hips")
  const nape = figure.getObjectByName("neck") ?? figure.getObjectByName("Neck")

  const bodyUp = new THREE.Vector3()
  const across = new THREE.Vector3()
  const outward = new THREE.Vector3()
  const upper = new THREE.Vector3()
  const lower = new THREE.Vector3()
  const hinge = new THREE.Vector3()
  const spotA = new THREE.Vector3()
  const spotB = new THREE.Vector3()

  /** Turn a bone about a direction in the room, not one in its own frame. */
  const turnBone = (bone: any, about: any, angle: number) => {
    if (Math.abs(angle) < 0.002 || !bone.parent) return
    bone.parent.getWorldQuaternion(parented)
    bone.quaternion.premultiply(
      turning
        .copy(parented)
        .invert()
        .multiply(spare.setFromAxisAngle(about, angle))
        .multiply(parented),
    )
  }

  const easeArms = (rest: number) => {
    if (arms.length < 2 || !hips || !nape) return
    hips.getWorldPosition(spotA)
    nape.getWorldPosition(spotB)
    bodyUp.subVectors(spotB, spotA)
    arms[0].arm.getWorldPosition(spotA)
    arms[1].arm.getWorldPosition(spotB)
    across.subVectors(spotA, spotB)
    if (bodyUp.lengthSq() < 1e-9 || across.lengthSq() < 1e-9) return
    bodyUp.normalize()
    across.normalize()

    for (const limb of arms) {
      limb.arm.getWorldPosition(spotA)
      limb.fore.getWorldPosition(spotB)
      upper.subVectors(spotB, spotA)
      limb.fist.getWorldPosition(spotA)
      lower.subVectors(spotA, spotB)
      if (upper.lengthSq() < 1e-9 || lower.lengthSq() < 1e-9) continue
      upper.normalize()
      lower.normalize()
      outward.copy(across).multiplyScalar(limb.side === "Left" ? 1 : -1)

      // The elbow first: it lands in the forearm's own local rotation, which
      // the shoulder turn below then carries along unchanged. The hinge is
      // `l x u` and not the `u x l` it looks like it should be -- a vector
      // rotated about `u x l` travels away from `u`, not toward it, and taking
      // that on trust gave a man shrugging at his forge.
      hinge.crossVectors(lower, upper)
      if (hinge.lengthSq() > 1e-9) {
        hinge.normalize()
        turnBone(limb.fore, hinge, (flexion(upper, lower) - ELBOW_REST) * rest)
      }

      // Then the shoulder, sideways only: about the axis that runs front to
      // back, so whatever lean the clip has is left where it is.
      hinge.crossVectors(outward, bodyUp).normalize()
      turnBone(limb.arm, hinge, (ARM_OUT - sideways(upper, outward, bodyUp)) * rest)
    }
  }

  /** The lowest the hand goes, and when -- the blow, near enough to aim by. */
  const bottom = (probe: (moment: number) => any) => {
    const at = new THREE.Vector3()
    const found = new THREE.Vector3()
    let lowest = Infinity
    let when = 0
    for (let step = 0; step <= 60; step += 1) {
      const moment = (step / 60) * swing.duration
      mixer.setTime(moment)
      stretchArms()
      figure.updateWorldMatrix(true, true)
      at.copy(probe(moment))
      if (at.y < lowest) {
        lowest = at.y
        found.copy(at)
        when = moment
      }
    }
    return { at: found, when }
  }

  // Give him the hammer before asking where it lands. It sits where his fist
  // is, measured off the skin, and the handle is turned so that at the bottom
  // of the swing it points straight at the floor -- a rotation solved from the
  // bone's own matrix at that moment, not an angle anybody chose. The old prop
  // was welded into the mesh and could only be followed vertex by vertex; this
  // one is a node, so its head is a point.
  //
  // It hangs off the forearm rather than the hand, which is the one place this
  // deliberately disobeys the rig. The wrist turns 91 degrees over the swing
  // -- from 8 off its rest pose to 99 -- because the actor was holding
  // nothing and nothing constrained it. Two feet of iron and ash bolted to
  // that rolls like a rubber hose. On the elbow it keeps the arc and loses the
  // roll, and a hammer in line with the forearm is what a swing looks like
  // anyway.
  const wrist = new THREE.Vector3()
  const swung = bottom(() => hand.getWorldPosition(wrist))
  /** The holder's own axis: -Y runs down the handle to the head. */
  const HANDLE = new THREE.Vector3(0, -1, 0)
  /** How the hammer is held while he is working: out along the forearm. */
  const swinging = new THREE.Quaternion()
  /** And while he is not: hanging from the fist, whatever the arm is doing. */
  const hanging = new THREE.Quaternion()
  const axis = new THREE.Vector3()
  const looks = new THREE.Vector3()
  const inward = new THREE.Vector3()
  const flatly = new THREE.Vector3()
  const middleOf = new THREE.Vector3()
  const handAt = new THREE.Vector3()
  const turning = new THREE.Quaternion()
  const parented = new THREE.Quaternion()
  const spare = new THREE.Quaternion()
  const turned = new THREE.Quaternion()
  // Up in the room, carried into the forearm's frame by tick() below.
  const skyward = new THREE.Vector3()
  const forearm = figure.getObjectByName(`${HAMMER_HAND}ForeArm`) ?? hand
  const boneScale = new THREE.Vector3().setFromMatrixScale(forearm.matrixWorld).x || 1
  const hammer = hammerHeld(THREE, props.hammer, HAMMER_LONG / boneScale)

  mixer.setTime(swung.when)
  stretchArms()
  figure.updateWorldMatrix(true, true)
  {
    // The fist is measured in the hand's frame; the hammer lives in the
    // forearm's. Carry the point across through the world at the one pose
    // that has to be right.
    const grip = fistOf(THREE, figure, `${HAMMER_HAND}Hand`)
    hand.localToWorld(grip)
    forearm.worldToLocal(grip)
    hammer.holder.position.copy(grip)
    forearm.add(hammer.holder)

    // -Y of the holder runs down the handle to the head, and while he is
    // working it runs on out along the arm -- which is a direction the rig
    // knows: where the wrist sits, seen from the elbow. Solving it against
    // the floor at one pose worked for that pose and left the hammer stuck
    // out sideways in the other clip.
    const alongArm = new THREE.Vector3()
    hand.getWorldPosition(alongArm)
    forearm.worldToLocal(alongArm).normalize()
    swinging.setFromUnitVectors(HANDLE, alongArm)
    hammer.holder.quaternion.copy(swinging)
    figure.updateWorldMatrix(true, true)
  }

  // When, within the clip, the blow actually lands -- the sparks need it too.
  // Printing the hammer's whole path settled it: the clip winds up mid-loop
  // and slams at the very END, so the lowest point is the blow, and the loop
  // seam sits right behind it.
  const strike = bottom(() =>
    hammer.holder.localToWorld(hammer.head.clone()),
  )
  const strikeAt = strike.when

  // Now stand him where the swing fits the room. The backswing takes the
  // hammer up and behind his left shoulder, which is the corner the two walls
  // meet in, and it was going a third of a metre into the logs. So sweep the
  // clip for how far past the inside faces the head reaches, and step him and
  // his anvil out by exactly that -- toward the open side, which is where a
  // room this shape has room to give.
  {
    const corner = new THREE.Vector3()
    const intoWall = { x: 0, z: 0 }
    for (let step = 0; step <= 60; step += 1) {
      mixer.setTime((step / 60) * swing.duration)
      stretchArms()
      figure.updateWorldMatrix(true, true)
      for (const local of hammer.corners) {
        corner.copy(local)
        hammer.holder.localToWorld(corner)
        intoWall.x = Math.max(intoWall.x, INSIDE + HAMMER_CLEAR - corner.x)
        intoWall.z = Math.max(intoWall.z, INSIDE + HAMMER_CLEAR - corner.z)
      }
    }
    figure.position.x += intoWall.x
    figure.position.z += intoWall.z
    strike.at.x += intoWall.x
    strike.at.z += intoWall.z
  }
  mixer.setTime(0)
  stretchArms()

  bench.position.set(strike.at.x, 0, strike.at.z)
  // Only after the probe: setTime works in unscaled clip seconds, and slowing
  // the clock before measuring would have moved the anvil.
  acts.working.setEffectiveTimeScale(WORK_PACE)
  acts.resting.setEffectiveTimeScale(REST_PACE)
  acts.working.setEffectiveWeight(0)
  acts.resting.setEffectiveWeight(1)
  figure.updateWorldMatrix(true, true)

  // A soft radial dot, drawn once: bare Points render as hard squares, and a
  // square spark is a pixel error, not an ember.
  const glowCanvas = document.createElement("canvas")
  glowCanvas.width = glowCanvas.height = 32
  const ink = glowCanvas.getContext("2d")!
  const wash = ink.createRadialGradient(16, 16, 1, 16, 16, 16)
  wash.addColorStop(0, "rgba(255,255,255,1)")
  wash.addColorStop(0.4, "rgba(255,255,255,0.55)")
  wash.addColorStop(1, "rgba(255,255,255,0)")
  ink.fillStyle = wash
  ink.fillRect(0, 0, 32, 32)
  const glow = new THREE.CanvasTexture(glowCanvas)

  // -- sparks off the blow: a handful of embers thrown out of the work after
  // each strike, arcing up and falling past the anvil. How long they live and
  // where they go is in ./strike, in wall-clock seconds; this is only what
  // shows them.
  //
  // Sprites rather than Points, which is not a style choice. This room is seen
  // through an OrthographicCamera, and three.js sizes a Point by pixels unless
  // the projection is perspective -- so `size: 0.07`, read as world units and
  // written as such, asked for embers a fourteenth of a pixel across. The
  // sparks were never once drawn. A Sprite is measured in world units under
  // either projection, which is why the flash below always did show up.
  const sparkSpray = new Float32Array(SPARKS * 3)
  const sparkSkin = new THREE.SpriteMaterial({
    color: 0xffd98a,
    map: glow,
    transparent: true,
    opacity: 0,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
  const sparks = new THREE.Group()
  sparks.position.copy(work.position)
  for (let i = 0; i < SPARKS; i += 1) {
    const ember = new THREE.Sprite(sparkSkin)
    // Small enough to read as a spark rather than a firefly, big enough to
    // survive a bench shrunk to phone width.
    ember.scale.setScalar(0.055)
    sparks.add(ember)
  }
  bench.add(sparks)

  // The flash is what sells the impact -- but a light alone did nothing: the
  // anvil is near-black and reflects nothing, which a brightness probe on the
  // bench sheet proved (+2 grey levels, inside the noise). So the flash is a
  // thing that glows, not just a light: an additive sprite that blooms over
  // the work and dies in a sixth of a second, with the light as backup.
  const impact = new THREE.PointLight(0xffc46b, 0, 2.4, 1.8)
  impact.position.copy(work.position).y += 0.12
  bench.add(impact)

  const flashSkin = new THREE.SpriteMaterial({
    map: glow,
    color: 0xffe9b8,
    transparent: true,
    opacity: 0,
    depthWrite: false,
    blending: THREE.AdditiveBlending,
  })
  const flash = new THREE.Sprite(flashSkin)
  flash.position.copy(work.position).y += 0.08
  bench.add(flash)

  const swingLength = clipNamed("swing").duration

  let hot = false
  let was = -1
  let mode: "working" | "resting" = "resting"
  // Which blow this is. Counted off the clip's own wrap rather than derived
  // from the mixer's clock: the mixer counts unscaled seconds and the clip
  // runs at WORK_PACE, so `mixer.time / swingLength` advances half again as
  // fast as the hammer does and re-hashed the spray mid-flight.
  let blow = 0
  let lastSince = 0
  // For tools/bench.html only: lets the sheet print what the mixer is doing.
  ;(group as any).userData.acts = acts
  ;(group as any).userData.strikeAt = strikeAt
  // The sparks too: judging a burst from a still is what let a flash that was
  // not there be signed off once already.
  ;(group as any).userData.sparks = sparks
  ;(group as any).userData.anvilTop = anvilTop
  // The hammer, so the sheet can follow the head rather than the wrist.
  ;(group as any).userData.hammer = hammer

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
        toward.setEffectiveTimeScale(next === "working" ? WORK_PACE : REST_PACE)
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
      stretchArms()
      was = elapsed

      // easeArms aims at an absolute angle, so it has to read the pose the
      // mixer just wrote and not the one on screen, which already carries the
      // last frame's correction -- hence the update before it. And the update
      // after, so the hammer and the palms below aim at the arms as corrected
      // rather than as the clip left them. Both are skipped while he is
      // swinging, when there is no correction to see.
      const working = acts.working.getEffectiveWeight()
      const rest = 1 - working
      if (rest > 0.01) {
        figure.updateWorldMatrix(true, true)
        easeArms(rest)
        figure.updateWorldMatrix(true, true)
      }

      face?.at(elapsed)

      flame.tick(elapsed)

      // A hammer he is not swinging is carried head up, the way a man holds
      // one he is about to use -- knuckles round the low end of the handle,
      // the weight above the fist. Locked to the forearm it stuck out sideways
      // whenever the arm did, which is most of the day, and hung head-down it
      // read as something he had dropped. So the aim rides the same crossfade
      // the body does: along the arm while he works, upright while he waits,
      // and neither one snapping to the other.
      forearm.getWorldQuaternion(turned)
      skyward.set(0, 1, 0).applyQuaternion(turned.invert())
      hanging.setFromUnitVectors(HANDLE, skyward)
      hammer.holder.quaternion.copy(hanging).slerp(swinging, working)


      // Turn the palms in. He was generated in an A-pose with his hands turned
      // up, and every clip retargeted onto him inherits it, so at rest he holds
      // an invisible tray. This is a roll about the forearm and nothing else:
      // where the arm hangs is easeArms' business, above, and how far round
      // the palm is turned within it is this one's.
      if (rest > 0.01) {
        figure.getWorldPosition(middleOf)
        for (const palm of palms) {
          palm.elbow.getWorldPosition(axis)
          palm.bone.getWorldPosition(handAt)
          axis.subVectors(handAt, axis)
          if (axis.lengthSq() < 1e-9) continue
          axis.normalize()

          // Where the palm looks now, and where it should: at his own middle.
          looks.copy(palm.faces).applyQuaternion(palm.bone.getWorldQuaternion(parented))
          inward.subVectors(middleOf, handAt).setY(0)
          if (inward.lengthSq() < 1e-9) continue
          inward.normalize()

          // The angle is found by trying, not solved. It was solved once, with
          // a projection and an atan2, and the applied roll landed the palm
          // sixty degrees from where the arithmetic said it would -- some sign
          // convention between bone frames disagreed with the derivation, and
          // a probe is how it was caught. Thirty-six candidates around the
          // circle cannot be wrong about a convention.
          let bestRoll = 0
          let bestDot = -2
          for (let step = 0; step < 36; step += 1) {
            const angle = (step / 36) * Math.PI * 2
            flatly
              .copy(looks)
              .applyQuaternion(spare.setFromAxisAngle(axis, angle))
            const dot = flatly.dot(inward)
            if (dot > bestDot) {
              bestDot = dot
              bestRoll = angle
            }
          }
          const roll = bestRoll * rest

          palm.bone.parent.getWorldQuaternion(parented)
          palm.bone.quaternion.premultiply(
            turning
              .copy(parented)
              .invert()
              .multiply(spare.setFromAxisAngle(axis, roll))
              .multiply(parented),
          )
          palm.bone.updateWorldMatrix(false, true)
        }
      }

      // Sparks fly for a moment after the hammer lands. Measured around the
      // loop: the blow lands a tenth of a second before the clip's seam, and
      // an unwrapped clock cut every burst off at the seam, a third grown.
      // Divided by the pace here, once: everything in ./strike is real
      // seconds, and the clip's own clock runs slower than the room's.
      const sinceBlow =
        ((acts.working.time - strikeAt + swingLength) % swingLength) / WORK_PACE
      if (sinceBlow < lastSince) blow += 1
      lastSince = sinceBlow
      if (mode === "working" && sinceBlow > 0 && sinceBlow < SPARK_LIFE) {
        spray(blow, sinceBlow, sparkSpray)
        sparks.children.forEach((ember, i) =>
          ember.position.set(
            sparkSpray[i * 3],
            sparkSpray[i * 3 + 1],
            sparkSpray[i * 3 + 2],
          ),
        )
        sparks.visible = true
        sparkSkin.opacity = sparkFade(sinceBlow)
        impact.intensity = lightPower(sinceBlow)
        flashSkin.opacity = flashFade(sinceBlow)
        const spread = flashSpread(sinceBlow)
        flash.scale.set(spread, spread, 1)
      } else {
        sparks.visible = false
        sparkSkin.opacity = 0
        impact.intensity = 0
        flashSkin.opacity = 0
      }

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
      sparkSkin.dispose()
      flashSkin.dispose()
      glow.dispose()
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
  const [gltf, anvilGltf, forgeGltf, hammerGltf] = await Promise.all([
    loader.loadAsync(smithUrl),
    loader.loadAsync(anvilUrl),
    loader.loadAsync(forgeUrl),
    loader.loadAsync(hammerUrl),
  ])

  const smith = gltf.scene
  const clips = gltf.animations ?? []
  const props = {
    anvil: anvilGltf.scene,
    forge: forgeGltf.scene,
    hammer: hammerGltf.scene,
  }
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
  // Just enough to read the room by -- the forge is meant to carry it. The
  // first pass lit everything like noon, and the smithy read as a pine sauna.
  scene.add(new THREE.AmbientLight(0xa08f7a, 0.95))
  const key = new THREE.DirectionalLight(0xc4b49c, 1.5)
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
  const painted = new Map<string, Worker>()
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
    // localStorage, parsed once per frame rather than once per use of it.
    const saved = savedSpots()
    const arranged = place(flows, saved, columnsFor(el.clientWidth))
    const changed = new Set(changedWorkers(stage.workers, painted).map(([flow]) => flow))

    for (const [flow, bench] of benches) {
      if (!(flow in stage.workers)) {
        room.remove(bench.group)
        bench.dispose()
        benches.delete(flow)
      }
    }

    const signature = `${flows.join("|")}@${el.clientWidth}x${el.clientHeight}`
    if (signature !== arrangedFor && !handled && Object.keys(saved).length === 0) {
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

      // Placement follows every frame; the bench and its tag only follow the
      // frames that touched this worker. paint() rebuilds shelf geometry, so
      // repainting a whole board because one flow spoke is GPU churn.
      if (!changed.has(flow)) continue
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

    tidy.hidden = !handled && Object.keys(saved).length === 0
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
