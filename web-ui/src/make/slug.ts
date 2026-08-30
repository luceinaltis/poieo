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
