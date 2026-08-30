/**
 * Taking a run's change, or throwing it away.
 *
 * The only component whose requests can move the reader's own files --
 * Control's verbs stop at the daemon. Both actions here are about the
 * reader's project, so both say plainly what they are about to do first.
 */

import { useState } from "react"

import { accept, discard } from "../api"
import type { Decision } from "../api"
import { Refusal } from "../Refusal"
import { useAct } from "../useAct"
import "./review.css"

/**
 * The two refusals this surface can say better than the daemon can.
 *
 * Both are about the reader's own checkout rather than the run, so both name
 * the files and say that nothing moved. Anything else falls through to the
 * daemon's sentence.
 */
function WhyRefused({ decision }: { decision: Decision }) {
  if (decision.dirty?.length) {
    return (
      <Refusal>
        You have uncommitted changes in {decision.dirty.join(", ")}. Commit or
        stash them first — accepting would have to touch the same files.
      </Refusal>
    )
  }
  if (decision.conflict?.length) {
    // No resolve button on purpose: sorting this out belongs in the reader's
    // own editor, with their own history in front of them.
    return (
      <Refusal>
        You changed {decision.conflict.join(", ")} too, so this run can't be
        taken as it is. Nothing was moved.
      </Refusal>
    )
  }
  return <Refusal answer={decision} />
}

export function Decide({
  project,
  task,
  pending,
  into,
  runId,
  onDone,
}: {
  project: string
  task: string
  pending: number
  into: string | null
  runId: string | null
  onDone(): void
}) {
  const [asking, setAsking] = useState(false)
  const { busy, refused, act: send } = useAct<Decision>(onDone)

  // Per-run controls always apply; the card's only apply to a waiting pile.
  if (!runId && pending <= 0) return null

  // Once a request has actually gone out the confirmation step is over: the
  // reader either got what they asked for or got told why not, and being
  // asked again is noise. A click that found one already in flight changes
  // nothing, including this.
  const act = async (go: () => Promise<Decision>) => {
    if (await send(go)) setAsking(false)
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
        onClick={() => void act(() => accept(project, task, runId ?? undefined))}
      >
        {runId ? "accept up to this run" : "accept this run"}
        {preview}
      </button>

      {asking ? (
        <button
          type="button"
          className="decide-drop"
          data-do="discard-confirm"
          disabled={busy}
          onClick={() => void act(() => discard(project, task, runId ?? undefined))}
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
          {runId ? "discard from this run onward" : "discard this run"}
        </button>
      )}

      {asking ? (
        <p className="decide-note">
          Thrown away, not deleted — it stays reachable if you need it back.
        </p>
      ) : null}

      {refused ? <WhyRefused decision={refused} /> : null}
    </div>
  )
}
