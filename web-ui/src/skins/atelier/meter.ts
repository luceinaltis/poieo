/**
 * The readout behind `?fps`.
 *
 * "It feels slow on my phone" is not a number, and a desktop cannot be made to
 * produce one. Emulating a phone -- a small viewport, three device pixels per
 * CSS pixel, the CPU throttled six times over -- leaves this page at a
 * comfortable sixty frames a second, because what a phone actually runs out of
 * is GPU, and there is no throttle for that.
 *
 * So the board can be asked to say, on the device that is actually struggling,
 * how many frames it draws, how fast its clock runs against a real one, and
 * what each frame costs it. Those three separate the three things that all
 * look like "slow": too few frames, a clock running at the wrong speed, and a
 * scene that is simply too much to draw.
 */

/** What the renderer says one frame cost it. */
export interface Cost {
  calls: number
  triangles: number
}

/**
 * One line: frames drawn per second, the clock's speed against a real one, and
 * the frame's cost.
 *
 * A speed near 1.00 with a low frame rate is a scene too heavy to draw. A speed
 * well under 1.00 is the clock itself, which is a bug and was one -- see
 * clock.ts.
 */
export function reading(
  frames: number,
  realMs: number,
  clockMs: number,
  cost: Cost,
): string {
  if (!(realMs > 0)) return "..."
  const fps = (frames * 1000) / realMs
  const speed = clockMs / realMs
  return (
    `${fps.toFixed(0)} fps   ${speed.toFixed(2)}x speed   ` +
    `${cost.calls} draws   ${Math.round(cost.triangles / 1000)}k tris`
  )
}
