import * as THREE from "three"
import { expect, test } from "vitest"

import { poseAt, riggingOf } from "./pose"

/** A skeleton with the names the swing looks for, and nothing else. */
function stickFigure() {
  const figure = new THREE.Group()
  const spine = new THREE.Bone()
  spine.name = "Spine"
  spine.position.set(0, 1, 0)
  figure.add(spine)

  for (const side of ["Right", "Left"]) {
    const arm = new THREE.Bone()
    arm.name = `${side}Arm`
    arm.position.set(side === "Right" ? -0.2 : 0.2, 0.4, 0)
    const fore = new THREE.Bone()
    fore.name = `${side}ForeArm`
    fore.position.set(0, -0.3, 0)
    const hand = new THREE.Bone()
    hand.name = `${side}Hand`
    hand.position.set(0, -0.3, 0)
    fore.add(hand)
    arm.add(fore)
    spine.add(arm)
  }
  return figure
}

function handAt(figure: THREE.Object3D, name: string) {
  figure.updateWorldMatrix(true, true)
  return figure.getObjectByName(name)!.getWorldPosition(new THREE.Vector3())
}

test("finds the arms whichever way the rig spells its bones", () => {
  const rig = riggingOf(stickFigure())
  expect(rig.swinging).toHaveLength(2)
  expect(rig.holding).toHaveLength(2)
  expect(rig.spine).toHaveLength(1)
})

test("the hammer comes down over the swing", () => {
  const figure = stickFigure()
  const rig = riggingOf(figure)

  poseAt(THREE, figure, rig, 0)
  const raised = handAt(figure, "RightHand")
  poseAt(THREE, figure, rig, 1)
  const struck = handAt(figure, "RightHand")

  expect(struck.y).toBeLessThan(raised.y)
})

test("the hammer swings in the plane the smith faces, not across it", () => {
  // The first attempt turned the arm about the wrong line, which swung it
  // sideways like a gate: it looked like a wave from the front and like
  // nothing at all in profile.
  const figure = stickFigure()
  const rig = riggingOf(figure)

  poseAt(THREE, figure, rig, 0)
  const raised = handAt(figure, "RightHand")
  poseAt(THREE, figure, rig, 1)
  const struck = handAt(figure, "RightHand")

  const sideways = Math.abs(struck.x - raised.x)
  const along = Math.hypot(struck.y - raised.y, struck.z - raised.z)
  expect(sideways).toBeLessThan(along / 10)
})

test("the other hand holds still while the hammer moves", () => {
  const figure = stickFigure()
  const rig = riggingOf(figure)

  poseAt(THREE, figure, rig, 0)
  const early = handAt(figure, "LeftHand")
  poseAt(THREE, figure, rig, 1)
  const late = handAt(figure, "LeftHand")

  // Not frozen -- the waist carries it a little -- but nowhere near a swing.
  expect(early.distanceTo(late)).toBeLessThan(0.1)
})
