/**
 * Which skins exist. Adding one is a module and a line here.
 */

import { atelier } from "./atelier"
import type { Skin } from "./contract"
import { basic } from "./basic"
import { hours } from "./hours"

// Listing a skin here must not pull its renderer in: atelier's three.js stays
// behind a dynamic import inside its own module.
export const SKINS: Skin[] = [basic, hours, atelier]

// The graph is what answers "what does this project do, and where is it right
// now" -- which is the question a reader opens the page with. atelier answers a
// different and better one, "is it working", and is a click away for that.
// hours answers the third: what has it been doing, and when -- the question the
// other two cannot reach, because neither puts time on the screen.
// basic is also what an unknown or unreadable choice lands on, so the default
// and the fallback are now one skin rather than two.
export const DEFAULT_SKIN_ID = basic.id

/** A stale or unknown id -- from an old localStorage value -- must not blank
 * the page, so it lands on the fallback skin instead. */
export function skinById(id: string | null | undefined): Skin {
  return SKINS.find((skin) => skin.id === id) ?? basic
}
