/**
 * What a skin is.
 *
 * A skin renders a StageState and takes callbacks. It never fetches, never
 * sees a raw event, and never keeps state of its own beyond what it needs to
 * draw. Everything a skin could want to know has to arrive in StageState --
 * if it does not, the reducer is wrong, not the skin.
 *
 * `mount` is synchronous on purpose. A skin whose renderer has to be loaded
 * (see atelier) returns its handle at once and swaps the renderer in later;
 * making this a promise would push waiting onto the shell and onto every
 * future skin to serve one skin's private problem.
 */

import type { StageState } from "../state/stage"

export interface SkinCallbacks {
  onSelectWorker(flow: string): void
}

export interface SkinHandle {
  update(stage: StageState): void
  destroy(): void
}

export interface Skin {
  id: string
  label: string
  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle
}
