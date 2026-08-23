/**
 * How the smith stands at each point of a hammer swing.
 *
 * Kept apart from the skin so the pose sheet in tools/ can drive exactly the
 * same code: a swing judged in a lit close-up and a swing shown on the board
 * have to be the same swing, or the tool is measuring something else.
 *
 * The model is rigged in a neutral pose with a hammer in one hand and tongs in
 * the other, so one arm swings and the other stays on the work. Rotations are
 * applied about an axis in world space rather than a bone's own, because which
 * local axis bends a shoulder is the rig's business and guessing it wrong
 * swings the arm sideways like a gate.
 */

/** Which hand the model holds its hammer in. */
export const HAMMER_HAND = "Right"

/**
 * The swing, as a shoulder and an elbow at each end of it.
 *
 * Raised: the arm is back and the elbow folded. Struck: both have opened out
 * and the hammer is down on the work.
 */
export const SHOULDER = { raised: -2.0, struck: 0.42 }
export const ELBOW = { raised: -1.15, struck: -0.05 }

/** Which way round the rig turns. Filmed, not reasoned about. */
export const ARM_SENSE = 1

/**
 * The line the arm turns about, in the model's own frame.
 *
 * A hammer swings in the plane the smith faces, so this is the line across his
 * shoulders. Which of the model's axes that is depends on which way it was
 * built facing; tools/pose.html sweeps the candidates and the answer is looked
 * at rather than reasoned about.
 */
export const SWING_AXIS = { x: 1, y: 0, z: 0 }

/** Where the other hand holds the work: down and forward, onto the anvil. */
export const TONG_SHOULDER = 0.55
export const TONG_ELBOW = -1.1

/**
 * Where a smith stands when he is not working: hammer down by the anvil.
 *
 * Holding the raised pose instead leaves an idle flow frozen halfway through a
 * backswing, arm up beside the ear, which reads as a man waiting rather than a
 * man resting.
 */
export const RESTING = 1

/** How far the waist follows the blow. */
export const LEAN = { raised: -0.05, struck: 0.35 }

/** A joint angle at each end of the swing, in radians. */
export interface Span {
  raised: number
  struck: number
}

/**
 * Overrides for one render, so tools/pose.html can shoot a candidate swing
 * without the skin being edited between shots. The skin passes nothing.
 */
export interface Tuning {
  shoulder?: Span
  elbow?: Span
  lean?: Span
  tongShoulder?: number
  tongElbow?: number
  axis?: { x: number; y: number; z: number }
}

export interface Hinge {
  bone: any
  rest: any
}

export interface Twist {
  bone: any
  rest: number
}

export interface Rigging {
  spine: Twist[]
  swinging: Hinge[]
  holding: Hinge[]
}

/** Find the bones a swing needs, and remember where they rest. */
export function riggingOf(figure: any): Rigging {
  const spineNames: string[] = []
  figure.traverse((node: any) => {
    if (/^spine/i.test(node.name ?? "")) spineNames.push(node.name)
  })

  const twist = (names: string[]): Twist[] =>
    names
      .map((name) => figure.getObjectByName(name))
      .filter(Boolean)
      .map((bone: any) => ({ bone, rest: bone.rotation.x }))

  const hinge = (names: string[]): Hinge[] =>
    names
      .map((name) => figure.getObjectByName(name))
      .filter(Boolean)
      .map((bone: any) => ({ bone, rest: bone.quaternion.clone() }))

  const other = HAMMER_HAND === "Right" ? "Left" : "Right"
  return {
    spine: twist(spineNames),
    swinging: hinge([`${HAMMER_HAND}Arm`, `${HAMMER_HAND}ForeArm`]),
    holding: hinge([`${other}Arm`, `${other}ForeArm`]),
  }
}

const between = (span: Span, through: number) =>
  span.raised + (span.struck - span.raised) * through

/**
 * Pose the figure at a point in the swing: 0 is raised, 1 is struck.
 *
 * `THREE` is passed in rather than imported, so this file never pulls the
 * renderer into a bundle that did not already want it.
 */
export function poseAt(
  THREE: any,
  figure: any,
  rig: Rigging,
  through: number,
  tuning: Tuning = {},
): void {
  const lean = between(tuning.lean ?? LEAN, through)
  for (const joint of rig.spine) {
    joint.bone.rotation.x = joint.rest + lean / Math.max(1, rig.spine.length)
  }

  // The arms hang off the spine, so it has to have moved before they are
  // placed against the world.
  figure.updateWorldMatrix(true, true)
  const facing = new THREE.Quaternion()
  figure.getWorldQuaternion(facing)
  const along = tuning.axis ?? SWING_AXIS
  const axis = new THREE.Vector3(along.x, along.y, along.z).applyQuaternion(facing)

  const swing = [
    between(tuning.shoulder ?? SHOULDER, through),
    between(tuning.elbow ?? ELBOW, through),
  ]
  const steady = [tuning.tongShoulder ?? TONG_SHOULDER, tuning.tongElbow ?? TONG_ELBOW]

  const turn = (joints: Hinge[], angles: number[]) => {
    joints.forEach((joint, index) => {
      joint.bone.quaternion.copy(joint.rest)
      // Parent first: the forearm hangs off the upper arm, which has just moved.
      joint.bone.parent?.updateWorldMatrix(true, false)
      aboutWorld(THREE, joint.bone, axis, angles[index] * ARM_SENSE)
    })
  }

  turn(rig.swinging, swing)
  turn(rig.holding, steady)
}

/**
 * Turn a bone about a line in world space.
 *
 * Three's own rotateOnWorldAxis says in its docs that it assumes no rotated
 * parent, and the workshop stands every smith at a quarter turn to the room --
 * so using it directly swung the arm across the body instead of along it, and
 * the harness missed it because the harness did not turn the figure. Carrying
 * the axis into the parent's frame first is the whole fix.
 */
function aboutWorld(THREE: any, bone: any, axis: any, angle: number): void {
  if (!bone.parent) {
    bone.rotateOnWorldAxis(axis, angle)
    return
  }
  const parent = new THREE.Quaternion()
  bone.parent.getWorldQuaternion(parent)
  const local = axis.clone().applyQuaternion(parent.invert())
  bone.rotateOnWorldAxis(local, angle)
}
