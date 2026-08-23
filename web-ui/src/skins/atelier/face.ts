/**
 * Blinking, added from outside the model.
 *
 * The character arrives as a single mesh with a single material and no morph
 * targets, so there is nothing in the file to animate a face with -- the eyes
 * are painted into the texture. A blink is therefore two small skin-coloured
 * lids hung on the head bone and shown for a moment: at any distance the
 * workshop is actually viewed from, an eye that vanishes for a tenth of a
 * second reads as an eye that closed.
 *
 * Everything is measured off the skeleton rather than written down in model
 * units, so a re-generated character still gets lids in roughly the right
 * place, and tools/pose.html has a close-up row for checking that they landed.
 */

/** Where the eyes sit, as fractions of the skull's own height, from its middle. */
export const EYE = { up: 0.02, out: 0.135, forward: 0.44 }
export const LID = { wide: 0.16, tall: 0.1 }

/** How far each lid turns outward, so a flat plane follows a round face. */
const WRAP = 0.35

/** What tools/pose.html varies while these are being found by eye. */
export interface Placing {
  eye?: { up: number; out: number; forward: number }
  lid?: { wide: number; tall: number }
}

/** Painted to match the face; the lids take the room's light like the skin does. */
const SKIN = 0xffc6ae
const LASH = 0x6b4630

/** A blink every few seconds, and over almost before it is seen. In ms. */
const APART = 3600
const SHUT = 110

/** Where the skull is, and what drives it. */
export interface Head {
  bone: any
  /** World point at the middle of the skull. */
  centre: any
  /** World height of the skull, neck to crown. */
  tall: number
}

/** A head is about a seventh of a person, when nothing better can be measured. */
const HEAD_SHARE = 1 / 7

/**
 * Measure the skull from the skeleton and the silhouette.
 *
 * Deliberately suspicious of the skeleton. Auto-rigging puts the head bone at
 * the base of the skull on one model and above the crown on the next, and has
 * been seen to leave a neck bone metres away from the body -- so the bone gives
 * the centre line, the neck is used for the height only when it is somewhere
 * believable, and the fallback is a proportion of the whole figure.
 */
export function headFrame(THREE: any, figure: any): Head | null {
  figure.updateWorldMatrix(true, true)

  const named = (pattern: RegExp) => {
    const found: any[] = []
    figure.traverse((node: any) => {
      if (node.isBone && pattern.test(node.name ?? "")) found.push(node)
    })
    return found
  }

  const bone = named(/^head$/i)[0] ?? named(/head/i).find((node) => !/end|tip|top|nub/i.test(node.name))
  if (!bone) return null

  const whole = new THREE.Box3().setFromObject(figure)
  const crown = whole.max.y
  const at = new THREE.Vector3()
  bone.getWorldPosition(at)

  let tall = (whole.max.y - whole.min.y) * HEAD_SHARE
  const neck = named(/neck/i)[0] ?? named(/spine/i).pop()
  if (neck) {
    const under = new THREE.Vector3()
    neck.getWorldPosition(under)
    const height = crown - under.y
    // Believable means: below the crown, above a third of it, and actually
    // under the head rather than off in the room somewhere.
    const sideways = Math.hypot(under.x - at.x, under.z - at.z)
    if (height > 0 && height < (whole.max.y - whole.min.y) / 3 && sideways < height) {
      tall = height
    }
  }
  if (!(tall > 0)) return null

  const middle = centreLine(THREE, figure) ?? at
  return { bone, tall, centre: middle.setY(crown - tall / 2) }
}

/**
 * The body's plane of symmetry, found from every left/right pair of bones.
 *
 * Not from the head bone, which has been seen an eye-width off centre, and not
 * from any single pair either: a character holding a hammer has asymmetric arms,
 * and this rig's own shoulders disagree with its legs. The median of all the
 * pairs ignores the few that are posed or misplaced.
 */
