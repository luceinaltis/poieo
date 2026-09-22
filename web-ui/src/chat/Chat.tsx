/**
 * A conversation with the project's model, beside the board.
 *
 * The models panel says which models this project can reach; this is where a
 * person hears one. A message goes to the model the project's `default` role
 * names -- what a plain card gets -- and the reply says which model that was,
 * so a switch made in the terminal shows up in the next answer.
 *
 * The reply is read as it is written: a `thinking…` line holds its place
 * until the first words come, and they arrive in the bubble as they are
 * written. What the model thinks is never shown here -- the reader wants
 * the answer, and a running task's thinking stays in its drawer.
 *
 * The thread is the page's. The shell holds it, so a visit to a task's drawer
 * does not lose it, and it goes with the page. The daemon keeps none of it,
 * offers the model no tools, and starts no run for it.
 *
 * While a task runs, the same panel can speak to it instead: a picker names
 * the running tasks, choosing one shows that run's timeline here, live, and
 * the box then sends direction the run hears at its next model turn. That
 * is the one road a person's words take into a run, and the timeline shows
 * where they were heard.
 */

import { useEffect, useRef, useState } from "react"
import type { KeyboardEvent } from "react"

import { chat, leaveDirection } from "../api"
import type { Answer, ChatPiece } from "../api"
import { Timeline, visibleTimelineEvents, withoutThinking } from "../detail/Timeline"
import { Refusal } from "../Refusal"
import type { PoieoEvent } from "../types"
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

/** A task the reader may speak to: it is running, and its timeline is live. */
export interface Steerable {
  name: string
  title: string
  activity: PoieoEvent[]
}

export function Chat({
  project,
  turns,
  onTurns,
  onClose,
  steerable = [],
}: {
  project: string
  turns: Turn[]
  onTurns(turns: Turn[]): void
  onClose(): void
  /** The project's running tasks, for the picker; empty hides it. */
  steerable?: Steerable[]
}) {
  const [text, setText] = useState("")
  // Whom the box speaks to: the project's model, or one running task by name.
  const [target, setTarget] = useState("model")
  const steering = target === "model" ? null : (steerable.find((task) => task.name === target) ?? null)
  // A run that ended takes its name out of the picker; the box goes back to
  // the model rather than speaking to nothing.
  useEffect(() => {
    if (target !== "model" && !steering) setTarget("model")
  }, [target, steering])
  // The message on its way, and to whom. Words to the model are shown in
  // the thread while it answers; words to a run appear on its timeline once
  // it has heard them, so they are never drawn as a bubble here -- not even
  // when that run ends before the words have landed. Either way the message
  // stays in the box until it was answered: a refusal must not eat it.
  const [sending, setSending] = useState<{ said: string; to: "model" | "run" } | null>(null)
  // The reply on its way: the words that have arrived so far.
  const [arriving, setArriving] = useState<string | null>(null)
  const [refused, setRefused] = useState<Answer | null>(null)
  const threadRef = useRef<HTMLDivElement>(null)
  const busy = sending !== null
  const full = turns.length >= TURNS_AT_MOST
  const shown: Turn[] = sending?.to === "model" ? [...turns, { role: "user", content: sending.said }] : turns
  const answeredBy = [...turns].reverse().find((turn) => turn.model)?.model ?? null
  // What of the run a reader here sees: said and done, never thought.
  const heard = steering ? visibleTimelineEvents(withoutThinking(steering.activity)) : []

  // A thread is read from its newest line: keep that one in view, as it grows.
  useEffect(() => {
    const thread = threadRef.current
    if (thread) thread.scrollTop = thread.scrollHeight
  }, [shown.length, arriving?.length, heard.length])

  const send = async () => {
    const said = text.trim()
    if (!said || busy) return
    if (steering) {
      // To the run, not the model: it answers on its own timeline, where the
      // words appear as `you said` once the run has heard them.
      setSending({ said, to: "run" })
      setRefused(null)
      const answer = await leaveDirection(project, steering.name, said)
      setSending(null)
      if (!answer.ok) {
        setRefused(answer)
        return
      }
      setText("")
      return
    }
    if (full) return
    const asked: Turn[] = [...turns, { role: "user", content: said }]
    setSending({ said, to: "model" })
    setArriving("")
    setRefused(null)
    const answer = await chat(
      project,
      asked.map(({ role, content }) => ({ role, content })),
      (piece: ChatPiece) => setArriving((current) => (current === null ? null : current + (piece.text ?? ""))),
    )
    setSending(null)
    setArriving(null)
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
        {/* Only while something runs: a picker with one option in it is
            furniture, the rule the project picker follows. */}
        {steerable.length ? (
          <select
            className="chat-target"
            aria-label="Talk to"
            value={target}
            disabled={busy}
            onChange={(event) => setTarget(event.target.value)}
          >
            <option value="model">this project's model</option>
            {steerable.map((task) => (
              <option key={task.name} value={task.name}>
                {task.title} · running
              </option>
            ))}
          </select>
        ) : null}
        <span className="chat-model" title={steering ? undefined : (answeredBy ?? undefined)}>
          {steering ? "its run, live" : answeredBy ? `answered by ${answeredBy}` : ""}
        </span>
        {turns.length && !steering ? (
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
        {steering ? (
          heard.length ? (
            <Timeline events={heard} following />
          ) : (
            <p className="chat-empty">Nothing yet from this run.</p>
          )
        ) : shown.length ? (
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
            {arriving !== null ? (
              // The reply on its way, drawn where it will land. `aria-live`
              // so a screen reader hears the words as they come.
              <li className="chat-turn chat-arriving" data-role="assistant" aria-live="polite">
                <span className="chat-who">{answeredBy ?? "model"}</span>
                {arriving ? (
                  <div className="chat-said">{arriving}</div>
                ) : (
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
      {full && !steering ? (
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
          placeholder={
            steering
              ? `Tell ${steering.title} something; it hears it at its next model turn.`
              : "Ask anything. Enter sends, Shift+Enter breaks the line."
          }
          value={text}
          disabled={full && !steering}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="chat-row">
          <button type="submit" data-do="chat-send" disabled={busy || (full && !steering) || !text.trim()}>
            {busy ? "sending…" : "send"}
          </button>
        </div>
      </form>
    </aside>
  )
}
