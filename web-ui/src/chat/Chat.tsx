/**
 * A conversation with the project's model, beside the board.
 *
 * The models panel says which models this project can reach; this is where a
 * person hears one. A message goes to the model the project's `default` role
 * names -- what a plain card gets -- and the reply says which model that was,
 * so a switch made in the terminal shows up in the next answer.
 *
 * The thread is the page's. The shell holds it, so a visit to a task's drawer
 * does not lose it, and it goes with the page. The daemon keeps none of it,
 * offers the model no tools, and starts no run for it.
 */

import { useEffect, useRef, useState } from "react"
import type { KeyboardEvent } from "react"

import { chat } from "../api"
import type { ChatAnswer } from "../api"
import { Refusal } from "../Refusal"
import "./chat.css"

export interface Turn {
  role: "user" | "assistant"
  content: string
  /** Which model answered, as `provider/model`, on the model's turns. */
  model?: string
  /** The model stopped at its token limit rather than at the end of what it had to say. */
  cutShort?: boolean
}

/** The most turns the daemon takes in one conversation. */
export const TURNS_AT_MOST = 30

export function Chat({
  project,
  turns,
  onTurns,
  onClose,
}: {
  project: string
  turns: Turn[]
  onTurns(turns: Turn[]): void
  onClose(): void
}) {
  const [text, setText] = useState("")
  // The message on its way, shown in the thread while the model thinks. It
  // stays in the box until it was answered: a refusal must not eat it.
  const [sending, setSending] = useState<string | null>(null)
  const [refused, setRefused] = useState<ChatAnswer | null>(null)
  const threadRef = useRef<HTMLDivElement>(null)
  const busy = sending !== null
  const full = turns.length >= TURNS_AT_MOST
  const shown: Turn[] = sending === null ? turns : [...turns, { role: "user", content: sending }]
  const answeredBy = [...turns].reverse().find((turn) => turn.model)?.model ?? null

  // A thread is read from its newest line: keep that one in view.
  useEffect(() => {
    const thread = threadRef.current
    if (thread) thread.scrollTop = thread.scrollHeight
  }, [shown.length])

  const send = async () => {
    const said = text.trim()
    if (!said || busy || full) return
    const asked: Turn[] = [...turns, { role: "user", content: said }]
    setSending(said)
    setRefused(null)
    const answer = await chat(
      project,
      asked.map(({ role, content }) => ({ role, content })),
    )
    setSending(null)
    if (!answer.ok) {
      setRefused(answer)
      return
    }
    const reply: Turn = { role: "assistant", content: answer.reply ?? "", model: answer.model }
    if (answer.cut_short) reply.cutShort = true
    onTurns([...asked, reply])
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

  return (
    <aside className="panel chat" aria-label="Chat">
      <header className="chat-head">
        <h2>chat</h2>
        <span className="chat-model" title={answeredBy ?? undefined}>
          {answeredBy ? `answered by ${answeredBy}` : ""}
        </span>
        {turns.length ? (
          <button
            type="button"
            className="chat-new"
            data-do="chat-new"
            disabled={busy}
            onClick={() => {
              onTurns([])
              setRefused(null)
            }}
          >
            new conversation
          </button>
        ) : null}
        <button type="button" className="chat-close" aria-label="Close" onClick={onClose}>
          ✕
        </button>
      </header>
      <div className="chat-thread" ref={threadRef}>
        {shown.length ? (
          <ol className="chat-turns">
            {shown.map((turn, index) => (
              <li className="chat-turn" data-role={turn.role} key={index}>
                <span className="chat-who">
                  {turn.role === "user" ? "you" : (turn.model ?? "model")}
                </span>
                {/* An empty bubble reads as broken. A thinking model can spend
                    its whole budget thinking and say nothing, and the words
                    for that are the fix: raise the limit in the models file. */}
                <div className="chat-said">
                  {turn.content || <span className="chat-nothing">the model said nothing</span>}
                </div>
                {turn.cutShort ? (
                  <span className="chat-cut">
                    cut short at the model's token limit: raise max_tokens for default in the models
                    file
                  </span>
                ) : null}
              </li>
            ))}
          </ol>
        ) : (
          <p className="chat-empty">
            Talk with this project's model. The conversation stays on this page: nothing is
            kept, and no run is started.
          </p>
        )}
        {busy ? (
          <p className="chat-thinking" role="status">
            thinking…
          </p>
        ) : null}
      </div>
      {full ? (
        <p className="chat-full" role="status">
          This conversation is as long as one gets. Start a new one to go on.
        </p>
      ) : null}
      {refused ? <Refusal answer={refused} /> : null}
      <form
        className="chat-ask"
        onSubmit={(event) => {
          event.preventDefault()
          void send()
        }}
      >
        <textarea
          className="chat-box"
          aria-label="Message"
          rows={2}
          maxLength={4000}
          placeholder="Ask anything. Enter sends, Shift+Enter breaks the line."
          value={text}
          disabled={full}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="chat-row">
          <button type="submit" data-do="chat-send" disabled={busy || full || !text.trim()}>
            {busy ? "sending…" : "send"}
          </button>
        </div>
      </form>
    </aside>
  )
}