function centreLine(THREE: any, figure: any): any {
  const bones = new Map<string, any>()
  figure.traverse((node: any) => {
    if (node.isBone) bones.set(node.name ?? "", node)
  })

  const midpoints: { x: number; z: number }[] = []
  const here = new THREE.Vector3()
  const there = new THREE.Vector3()
  for (const [name, bone] of bones) {
    const mirror = name.replace(/left/i, (m) => (m[0] === "L" ? "Right" : "right"))
    if (mirror === name) continue
    const twin = bones.get(mirror)
    if (!twin) continue
    bone.getWorldPosition(here)
    twin.getWorldPosition(there)
    midpoints.push({ x: (here.x + there.x) / 2, z: (here.z + there.z) / 2 })
  }
  if (!midpoints.length) return null

  const median = (values: number[]) => {
    const sorted = [...values].sort((a, b) => a - b)
    const half = Math.floor(sorted.length / 2)
    return sorted.length % 2 ? sorted[half] : (sorted[half - 1] + sorted[half]) / 2
  }
  return new THREE.Vector3(
    median(midpoints.map((m) => m.x)),
    0,
    median(midpoints.map((m) => m.z)),
  )
}

export interface Face {
  /** Show or hide the lids for this moment of the run. */
  at(elapsed: number): void
  dispose(): void
}

/**
 * Hang lids on the figure's head, or return null if it has no measurable head
 * -- a rig that cannot be read is a reason to skip blinking, not to fail.
 *
 * `offset` staggers one figure against another, so a room full of smiths does
 * not blink in unison. It is derived from the flow's name rather than drawn at
 * random, so a replay blinks where the live run did.
 */
export function makeFace(
  THREE: any,
  figure: any,
  offset = 0,
  placing: Placing = {},
): Face | null {
  const head = headFrame(THREE, figure)
  if (!head) return null
  const { tall } = head
  const eyeAt = placing.eye ?? EYE
  const lidAt = placing.lid ?? LID

  // The face looks the way the figure does, whatever the bone's own axes are.
  const facing = new THREE.Quaternion()
  figure.getWorldQuaternion(facing)
  const forward = new THREE.Vector3(0, 0, 1).applyQuaternion(facing)
  const across = new THREE.Vector3(1, 0, 0).applyQuaternion(facing)
  const up = new THREE.Vector3(0, 1, 0)

  const lids = new THREE.Group()
  // Named so it can be found again from outside -- the tests look it up rather
  // than guessing which group in the tree is the one that blinks.
  lids.name = "blink"
  lids.visible = false

  const skin = new THREE.MeshStandardMaterial({ color: SKIN, roughness: 0.85 })
  const lash = new THREE.MeshStandardMaterial({ color: LASH, roughness: 0.9 })
  const shape = new THREE.PlaneGeometry(tall * lidAt.wide, tall * lidAt.tall)
  const line = new THREE.PlaneGeometry(tall * lidAt.wide, tall * lidAt.tall * 0.16)

  for (const side of [-1, 1]) {
    const eye = new THREE.Group()
    eye.position
      .copy(head.centre)
      .addScaledVector(up, tall * eyeAt.up)
      .addScaledVector(across, side * tall * eyeAt.out)
      .addScaledVector(forward, tall * eyeAt.forward)
    eye.quaternion.copy(facing)
    // Without this the outer corner of the eye escapes past the edge of a lid
    // that is sitting flat against a cheek that curves away.
    eye.rotateY(side * WRAP)

    eye.add(new THREE.Mesh(shape, skin))
    // The crease along the bottom: without it a closed eye is a blank patch.
    const crease = new THREE.Mesh(line, lash)
    crease.position.set(0, -tall * lidAt.tall * 0.42, 0.001)
    eye.add(crease)

    lids.add(eye)
  }

  // Placed in world space, then handed to the bone with that placement intact,
  // so the lids ride the head without anyone having to know the rig's axes.
  ;(figure.parent ?? figure).add(lids)
  head.bone.attach(lids)

  return {
    at(elapsed: number) {
      lids.visible = (elapsed + offset) % APART < SHUT
    },
    dispose() {
      lids.removeFromParent()
      shape.dispose()
      line.dispose()
      skin.dispose()
      lash.dispose()
    },
  }
}
