/**
 * Saying the work in one's own words, above the fields.
 *
 * The form asks for a name, a folder and a prompt, and a reader who has
 * never written a card knows none of them yet. Here the person says what
 * they want done; the project's model answers, asks what it needs to, and
 * when it can, proposes a card. "Use this draft" puts that card on the form
 * below -- where it is read, changed and saved through the same save as
 * before, and the sentence naming whose files change is still read first.
 *
 * The conversation is the page's: sent whole with every message, kept
 * nowhere, gone when the panel closes. The daemon writes nothing for it, and
 * the folder a draft names is one the project has or is blank -- the form
 * keeps that choice with the person either way.
 */

import { useState } from "react"
import type { KeyboardEvent } from "react"

import { draftTask } from "../api"
import type { DraftAnswer, TaskDraft } from "../api"
import { Refusal } from "../Refusal"
import "./describe.css"

interface Turn {
  role: "user" | "assistant"
  content: string
  /** The card the model proposed with this reply, if it did. */
  draft?: TaskDraft | null
}

/** A draft's schedule in the words the card would use. */
function whenOf(schedule: string): string {
  if (!schedule) return "hourly"
  if (schedule === "loop") return "loop"
  return schedule.split(" ").length === 5 ? `at ${schedule}` : `every ${schedule}`
}

export function Describe({
  project,
  disabled = false,
  onDraft,
}: {
  project: string
  disabled?: boolean
  /** A card the model proposed, for the form to fill itself from. */
  onDraft(draft: TaskDraft): void
}) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState("")
  // The message on its way, shown in the thread while the model thinks. It
  // stays in the box until it was answered: a refusal must not eat it.
  const [sending, setSending] = useState<string | null>(null)
  const [refused, setRefused] = useState<DraftAnswer | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const busy = sending !== null

  const send = async () => {
    const said = text.trim()
    if (!said || busy || disabled) return
    const asked: Turn[] = [...turns, { role: "user", content: said }]
    setSending(said)
    setRefused(null)
    const answer = await draftTask(
      project,
      asked.map(({ role, content }) => ({ role, content })),
    )
    setSending(null)
    if (!answer.ok) {
      setRefused(answer)
      return
    }
    setTurns([...asked, { role: "assistant", content: answer.reply ?? "", draft: answer.draft ?? null }])
    setModel(answer.model ?? null)
    setText("")
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends and Shift+Enter breaks the line, as a chat box does -- but
    // not while an input method is still composing, where Enter commits the
    // characters and a send here would take half a word.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    void send()
  }

  const shown: Turn[] = sending === null ? turns : [...turns, { role: "user", content: sending }]

  return (
    <section className="describe" aria-label="Describe the work">
      {shown.length > 0 ? (
        <ol className="describe-turns">
          {shown.map((turn, index) => (
            <li className="describe-turn" data-role={turn.role} key={index}>
              <span className="describe-who">{turn.role === "user" ? "you" : "poieo"}</span>
              <div className="describe-said">{turn.content}</div>
              {turn.draft ? (
                <div className="describe-card" role="group" aria-label="A card the model proposed">
                  <strong className="describe-card-name">{turn.draft.name}</strong>
                  <span className="describe-card-where">
                    {turn.draft.folder ? (
                      <>
                        in <code>{turn.draft.folder}</code>
                      </>
                    ) : (
                      "folder: choose it on the form"
                    )}
                    {" · "}
                    {whenOf(turn.draft.schedule)}
                  </span>
                  <p className="describe-card-prompt">{turn.draft.prompt}</p>
                  <button
                    type="button"
                    className="describe-use"
                    data-do="use-draft"
                    disabled={disabled}
                    onClick={() => onDraft(turn.draft!)}
                  >
                    use this draft
                  </button>
                </div>
              ) : null}
            </li>
          ))}
        </ol>
      ) : null}
      {busy ? <p className="describe-thinking">thinking…</p> : null}
      {refused ? <Refusal answer={refused} /> : null}
      <form
        className="describe-ask"
        onSubmit={(event) => {
          event.preventDefault()
          void send()
        }}
      >
        <label className="describe-label">
          {turns.length ? "reply" : "describe the work"}
          <textarea
            className="describe-box"
            aria-label="Describe the work"
            rows={2}
            maxLength={4000}
            placeholder="What should it do, where, and how often? e.g. every night, run the tests in src and fix one failure"
            value={text}
            disabled={disabled}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
          />
        </label>
        <div className="describe-row">
          {model ? <span className="describe-model">answered by {model}</span> : null}
          <button type="submit" data-do="describe" disabled={disabled || busy || !text.trim()}>
            {busy ? "asking…" : "ask"}
          </button>
        </div>
      </form>
    </section>
  )
}
