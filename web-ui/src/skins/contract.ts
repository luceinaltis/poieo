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
  /** The control is the place focus returns when the task panel closes. */
  onSelectTask(task: string, opener: HTMLElement): void
  /**
   * The one thing a card may do without opening the task: run it now, or
   * resume it when it is held. Answers with the daemon's refusal, if any, for
   * the card to say. A shell that cannot act leaves it out and no button shows.
   */
  onAct?(task: string, verb: "run" | "resume"): Promise<{ ok: boolean; error?: string }>
}

export interface SkinHandle {
  update(stage: StageState): void
  destroy(): void
  /**
   * Which task the reader has open in the panel, or null. A skin that draws
   * the task marks it and brings it into view; one that does not may leave
   * this out.
   */
  select?(task: string | null): void
}

export interface Skin {
  id: string
  label: string
  /**
   * A place of its own among the bar's tabs, rather than a rendering of the board.
   *
   * The picker on the bar answers "how should the board be drawn"; the tabs
   * answers "what did you come to this page for". A skin that answers a
   * different question from the board -- runs answers *when*, the board
   * answers *what and where* -- is the second kind, and listing it among the
   * renderings made a place look like a font choice.
   */
  standalone?: boolean
  mount(el: HTMLElement, callbacks: SkinCallbacks): SkinHandle
}
