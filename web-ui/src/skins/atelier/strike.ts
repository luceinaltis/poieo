/**
 * What a blow looks like, measured in real seconds.
 *
 * The sparks and the flash used to be timed against the swing clip's own
 * clock, which runs at WORK_PACE -- two thirds speed. So "a quarter second of
 * sparks" was written, and 0.28 * 0.65 = 0.18 s of sparks arrived. On a phone
 * held at arm's length the whole burst was over before an eye found it. Every
 * span here is wall-clock; index.ts divides the clip's clock by the pace once,
 * at the boundary, and nothing downstream has to remember the conversion.
 *
 * Pure functions of the time since the hammer landed, so tools and tests can
 * ask what the burst is doing at any moment without a renderer.
 */

/**
 * How fast the clips play. The capture swings like a man in a fight; a smith
 * at his own anvil takes his time, so the swing runs below full speed and a
 * strike lands about every three seconds instead of two.
 */
export const WORK_PACE = 0.65
export const REST_PACE = 0.9

/** How long the sparks stay in the air. */
export const SPARK_LIFE = 1.15

/** How long the work glows white from the blow. Still a flash, not a lamp. */
export const FLASH_LIFE = 0.45

/** The light behind the flash, which is what the room reads rather than the work. */
export const LIGHT_LIFE = 0.3

/** How many embers a blow throws. */
export const SPARKS = 28

/**
 * Weak gravity, in metres per second squared. Real gravity drops an ember out
 * of frame in a third of a second, which is the problem this file exists to
 * fix; at this strength they hang long enough to be seen falling.
 */
const GRAVITY = 2.6

/** A repeatable number in [0, 1) from an integer-ish seed. */
export function scatter(seed: number): number {
  const spun = Math.sin(seed * 127.1 + 311.7) * 43758.5453
  return spun - Math.floor(spun)
}

/**
 * How bright the embers are, `since` seconds after the blow.
 *
 * Held near full for most of the flight and then faded, rather than faded
 * linearly from the first frame: a linear fade is already half gone at the
 * midpoint, which is roughly when a glance arrives.
 */
export function sparkFade(since: number): number {
  if (since <= 0 || since >= SPARK_LIFE) return 0
  return Math.min(1, (1 - since / SPARK_LIFE) / 0.45)
}

/**
 * Where each ember sits, relative to the work, `since` seconds after the blow.
 *
 * Thrown with a velocity and pulled down by GRAVITY, so lengthening the burst
 * makes the embers fly further rather than making the same arc play in slow
 * motion. Directions are hashed from the ember's index and the blow's number,
 * so a filmed replay throws the same sparks the live run did.
 */
export function spray(burst: number, since: number, into: Float32Array): void {
  for (let i = 0; i < SPARKS; i += 1) {
    const angle = scatter(i * 3.1 + burst * 17) * Math.PI * 2
    const out = 0.28 + scatter(i * 7.3 + burst * 5) * 0.45
    const up = 0.95 + scatter(i * 11.7 + burst * 3) * 0.85
    into[i * 3] = Math.cos(angle) * out * since
    into[i * 3 + 1] = 0.04 + up * since - 0.5 * GRAVITY * since * since
    into[i * 3 + 2] = Math.sin(angle) * out * since
  }
}

/** How bright the glow over the work is, `since` seconds after the blow. */
export function flashFade(since: number): number {
  if (since <= 0 || since >= FLASH_LIFE) return 0
  const gone = since / FLASH_LIFE
  return (1 - gone) * (1 - gone)
}

/** How wide that glow has bloomed, in world units. */
export function flashSpread(since: number): number {
  return 0.22 + Math.min(1, Math.max(0, since / FLASH_LIFE)) * 0.55
}

/** How hard the light behind it pushes, `since` seconds after the blow. */
export function lightPower(since: number): number {
  if (since <= 0 || since >= LIGHT_LIFE) return 0
  return 26 * (1 - since / LIGHT_LIFE)
}
