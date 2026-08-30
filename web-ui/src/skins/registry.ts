/**
 * Which skins exist. Adding one is a module and a line here.
 */

import type { Skin } from "./contract"
import { basic } from "./basic"
import { hours } from "./hours"

export const SKINS: Skin[] = [basic, hours]

// The graph is what answers "what does this project do, and where is it right
// now" -- which is the question a reader opens the page with. hours answers
// the other one, "what has it been doing, and when" -- which the graph cannot
// reach, because it does not put time on the screen.
// basic is also what an unknown or unreadable choice lands on -- including
// "atelier", stored by every reader who tried the 3D workshop before it was
// removed -- so the default and the fallback are one skin rather than two.
export const DEFAULT_SKIN_ID = basic.id

/** A stale or unknown id -- from an old localStorage value -- must not blank
 * the page, so it lands on the fallback skin instead. */
export function skinById(id: string | null | undefined): Skin {
  return SKINS.find((skin) => skin.id === id) ?? basic
}
