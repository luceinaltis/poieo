/**
 * Saying the work in one's own words, above the fields.
 *
 * The form asks for a prompt, and a reader who has never written a card does
 * not know what one says. Here the person says what they want done; the
 * project's model answers, asks what it needs to, and when it can, proposes
 * a card. "Use this draft" puts that card on the form below -- where it is
 * read, changed and saved through the same save as before, and the sentence
 * naming whose files change is still read first. Three examples under the
 * box are there for the person who does not know what to ask for: pressing
 * one puts it in the box to be changed or sent.
 *
 * The conversation is the page's: sent whole with every message, kept
 * nowhere, gone when the panel closes. The daemon writes nothing for it, and
 * the folder a draft names is one inside the project or is blank -- blank
 * leaves the task working in the whole project, as any card made here does
 * unless it is narrowed.
 */

import { useRef, useState } from "react"
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

/** What a first task tends to be, for somebody who does not know what to ask for. */
const EXAMPLES = [
  "every night, run the tests and fix one failure",
  "tidy the docs and fix what is out of date",
  "read the newest open issue and draft an answer",
]

/** A draft's schedule in the words the card would use. */
function whenOf(schedule: string): string {
  if (!schedule) return "hourly"
  if (schedule === "loop") return "loop"
  return schedule.split(" ").length === 5 ? `at ${schedule}` : `every ${schedule}`
}

/**
 * Whether a refusal is about the model rather than the message. The daemon's
 * three model refusals -- no models file, a role that resolves to nothing,
 * an endpoint that did not answer -- each say so in the word; a bounded
 * conversation or a bad body does not.
 */
function aboutTheModel(answer: DraftAnswer): boolean {
  return /model/i.test(answer.error ?? "")
}

export function Describe({
  project,
  disabled = false,
  onDraft,
  onModels,
}: {
  project: string
  disabled?: boolean
  /** A card the model proposed, for the form to fill itself from. */
  onDraft(draft: TaskDraft): void
  /** The models panel, for a refusal that says no model could answer. */
  onModels?(opener: HTMLElement): void
}) {
  const [turns, setTurns] = useState<Turn[]>([])
  const [text, setText] = useState("")
  // The message on its way, shown in the thread while the model thinks. It
  // stays in the box until it was answered: a refusal must not eat it.
  const [sending, setSending] = useState<string | null>(null)
  const [refused, setRefused] = useState<DraftAnswer | null>(null)
  const [model, setModel] = useState<string | null>(null)
  const box = useRef<HTMLTextAreaElement>(null)
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
                      "in this project"
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
      {refused ? (
        <Refusal answer={refused}>
          {onModels && aboutTheModel(refused) ? (
            <>
              {" "}
              <button
                type="button"
                className="describe-models"
                data-do="describe-models"
                onClick={(event) => onModels(event.currentTarget)}
              >
                open models
              </button>
            </>
          ) : null}
        </Refusal>
      ) : null}
      <form
        className="describe-ask"
        onSubmit={(event) => {
          event.preventDefault()
          void send()
        }}
      >
        <label className="describe-label">
          {turns.length ? "reply" : "what should it do?"}
          <textarea
            ref={box}
            className="describe-box"
            aria-label="Describe the work"
            rows={2}
            maxLength={4000}
            placeholder="in your own words, in any language"
            value={text}
            disabled={disabled}
            onChange={(event) => setText(event.target.value)}
            onKeyDown={onKeyDown}
          />
        </label>
        {/* Only before the first word: once there is a conversation, or
            something typed, the examples would be noise under it. */}
        {turns.length === 0 && !text && !busy ? (
          <div className="describe-examples" role="group" aria-label="Examples to try">
            <span aria-hidden="true">try</span>
            {EXAMPLES.map((example) => (
              <button
                type="button"
                key={example}
                data-do="describe-example"
                disabled={disabled}
                onClick={() => {
                  setText(example)
                  box.current?.focus()
                }}
              >
                {example}
              </button>
            ))}
          </div>
        ) : null}
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
