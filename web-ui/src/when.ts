/**
 * Timestamps as this page shows them.
 *
 * The daemon writes ISO strings; a reader wants a clock. An unparseable one
 * is shown as it arrived rather than as "Invalid Date" -- whatever the
 * daemon actually wrote is more use than the browser's opinion of it.
 */

export function shortTime(iso: string): string {
  const at = new Date(iso)
  return Number.isNaN(at.getTime()) ? iso : at.toLocaleTimeString()
}
