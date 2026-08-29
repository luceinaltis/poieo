/**
 * Mounts one skin at a time into an element the shell owns, and remembers
 * which one the reader picked.
 */

import { DEFAULT_SKIN_ID, skinById } from "../skins/registry"
import type { Skin, SkinCallbacks, SkinHandle } from "../skins/contract"
import type { StageState } from "../state/stage"
import { recall, remember } from "./remember"

const STORAGE_KEY = "poieo.skin"

export function readSkinPreference(): string {
  return recall(STORAGE_KEY, DEFAULT_SKIN_ID)
}

export function writeSkinPreference(id: string): void {
  remember(STORAGE_KEY, id)
}

export interface SkinHost {
  show(id: string): void
  update(stage: StageState): void
  destroy(): void
}

export function createSkinHost(
  el: HTMLElement,
  callbacks: SkinCallbacks,
  resolve: (id: string) => Skin = skinById,
): SkinHost {
  let handle: SkinHandle | null = null
  let currentId = ""
  let latest: StageState | null = null

  return {
    show(id: string) {
      const skin = resolve(id)
      if (handle && skin.id === currentId) return

      handle?.destroy()
      handle = skin.mount(el, callbacks)
      currentId = skin.id
      // Hand over what is on the board now; the next event may be minutes off.
      if (latest) handle.update(latest)
    },

    update(stage: StageState) {
      latest = stage
      handle?.update(stage)
    },

    destroy() {
      handle?.destroy()
      handle = null
      currentId = ""
    },
  }
}
