/**
 * The one thing on this page that only a person can do.
 *
 * A `confirm` node ends its run with a question rather than doing something
 * that cannot be undone -- a push, a merge, a deployment. Everything after it
 * is held until this is answered, so a question nobody notices is a run that
 * never finishes: it is drawn first in the drawer, above the controls.
 *
 * No confirmation step, unlike Decide. The graph's author already wrote the
 * question, and asking "are you sure?" over the top of somebody else's
 * sentence would only make it easier to stop reading it.
 */

import { answer } from "../api"
import type { AnswerReply } from "../api"
import { Refusal } from "../Refusal"
import type { Question as Asked } from "../types"
import { useAct } from "../useAct"

export function Question({
  project,
  task,
  asking,
  onAnswered,
}: {
  project: string
  task: string
  asking: Asked | null
  onAnswered(): void
}) {
  const { busy, refused, act } = useAct<AnswerReply>(onAnswered)

  if (!asking) return null

  return (
    <section className="question" data-run={asking.run_id}>
      <p className="question-asked">{asking.question}</p>
      <div className="question-choices">
        {asking.choices.map((choice) => (
          <button
            key={choice}
            type="button"
            data-do={`answer-${choice}`}
            disabled={busy}
            onClick={() => void act(() => answer(project, task, choice))}
          >
            {choice}
          </button>
        ))}
      </div>
      {refused ? (
        <Refusal answer={refused}>
          {refused.choices?.length
            ? ` It is asking for one of: ${refused.choices.join(", ")}.`
            : ""}
        </Refusal>
      ) : null}
    </section>
  )
}
