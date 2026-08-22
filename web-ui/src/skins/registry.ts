/**
 * Which skins exist. Adding one is a module and a line here.
 */

import { atelier } from "./atelier"
import type { Skin } from "./contract"
import { ledger } from "./ledger"

// ledger first: it is the fallback and the default, and listing a skin here
// must not pull its renderer in -- atelier's PixiJS stays behind a dynamic
// import inside its own module.
export const SKINS: Skin[] = [ledger, atelier]

export const DEFAULT_SKIN_ID = ledger.id

/** A stale or unknown id -- from an old localStorage value -- must not blank
 * the page, so it lands on the fallback skin instead. */
export function skinById(id: string | null | undefined): Skin {
  return SKINS.find((skin) => skin.id === id) ?? ledger
}
