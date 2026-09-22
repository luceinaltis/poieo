/**
 * What starts when this task finishes: its connections to other tasks.
 *
 * The board drew these wires long before it could make one -- connecting two
 * tasks meant opening a card's file and writing a `then:` with a condition in
 * the expression language. Here it is a task from a list and a condition in
 * words, and the daemon splices the result into the card's own text so a
 * comment or a field no form shows is kept.
 *
 * **Each connection starts a new run of the other task.** Not a next step of
 * this one: a run of its own, with its own change to accept. That is why the
 * words say "start".
 *
 * The conditions offered are the four a person asks for. A condition written
 * by hand is shown by its word and sent back exactly as it was, so this form
 * never loses what it cannot say.
 */

import { useState } from "react"

import { connect, fetchCard } from "../api"
import type { Connection, RewrittenCard } from "../api"
import { Refusal } from "../Refusal"
import { useAct } from "../useAct"

/** The conditions as the form offers them, and the expression each one writes. */
const WHEN = [
  { value: "always", label: "whenever it finishes" },
  { value: "succeeded", label: "if it succeeded" },
  { value: "failed", label: "if it failed" },
  { value: "says", label: "if its answer says…" },
] as const

type When = (typeof WHEN)[number]["value"]

/** A word as a condition can quote it: lower case, and nothing that ends the quote. */
const wordOf = (text: string) => text.trim().toLowerCase().replace(/['\\]/g, "")

function written(when: When, word: string): Pick<Connection, "when" | "label"> {
  if (when === "succeeded") return { when: "run.status == 'completed'", label: "succeeded" }
  if (when === "failed") return { when: "run.status == 'failed'", label: "failed" }
  if (when === "says") return { when: `'${wordOf(word)}' in str(run.outputs).lower()`, label: wordOf(word) }
  return { when: "true", label: null }
}

/** A connection's condition in words: one this form wrote, or the word it was given. */
function said(arrow: Connection): string {
  if (arrow.when === "true") return "whenever it finishes"
  if (arrow.when === "run.status == 'completed'") return "if it succeeded"
  if (arrow.when === "run.status == 'failed'") return "if it failed"
  const word = /^'(.*)' in str\(run\.outputs\)\.lower\(\)$/.exec(arrow.when)
  if (word) return `if its answer says “${word[1]}”`
  return arrow.label ? `when “${arrow.label}”` : `when ${arrow.when}`
}

export function Next({
  project,
  task,
  others,
  onConnected,
}: {
  project: string
  task: string
  /** The tasks in this project, by filename and title. The task itself is left out here. */
  others: { name: string; title: string }[]
  /** The board's chance to redraw its wires. */
  onConnected?(): void
}) {
  const [isOpen, setIsOpen] = useState(false)
  const [then, setThen] = useState<Connection[] | null>(null)
  const [isMissing, setIsMissing] = useState(false)
  const [target, setTarget] = useState("")
  const [when, setWhen] = useState<When>("always")
  const [word, setWord] = useState("")
  const { busy, refused, act } = useAct<RewrittenCard>(() => {})

  const choices = others.filter((other) => other.name !== task)
  const titleOf = (name: string | null) =>
    name === null ? "nothing" : (others.find((other) => other.name === name)?.title ?? name)

  const load = async () => {
    if (then !== null || isMissing) return
    const card = await fetchCard(project, task)
    if (card === null) setIsMissing(true)
    else setThen(card.then ?? [])
  }

  const send = (next: Connection[], onSent?: () => void) =>
    void act(async () => {
      const answer = await connect(project, task, next)
      if (answer.ok) {
        setThen(next)
        onSent?.()
        onConnected?.()
      }
      return answer
    })

  const ready = Boolean(target) && (when !== "says" || Boolean(wordOf(word)))

  return (
    <details className="drawer-card next" onToggle={(event) => setIsOpen(event.currentTarget.open)}>
      <summary aria-expanded={isOpen} onClick={() => void load()}>
        When it finishes
      </summary>

      {isMissing ? (
        <Refusal>The card could not be read. It may have moved on disk.</Refusal>
      ) : then === null ? null : (
        <div className="next-body">
          {then.length === 0 ? (
            <p className="next-none">Nothing starts after it.</p>
          ) : (
            <ul className="next-list">
              {then.map((arrow, index) => (
                <li className="next-row" key={`${arrow.to}-${arrow.when}-${index}`}>
                  <span>
                    start <strong>{titleOf(arrow.to)}</strong> {said(arrow)}
                  </span>
                  <button
                    type="button"
                    data-do="disconnect"
                    disabled={busy}
                    onClick={() => send(then.filter((_, at) => at !== index))}
                  >
                    remove
                  </button>
                </li>
              ))}
            </ul>
          )}

          {choices.length === 0 ? (
            <p className="next-none">This project has no other task to start.</p>
          ) : (
            <div className="next-add">
              <label className="card-field">
                start
                <select name="next-task" value={target} disabled={busy} onChange={(e) => setTarget(e.target.value)}>
                  <option value="">choose a task…</option>
                  {choices.map((other) => (
                    <option key={other.name} value={other.name}>
                      {other.title}
                    </option>
                  ))}
                </select>
              </label>
              <label className="card-field">
                when
                <select
                  name="next-when"
                  value={when}
                  disabled={busy}
                  onChange={(e) => setWhen(e.target.value as When)}
                >
                  {WHEN.map((choice) => (
                    <option key={choice.value} value={choice.value}>
                      {choice.label}
                    </option>
                  ))}
                </select>
              </label>
              {when === "says" ? (
                <label className="card-field">
                  the word
                  <input
                    name="next-word"
                    placeholder="for example: red"
                    value={word}
                    disabled={busy}
                    onChange={(e) => setWord(e.target.value)}
                  />
                </label>
              ) : null}
              <p className="next-note">Each connection starts a new run of that task, with its own change to review.</p>
              <button
                type="button"
                className="next-connect"
                data-do="connect"
                disabled={!ready || busy}
                onClick={() =>
                  send([...then, { ...written(when, word), to: target }], () => {
                    setTarget("")
                    setWhen("always")
                    setWord("")
                  })
                }
              >
                {busy ? "connecting…" : "connect"}
              </button>
            </div>
          )}

          {refused ? <Refusal answer={refused} /> : null}
        </div>
      )}
    </details>
  )
}
