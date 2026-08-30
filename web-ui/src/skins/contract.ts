/**
 * What a skin is.
 *
 * A skin renders a StageState and takes callbacks. It never fetches, never
 * sees a raw event, and never keeps state of its own beyond what it needs to
 * draw. Everything a skin could want to know has to arrive in StageState --
 * if it does not, the reducer is wrong, not the skin.
 *
 * `mount` is synchronous on purpose. A skin whose renderer has to be loaded
 * returns its handle at once and swaps the renderer in later -- the removed
 * 3D workshop worked this way; making this a promise would push waiting onto
 * the shell and onto every future skin to serve one skin's private problem.
 */

import type { StageState } from "../state/stage"

export interface SkinCallbacks {
  onSelectTask(task: string): void
}

export interface SkinHandle {
  update(stage: StageState): void
  destroy(): void
}

export interface Skin {
  id: string
  label: string
  /**
   * A place of its own on the rail, rather than a rendering of the board.
   *
   * The picker on the bar answers "how should the board be drawn"; the rail
   * answers "what did you come to this page for". A skin that answers a
   * different question from the board -- hours answers *when*, the board
   * answers *what and where* -- is the second kind, and listing it among the
   * renderings made a place look like a font choice.
   */
  standalone?: boolean
  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle
}
