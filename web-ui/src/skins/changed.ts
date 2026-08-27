/**
 * Which flows actually changed since a skin last painted them.
 *
 * The reducer keeps object identity for every flowState a frame did not touch,
 * so reference equality is the whole test. Skins repaint on every SSE frame;
 * without this, a board of N flows rebuilds N-1 cards because one of them
 * spoke.
 */

import type { FlowState } from "../state/stage"

export function changedFlows(
  flows: Record<string, FlowState>,
  painted: Map<string, FlowState>,
): [string, FlowState][] {
  const changed: [string, FlowState][] = []
  for (const [flow, flowState] of Object.entries(flows)) {
    if (painted.get(flow) !== flowState) {
      painted.set(flow, flowState)
      changed.push([flow, flowState])
    }
  }
  // A flow that left the board is forgotten, so its return paints again.
  for (const flow of painted.keys()) {
    if (!(flow in flows)) painted.delete(flow)
  }
  return changed
}
