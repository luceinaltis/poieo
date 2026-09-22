/**
 * A conversation with the project's model, beside the board.
 *
 * The models panel says which models this project can reach; this is where a
 * person hears one. A message goes to the model the project's `default` role
 * names -- what a plain card gets -- and the reply says which model that was,
 * so a switch made in the terminal shows up in the next answer.
 *
 * The reply is read as it is written: when the model thinks aloud its
 * thinking shows first, open while it is the only thing there is to read,
 * and its words arrive under it as they come. Afterwards the thinking waits
 * closed behind a line the reader can open, so the answer leads.
 *
 * The thread is the page's. The shell holds it, so a visit to a task's drawer
 * does not lose it, and it goes with the page. The daemon keeps none of it,
 * offers the model no tools, and starts no run for it.
 */

import { useEffect, useRef, useState } from "react"
import type { KeyboardEvent } from "react"

import { chat } from "../api"
import type { ChatAnswer, ChatPiece } from "../api"
import { Refusal } from "../Refusal"
import "./chat.css"

export interface Turn {
  role: "user" | "assistant"
  content: string
  /** Which model answered, as `provider/model`, on the model's turns. */
  model?: string
  /** The model stopped at its token limit rather than at the end of what it had to say. */
  cutShort?: boolean
  /** What the model thought before it answered, when it thinks aloud. */
  thinking?: string
}

/** The reply on its way: what has arrived so far. */
interface Arriving {
  thinking: string
  text: string
}

/** The most turns the daemon takes in one conversation. */
export const TURNS_AT_MOST = 30

/**
 * The model's thinking, behind a line. Open while it is being written and
 * nothing else has arrived; closed once the words come, and afterwards, so
 * the answer leads and the thinking waits for a reader who wants it.
 */
function Thought({ text, live }: { text: string; live: boolean }) {
  return (
    <details className="chat-thought" open={live || undefined}>
      <summary>{live ? "thinking…" : "thought"}</summary>
      <pre className="chat-thought-text">{text}</pre>
    </details>
  )
}

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
  // The message on its way, shown in the thread while the model answers. It
  // stays in the box until it was answered: a refusal must not eat it.
  const [sending, setSending] = useState<string | null>(null)
  const [arriving, setArriving] = useState<Arriving | null>(null)
  const [refused, setRefused] = useState<ChatAnswer | null>(null)
  const threadRef = useRef<HTMLDivElement>(null)
  const busy = sending !== null
  const full = turns.length >= TURNS_AT_MOST
  const shown: Turn[] = sending === null ? turns : [...turns, { role: "user", content: sending }]
  const answeredBy = [...turns].reverse().find((turn) => turn.model)?.model ?? null

  // A thread is read from its newest line: keep that one in view, as it grows.
  useEffect(() => {
    const thread = threadRef.current
    if (thread) thread.scrollTop = thread.scrollHeight
  }, [shown.length, arriving?.thinking.length, arriving?.text.length])

  const send = async () => {
    const said = text.trim()
    if (!said || busy || full) return
    const asked: Turn[] = [...turns, { role: "user", content: said }]
    setSending(said)
    setArriving({ thinking: "", text: "" })
    setRefused(null)
    const answer = await chat(
      project,
      asked.map(({ role, content }) => ({ role, content })),
      (piece: ChatPiece) =>
        setArriving((current) =>
          current && {
            thinking: current.thinking + (piece.thinking ?? ""),
            text: current.text + (piece.text ?? ""),
          },
        ),
    )
    setSending(null)
    setArriving(null)
    if (!answer.ok) {
      setRefused(answer)
      return
    }
    const reply: Turn = { role: "assistant", content: answer.reply ?? "", model: answer.model }
    if (answer.thinking) reply.thinking = answer.thinking
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
                {turn.thinking ? <Thought text={turn.thinking} live={false} /> : null}
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
            {arriving ? (
              // The reply on its way, drawn where it will land. `aria-live`
              // so a screen reader hears the words as they come.
              <li className="chat-turn chat-arriving" data-role="assistant" aria-live="polite">
                <span className="chat-who">{answeredBy ?? "model"}</span>
                {arriving.thinking ? <Thought text={arriving.thinking} live={!arriving.text} /> : null}
                {arriving.text ? (
                  <div className="chat-said">{arriving.text}</div>
                ) : arriving.thinking ? null : (
                  <p className="chat-thinking" role="status">
                    thinking…
                  </p>
                )}
              </li>
            ) : null}
          </ol>
        ) : (
          <p className="chat-empty">
            Talk with this project's model. The conversation stays on this page: nothing is
            kept, and no run is started.
          </p>
        )}
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
