import * as THREE from "three"
import { expect, test } from "vitest"

import { headFrame, makeFace } from "./face"

/**
 * A rig shaped like the ones the generator actually produces: the head bone at
 * the top of the skull rather than its base, and shoulders that do not straddle
 * the body evenly. Both have caused eyelids to be hung in the wrong place.
 */
function stickFigure() {
  const figure = new THREE.Group()

  // Something with a silhouette, so the crown can be measured at all, and
  // enough vertices on it to answer "is the lid touching him".
  const body = new THREE.Mesh(new THREE.BoxGeometry(0.5, 1.8, 0.3, 6, 20, 4))
  body.position.y = 0.9
  figure.add(body)

  const bone = (name: string, x: number, y: number, z = 0) => {
    const made = new THREE.Bone()
    made.name = name
    made.position.set(x, y, z)
    figure.add(made)
    return made
  }

  bone("neck", 0.03, 1.52)
  bone("Head", 0.008, 1.81)
  bone("RightShoulder", -0.09, 1.4)
  bone("LeftShoulder", 0.19, 1.4)
  bone("RightUpLeg", -0.02, 0.85)
  bone("LeftUpLeg", 0.12, 0.85)
  bone("RightFoot", -0.02, 0.1)
  bone("LeftFoot", 0.12, 0.1)

  figure.updateWorldMatrix(true, true)
  return figure
}

test("measures the skull from the neck, not from a head bone above the crown", () => {
  const head = headFrame(THREE, stickFigure())!
  expect(head).not.toBeNull()
  expect(head.tall).toBeCloseTo(1.8 - 1.52, 2)
  expect(head.centre.y).toBeCloseTo(1.8 - 0.14, 2)
})

test("takes the centre line from the body, not from the head bone", () => {
  // The head bone here sits at x 0.008 while the body straddles x 0.05.
  const head = headFrame(THREE, stickFigure())!
  expect(head.centre.x).toBeCloseTo(0.05, 2)
})

test("hangs the lids on the head, between the neck and the crown", () => {
  const figure = stickFigure()
  const face = makeFace(THREE, figure)!
  expect(face).not.toBeNull()

  face.at(0)
  figure.updateWorldMatrix(true, true)
  const eyes = figure
    .getObjectByName("blink")!
    .children.map((eye) => eye.getWorldPosition(new THREE.Vector3()))

  expect(eyes).toHaveLength(2)
  for (const eye of eyes) {
    expect(eye.y).toBeGreaterThan(1.52)
    expect(eye.y).toBeLessThan(1.8)
  }
})

test("blinks now and then rather than all the time", () => {
  const figure = stickFigure()
  const face = makeFace(THREE, figure)!

  const shut = (elapsed: number) => {
    face.at(elapsed)
    return figure.getObjectByName("blink")!.visible
  }

  expect(shut(0)).toBe(true)
  expect(shut(500)).toBe(false)
  expect(shut(2000)).toBe(false)
  // and again on the next turn of the clock
  expect(shut(3600)).toBe(true)
})

test("two smiths do not blink in step", () => {
  const one = stickFigure()
  const other = stickFigure()
  makeFace(THREE, one, 0)!.at(0)
  makeFace(THREE, other, 1800)!.at(0)

  const lidsOf = (figure: THREE.Object3D) => figure.getObjectByName("blink")!.visible

  expect(lidsOf(one)).toBe(true)
  expect(lidsOf(other)).toBe(false)
})

test("no lids at all when they would not land on the face", () => {
  // Two rigs measured the same way put the lids in two different places, and
  // on the second they hung in the room beside his cheek. A skull that cannot
  // be read is a reason to skip blinking, not to hang a card in mid-air.
  //
  // Here the skin and the skeleton disagree: the bones say the middle of him
  // is at the origin and the body says it is a metre to the left, which is the
  // shape the real failure had.
  const figure = stickFigure()
  const body = figure.children.find((node) => (node as any).geometry)!
  body.position.x += 1
  figure.updateWorldMatrix(true, true)

  expect(makeFace(THREE, figure)).toBeNull()
  expect(figure.getObjectByName("blink")).toBeUndefined()
})
