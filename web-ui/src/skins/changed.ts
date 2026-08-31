/**
 * Which tasks actually changed since a skin last painted them.
 *
 * The reducer keeps object identity for every task a frame did not touch,
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
  for (const [task, taskState] of Object.entries(tasks)) {
    if (painted.get(task) !== taskState) {
      painted.set(task, taskState)
      changed.push([task, taskState])
    }
  }
  // A task that left the board is forgotten, so its return paints again.
  for (const task of painted.keys()) {
    if (!(task in tasks)) painted.delete(task)
  }
  return changed
}
