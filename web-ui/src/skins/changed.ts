/**
 * Which workers actually changed since a skin last painted them.
 *
 * The reducer keeps object identity for every worker a frame did not touch,
 * so reference equality is the whole test. Skins repaint on every SSE frame;
 * without this, a board of N flows rebuilds N-1 cards because one of them
 * spoke.
 */

import type { Worker } from "../state/stage"

export function changedWorkers(
  workers: Record<string, Worker>,
  painted: Map<string, Worker>,
): [string, Worker][] {
  const changed: [string, Worker][] = []
  for (const [flow, worker] of Object.entries(workers)) {
    if (painted.get(flow) !== worker) {
      painted.set(flow, worker)
      changed.push([flow, worker])
    }
  }
  // A flow that left the board is forgotten, so its return paints again.
  for (const flow of painted.keys()) {
    if (!(flow in workers)) painted.delete(flow)
  }
  return changed
}
