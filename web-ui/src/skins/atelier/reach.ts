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
