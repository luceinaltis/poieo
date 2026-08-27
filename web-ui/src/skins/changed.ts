/**
 * Which tasks actually changed since a skin last painted them.
 *
 * The reducer keeps object identity for every flowState a frame did not touch,
 * so reference equality is the whole test. Skins repaint on every SSE frame;
 * without this, a board of N tasks rebuilds N-1 cards because one of them
 * spoke.
 */

import type { TaskState } from "../state/stage"

export function changedTasks(
  tasks: Record<string, TaskState>,
  painted: Map<string, TaskState>,
): [string, TaskState][] {
  const changed: [string, TaskState][] = []
  for (const [task, flowState] of Object.entries(tasks)) {
    if (painted.get(task) !== flowState) {
      painted.set(task, flowState)
      changed.push([task, flowState])
    }
  }
  // A task that left the board is forgotten, so its return paints again.
  for (const task of painted.keys()) {
    if (!(task in tasks)) painted.delete(task)
  }
  return changed
}
