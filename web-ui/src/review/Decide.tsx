/**
 * Taking the work, or throwing it away.
 *
 * The only component in the app allowed a non-GET request. Everything else
 * answers "what happened"; these two act, and both act on the reader's own
 * project, so both say plainly what they are about to do first.
 */

import { useState } from "react"

import { accept, discard } from "../api"
import type { Decision } from "../api"
import "./review.css"

function Refusal({ decision }: { decision: Decision }) {
  if (decision.dirty?.length) {
    return (
      <p className="decide-refusal">
        You have uncommitted changes in {decision.dirty.join(", ")}. Commit or
        stash them first — accepting would have to touch the same files.
      </p>
    )
  }
  if (decision.conflict?.length) {
    // No resolve button on purpose: sorting this out belongs in the reader's
    // own editor, with their own history in front of them.
    return (
      <p className="decide-refusal">
        You changed {decision.conflict.join(", ")} too, so this work can't be
        taken as it is. Nothing was moved.
      </p>
    )
  }
  return <p className="decide-refusal">{decision.error || "That didn't work."}</p>
}

export function Decide({
  flow,
  pending,
  into,
  runId,
  onDone,
}: {
  flow: string
  pending: number
  into: string | null
  runId: string | null
  onDone(): void
}) {
  const [busy, setBusy] = useState(false)
  const [asking, setAsking] = useState(false)
  const [refused, setRefused] = useState<Decision | null>(null)

  // Per-work controls always apply; the card's only apply to a waiting pile.
  if (!runId && pending <= 0) return null

  const act = async (go: () => Promise<Decision>) => {
    if (busy) return
    setBusy(true)
    setRefused(null)
    const decision = await go()
    setBusy(false)
    setAsking(false)
    if (decision.ok) onDone()
    else setRefused(decision)
  }

  const preview =
    !runId && into ? ` — adds ${pending} commit${pending === 1 ? "" : "s"} to ${into}` : ""

  return (
    <div className="decide">
      <button
        type="button"
        className="decide-take"
        data-do="accept"
        disabled={busy}
        onClick={() => void act(() => accept(flow, runId ?? undefined))}
      >
        {runId ? "accept up to this work" : "accept this work"}
        {preview}
      </button>

      {asking ? (
        <button
          type="button"
          className="decide-drop"
          data-do="discard-confirm"
          disabled={busy}
          onClick={() => void act(() => discard(flow, runId ?? undefined))}
        >
          yes, throw it away
        </button>
      ) : (
        <button
          type="button"
          className="decide-drop"
          data-do="discard"
          disabled={busy}
          onClick={() => setAsking(true)}
        >
          {runId ? "discard from this work onward" : "discard this work"}
        </button>
      )}

      {asking ? (
        <p className="decide-note">
          Thrown away, not deleted — it stays reachable if you need it back.
        </p>
      ) : null}

      {refused ? <Refusal decision={refused} /> : null}
    </div>
  )
}
