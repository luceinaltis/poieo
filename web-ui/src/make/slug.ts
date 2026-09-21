/**
 * The filename a title becomes, as the daemon would spell it.
 *
 * A mirror of the server's `_slug`, kept case for case by `slug.test.ts`:
 * the whole point of warning about a taken name while it is being typed is
 * agreeing with the refusal that would otherwise come after save. Unicode
 * letters survive, as they do there -- a Korean title is a card too -- via
 * `\p{L}\p{N}_` where Python spells unicode `\w`.
 */
export function slugOf(title: string): string {
  return title
    .trim()
    .toLowerCase()
    .replace(/[^\p{L}\p{N}_-]+/gu, "-")
    .replace(/^-+|-+$/g, "")
}

/**
 * A title for a card whose name was left blank: the first line of its
 * prompt, cut at the first sentence when that comes soon enough, otherwise
 * at the last word that fits. A name is a title on the board and a filename
 * on disk, and both read better short.
 */
export function titleOf(text: string): string {
  const line = text.split("\n").map((one) => one.trim()).find(Boolean) ?? ""
  // A full stop ends a sentence only before a space or the end, or "v2.0"
  // would be cut in half; the ideographic one is never followed by a space
  // and is a boundary on its own.
  const stop = line.search(/[.!?](\s|$)|。/u)
  let title = stop > 0 && stop <= 60 ? line.slice(0, stop) : line
  if (title.length > 60) {
    const cut = title.lastIndexOf(" ", 60)
    title = cut > 20 ? title.slice(0, cut) : title.slice(0, 60)
  }
  return title.replace(/[\s.,;:!?。]+$/u, "")
}
