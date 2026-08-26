/**
 * What a blow looks like, measured in real seconds.
 *
 * The sparks and the flash used to be timed against the swing clip's own
 * clock, which does not run at one second per second -- it runs at WORK_PACE.
 * So "a quarter second of sparks" was written and a fraction of that arrived,
 * and on a phone held at arm's length the burst was over before an eye found
 * it. Every span here is wall-clock; index.ts divides the clip's clock by the
 * pace once, at the boundary, and nothing downstream remembers the conversion.
 *
 * Pure functions of the time since the hammer landed, so tools and tests can
 * ask what the burst is doing at any moment without a renderer.
 */

/**
 * How fast the clips play.
 *
 * These were set while the board's clock counted frames rather than seconds
 * (see clock.ts), so what anybody watched was the pace multiplied by their own
 * frame rate: on a 240 Hz screen, near four times this. The swing was 0.65 and
 * looked right at 2.5, and the number that was actually being judged all along
 * is the one below.
 *
 * A smith's blow lands every 0.5 to 1.0 seconds -- 60 to 120 a minute is hand
 * hammering. The swing clip is 1.87 s, so 2.5 puts a blow every 0.75 s, in the
 * middle of that. At 0.65 it was one every 2.9 s, which is not a man working.
 *
 * The idle plays as captured. A man standing still does not stand still faster.
 */
export const WORK_PACE = 2.5
export const REST_PACE = 1

/**
 * How long the sparks stay in the air.
 *
 * A bench keeps one set of embers and the next blow resets them, so this has
 * to fit inside the gap between blows -- 1.87 / WORK_PACE, which is 0.75 s --
 * or a burst is cut off in mid-flight and the ones still climbing vanish. It
 * also has to leave a gap, or the anvil is never seen without sparks over it
 * and the whole thing reads as a fire rather than as a man hitting something.
 */
export const SPARK_LIFE = 0.5

/** How long the work glows white from the blow. Still a flash, not a lamp. */
export const FLASH_LIFE = 0.28

/** The light behind the flash, which is what the room reads rather than the work. */
export const LIGHT_LIFE = 0.18

/** How many embers a blow throws. */
export const SPARKS = 28

/**
 * The throw: world units per second, and per second squared.
 *
 * Real ballistics rather than an arc stretched to fit -- an ember is thrown
 * and pulled down, so it peaks and lands on its own schedule, and a longer
 * life would mean a taller arc rather than slow motion. Which is also why
 * these have to be tuned to SPARK_LIFE and not merely fit inside it: too
 * gentle a throw and the embers go out on the way up, still climbing. This is
 * what a burst that begins and ends within half a second looks like.
 *
 * Not earth's gravity, which drops an ember out of frame in a third of a
 * second, at the scale a bench is drawn.
 */
const GRAVITY = 14
const THROWN = { least: 2.2, more: 2.0 }
const OUTWARD = { least: 0.65, more: 1.05 }

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
    const out = OUTWARD.least + scatter(i * 7.3 + burst * 5) * OUTWARD.more
    const up = THROWN.least + scatter(i * 11.7 + burst * 3) * THROWN.more
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
