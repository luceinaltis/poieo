/**
 * The workshop's clock.
 *
 * It used to count frames: sixteen milliseconds added per draw, whatever the
 * draw actually cost. On a desktop holding sixty frames a second that is close
 * enough to real time to pass -- 0.96x, and nobody notices four percent. On a
 * phone it is not. Measured on the board with the main thread loaded down to
 * thirty-two frames a second, the whole workshop ran at 0.51x: the swing, the
 * sparks and the fire all in half speed, because every one of them is driven
 * from this one number.
 *
 * So the clock takes its step from the timestamp the frame arrives with, and
 * the workshop runs at the same speed on every machine that can draw it at all.
 */

/**
 * How far the clock may move in one frame, in milliseconds.
 *
 * A backgrounded tab stops being drawn and comes back with a gap of minutes in
 * it. Uncapped, returning to the board fast-forwards through every strike it
 * missed and lands the hammer a dozen times in one frame. Capped, it resumes.
 * Six frames' worth at sixty a second: longer than any hitch worth smoothing,
 * shorter than any absence worth replaying.
 */
export const LONGEST_STEP = 100

/**
 * How far to move the clock, given this frame's timestamp and the last one.
 *
 * A first frame has no last one, and is worth nothing: `before` below zero
 * says so. A timestamp that fails to advance is worth nothing either -- some
 * browsers hand every callback in a batch the same one.
 */
export function step(now: number, before: number): number {
  if (!(before >= 0) || !(now > before)) return 0
  return Math.min(now - before, LONGEST_STEP)
}
