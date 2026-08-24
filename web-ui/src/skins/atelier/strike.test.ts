import { expect, test } from "vitest"

import {
  FLASH_LIFE,
  LIGHT_LIFE,
  SPARKS,
  SPARK_LIFE,
  WORK_PACE,
  flashFade,
  flashSpread,
  lightPower,
  sparkFade,
  spray,
} from "./strike"

/** The swing clip Meshy returned, in its own seconds. */
const SWING = 1.9

function heights(burst: number, since: number): number[] {
  const spots = new Float32Array(SPARKS * 3)
  spray(burst, since, spots)
  return Array.from({ length: SPARKS }, (_, i) => spots[i * 3 + 1])
}

test("the burst lasts long enough to be seen on a phone", () => {
  // The complaint that started this: on a handset the sparks were gone before
  // an eye found them. A tenth of a second is a frame or six; a second is a
  // thing that happened.
  expect(SPARK_LIFE).toBeGreaterThan(1)
})

test("the burst is over well before the next blow lands", () => {
  // Sparks still in the air when the hammer comes down again read as a fire,
  // not as a strike.
  const period = SWING / WORK_PACE
  expect(SPARK_LIFE).toBeLessThan(period * 0.5)
})

test("the flash outlives its own light, and the sparks outlive both", () => {
  expect(LIGHT_LIFE).toBeLessThan(FLASH_LIFE)
  expect(FLASH_LIFE).toBeLessThan(SPARK_LIFE)
})

test("an ember is still near full brightness halfway through its flight", () => {
  // A linear fade from the first frame is half gone at the midpoint, which is
  // about when a glance arrives -- so the burst looked shorter than it was.
  expect(sparkFade(SPARK_LIFE / 2)).toBeGreaterThan(0.95)
  expect(sparkFade(SPARK_LIFE * 0.8)).toBeGreaterThan(0.4)
})

test("nothing is drawn before the blow or after the burst", () => {
  expect(sparkFade(0)).toBe(0)
  expect(sparkFade(-0.1)).toBe(0)
  expect(sparkFade(SPARK_LIFE)).toBe(0)
  expect(flashFade(FLASH_LIFE)).toBe(0)
  expect(lightPower(LIGHT_LIFE)).toBe(0)
})

test("the flash is brightest at the moment of impact and decays", () => {
  expect(flashFade(0.01)).toBeGreaterThan(0.9)
  expect(flashFade(FLASH_LIFE / 2)).toBeLessThan(flashFade(0.01))
  expect(flashSpread(FLASH_LIFE)).toBeGreaterThan(flashSpread(0))
  expect(lightPower(0.01)).toBeGreaterThan(20)
})

test("embers rise and fall rather than crawling outward", () => {
  // Lengthening the burst must not turn the same arc into slow motion: they
  // are thrown with a velocity and pulled down, so a longer life means a
  // taller arc and a landing, not a stretched one.
  const early = heights(0, 0.15)
  const peak = heights(0, SPARK_LIFE * 0.35)
  const late = heights(0, SPARK_LIFE * 0.98)

  expect(Math.max(...peak)).toBeGreaterThan(Math.max(...early))
  // Every one of them is on the way down by the time it goes out -- the
  // slowest has already fallen past the work.
  expect(late.every((y, i) => y < peak[i])).toBe(true)
  expect(Math.min(...late)).toBeLessThan(0)
})

test("embers spread out from the work rather than sitting on it", () => {
  const spots = new Float32Array(SPARKS * 3)
  spray(0, SPARK_LIFE * 0.5, spots)
  const reach = Array.from({ length: SPARKS }, (_, i) =>
    Math.hypot(spots[i * 3], spots[i * 3 + 2]),
  )
  expect(Math.min(...reach)).toBeGreaterThan(0.1)
  expect(Math.max(...reach)).toBeLessThan(0.6)
})

test("the same blow throws the same sparks, a later blow throws different ones", () => {
  // A filmed replay has to land where the live run did, so the spray is
  // hashed rather than random -- but two blows in a row must not be identical.
  expect(heights(4, 0.3)).toEqual(heights(4, 0.3))
  expect(heights(5, 0.3)).not.toEqual(heights(4, 0.3))
})
