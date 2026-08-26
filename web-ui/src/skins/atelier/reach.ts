/**
 * Lengthening a rig's arms.
 *
 * The generated smith has arms two thirds of a person's -- his upper arm is
 * 12% of his height where a man's is 18% -- which folded his hands onto his
 * belly and left his elbows reading as broken. No rotation can add reach, so
 * the elbow and the wrist get pushed out along their own bones and the sleeve
 * stretches across the gap.
 *
 * Positions and not scale: a scaled bone hands the same stretch down to the
 * hand, and to the hammer held in it, and both come out deformed.
 */

/** The little of a bone this needs: somewhere to put it. */
export interface Jointed {
  position: {
    clone(): any
    copy(from: any): any
    multiplyScalar(by: number): any
  }
}

/**
 * A function that sets those joints out by `factor`, to be called after every
 * write the mixer makes -- the clips carry translation tracks for arm bones
 * and would put them back each frame.
 *
 * It reads each bone's rest position once and then always sets from that, so
 * calling it twice in a frame does what calling it once does. Multiplying the
 * bone in place instead looks identical for one frame and then runs away,
 * because the mixer does not rewrite a track whose value has not changed.
 */
export function stretcher(joints: Jointed[], factor: number): () => void {
  const rest = new Map<Jointed, any>()
  return () => {
    for (const bone of joints) {
      let was = rest.get(bone)
      if (!was) {
        was = bone.position.clone()
        rest.set(bone, was)
      }
      bone.position.copy(was).multiplyScalar(factor)
    }
  }
}

/** Any three numbers that name a direction. */
export interface Way {
  x: number
  y: number
  z: number
}

const dot = (a: Way, b: Way) => a.x * b.x + a.y * b.y + a.z * b.z
const size = (a: Way) => Math.sqrt(dot(a, a))

/**
 * How far the elbow is bent, in radians: nothing when the arm is straight.
 *
 * `upper` runs shoulder to elbow and `lower` elbow to wrist, so a straight arm
 * has them pointing the same way. A man standing still holds 10 to 20 degrees
 * here. This rig's idle holds 45, which crosses the forearms over the belly.
 */
export function flexion(upper: Way, lower: Way): number {
  const scale = size(upper) * size(lower)
  if (scale < 1e-9) return 0
  return Math.acos(Math.max(-1, Math.min(1, dot(upper, lower) / scale)))
}

/**
 * How far the upper arm hangs clear of the body, in radians, sideways only --
 * positive away from the ribs, negative into them.
 *
 * `up` runs hips to neck and `outward` points away from this arm's own side,
 * so the measurement ignores whatever the clip is doing front to back. A man
 * standing still holds 5 to 10 degrees. This rig's idle holds -9 to -18: the
 * arm is pressed inward, which with the bent elbow is what reads as bound.
 */
export function sideways(upper: Way, outward: Way, up: Way): number {
  return Math.atan2(dot(upper, outward), -dot(upper, up))
}

/**
 * The same turn, taken the short way round: an angle in [0, 2pi) mapped into
 * (-pi, pi].
 *
 * A search around the circle returns 300 degrees where -60 was meant, and the
 * two are the same rotation -- until something scales them. Half of -60 is a
 * hand half turned; half of 300 is a hand turned the wrong way and further
 * than it started.
 */
export function shortestWay(angle: number): number {
  const round = Math.PI * 2
  const wrapped = ((angle % round) + round) % round
  return wrapped > Math.PI ? wrapped - round : wrapped
}
