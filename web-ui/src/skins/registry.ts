/**
 * Which skins exist. Adding one is a module and a line here.
 */

import { atelier } from "./atelier"
import type { Skin } from "./contract"
import { ledger } from "./ledger"
import { smithy } from "./smithy"

// Listing a skin here must not pull its renderer in: atelier's PixiJS stays
// behind a dynamic import inside its own module.
export const SKINS: Skin[] = [atelier, ledger, smithy]

// The workshop is what this page is for. ledger remains the fallback that an
// unknown or unreadable choice lands on.
export const DEFAULT_SKIN_ID = atelier.id

/** A stale or unknown id -- from an old localStorage value -- must not blank
 * the page, so it lands on the fallback skin instead. */
export function skinById(id: string | null | undefined): Skin {
  return SKINS.find((skin) => skin.id === id) ?? ledger
}
