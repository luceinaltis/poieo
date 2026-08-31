/**
 * Timestamps as this page shows them.
 *
 * The daemon writes ISO strings; a reader wants a clock. An unparseable one
 * is shown as it arrived rather than as "Invalid Date" -- whatever the
 * daemon actually wrote is more use than the browser's opinion of it.
 */

export function shortTime(iso: string): string {
  const at = new Date(iso)
  if (Number.isNaN(at.getTime())) return iso
  // The reader's own clock, but a 24-hour one and no seconds. The default
  // format follows the browser's locale into a 12-hour clock with a
  // localised marker, which lands a word of another language in the middle
  // of an English line and is a different width every hour. Seconds go
  // because nothing here is answered by them: "last looked 21:56" is the
  // whole of what the line is for.
  return at.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", hour12: false })
}
