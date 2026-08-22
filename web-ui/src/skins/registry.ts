/**
 * Which skins exist. Adding one is a module and a line here.
 */

import type { Skin } from "./contract"
import { ledger } from "./ledger"

export const SKINS: Skin[] = [ledger]

export const DEFAULT_SKIN_ID = ledger.id

/** A stale or unknown id -- from an old localStorage value -- must not blank
 * the page, so it lands on the fallback skin instead. */
export function skinById(id: string | null | undefined): Skin {
  return SKINS.find((skin) => skin.id === id) ?? ledger
}
