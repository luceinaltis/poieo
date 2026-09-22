/**
 * A conversation with the project, beside the board.
 *
 * A conversation is a task: the project's chat card, made the first time the
 * chat is used. Each message starts one of its runs, and the runs that share a
 * thread are the conversation -- so the thread is read back from the task's own
 * run records, a past conversation is there to go back to, and what the model
 * does while it answers is that run's live timeline: what it says between
 * steps, and each tool it reaches for, folded. What it thinks is never shown.
 *
 * While the answer is being worked on, a message is heard at the run's next
 * model turn, the way direction reaches any run.
 *
 * While another task runs, the same panel can speak to it instead: a picker
 * names the running tasks, choosing one shows that run's timeline here, live,
 * and the box sends direction it hears at its next model turn.
 */

import { useEffect, useState } from "react"
import type { KeyboardEvent } from "react"

import { createChatCard, fetchRunEvents, leaveDirection, runNow } from "../api"
import type { Answer } from "../api"
import { Timeline, visibleTimelineEvents, withoutThinking } from "../detail/Timeline"
import { Refusal } from "../Refusal"
import type { TaskState } from "../state/stage"
import type { PoieoEvent, RunSummary } from "../types"
import "./chat.css"

/** A task the reader may speak to: it is running, and its timeline is live. */
export interface Steerable {
  name: string
  title: string
  activity: PoieoEvent[]
}

/** A conversation as the picker names it: by how it began. */
interface Conversation {
  thread: string
  title: string
}

/** The run in flight, and what it was started with. */
interface Live {
  runId: string
  thread: string | null
  message: string
  activity: PoieoEvent[]
}

/** A message on its way, drawn where it will land until its run shows up. */
interface Pending {
  thread: string
  message: string
  /** How many runs the thread had when it was sent: one more means it landed. */
  had: number
}

const TITLE_AT_MOST = 60

function newThread(): string {
  return `t-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`
}

/** The conversations, the most recently spoken-in first, each named by its first message. */
function conversationsOf(runs: RunSummary[], live: Live | null): Conversation[] {
  const titles = new Map<string, string>()
  const order: string[] = []
  const seen = (thread: string | null | undefined, message: string | undefined) => {
    if (!thread) return
    if (!titles.has(thread)) order.push(thread)
    // Newest first, so the last one seen is how the conversation began.
    if (message) titles.set(thread, message)
    else if (!titles.has(thread)) titles.set(thread, thread)
  }
  if (live) seen(live.thread, live.message)
  for (const run of runs) seen(run.thread, run.message)
  return order.map((thread) => {
    const title = titles.get(thread) ?? thread
    return { thread, title: title.length > TITLE_AT_MOST ? `${title.slice(0, TITLE_AT_MOST)}…` : title }
  })
}

function liveOf(task: TaskState | null): Live | null {
  if (!task || task.status !== "running" || !task.activityRunId) return null
  const started = task.activity.find((event) => event.type === "run_started")
  const input = (started?.data?.input ?? {}) as Record<string, unknown>
  return {
    runId: task.activityRunId,
    thread: typeof input.thread === "string" ? input.thread : null,
    message: typeof input.message === "string" ? input.message : "",
    activity: task.activity,
  }
}

/** What the model did on one past answer: its run's record, opened on request. */
function RunWork({ runId }: { runId: string }) {
  const [events, setEvents] = useState<PoieoEvent[] | null>(null)
  const shown = events ? visibleTimelineEvents(withoutThinking(events), { keepWords: true }) : []
  return (
    <details
      className="chat-work"
      onToggle={(event) => {
        if (event.currentTarget.open && events === null) {
          void fetchRunEvents(runId).then(setEvents)
        }
      }}
    >
      <summary>what it did</summary>
      {events === null ? null : shown.length ? (
        <Timeline events={shown} following={false} />
      ) : (
        <p className="chat-empty">It answered without reaching for anything.</p>
      )}
    </details>
  )
}

function Asked({ message }: { message: string }) {
  return (
    <li className="chat-turn" data-role="user">
      <span className="chat-who">you</span>
      <div className="chat-said">{message}</div>
    </li>
  )
}

function Answered({ run }: { run: RunSummary }) {
  return (
    <li className="chat-turn" data-role="assistant">
      <span className="chat-who">answer</span>
      {/* An empty bubble reads as broken; say what happened instead. */}
      <div className="chat-said">{run.said || <span className="chat-nothing">the model said nothing</span>}</div>
      {run.status === "failed" && run.error ? <span className="chat-cut">{run.error}</span> : null}
      <RunWork runId={run.run_id} />
    </li>
  )
}

export function Chat({
  project,
  chatTask,
  thread,
  onThread,
  onClose,
  steerable = [],
}: {
  project: string
  /** The project's chat task, live from the stage, or null before the chat has made one. */
  chatTask: TaskState | null
  /** The conversation open in the panel, or null for a new one. */
  thread: string | null
  onThread(thread: string | null): void
  onClose(): void
  /** The project's other running tasks, for the picker; empty hides it. */
  steerable?: Steerable[]
}) {
  const [text, setText] = useState("")
  // Whom the box speaks to: this conversation, or one running task by name.
  const [target, setTarget] = useState("chat")
  const steering = target === "chat" ? null : (steerable.find((task) => task.name === target) ?? null)
  // A run that ended takes its name out of the picker; the box goes back to
  // the conversation rather than speaking to nothing.
  useEffect(() => {
    if (target !== "chat" && !steering) setTarget("chat")
  }, [target, steering])

  const [busy, setBusy] = useState(false)
  const [refused, setRefused] = useState<Answer | null>(null)
  const [pending, setPending] = useState<Pending | null>(null)
  // A message said before the chat's card existed, waiting for the daemon to
  // pick the card up: it is sent the moment the task appears.
  const [awaitingCard, setAwaitingCard] = useState(false)

  const runs = chatTask?.runs ?? []
  const live = liveOf(chatTask)
  const past = thread ? runs.filter((run) => run.thread === thread && run.run_id !== live?.runId).reverse() : []
  const liveHere = live && thread !== null && live.thread === thread ? live : null

  // A pending message has landed once its run is live or on the record.
  useEffect(() => {
    if (!pending || awaitingCard) return
    const landed = runs.filter((run) => run.thread === pending.thread).length > pending.had
    if (landed || (live && live.thread === pending.thread)) setPending(null)
  }, [pending, awaitingCard, runs, live])

  const start = async (task: TaskState, said: string, into: string): Promise<boolean> => {
    const had = task.runs.filter((run) => run.thread === into).length
    setPending({ thread: into, message: said, had })
    const answer = await runNow(project, task.name, { message: said, thread: into })
    if (!answer.ok) {
      setPending(null)
      setRefused(answer)
      return false
    }
    return true
  }

  // The card has appeared: send what was said while it was being made.
  useEffect(() => {
    if (!awaitingCard || !chatTask || !pending) return
    setAwaitingCard(false)
    setBusy(true)
    void start(chatTask, pending.message, pending.thread).finally(() => setBusy(false))
    // `start` only reads what it is handed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [awaitingCard, chatTask, pending])

  const send = async () => {
    const said = text.trim()
    if (!said || busy || awaitingCard) return
    setRefused(null)
    setBusy(true)
    try {
      if (steering || liveHere) {
        // To a run already going -- another task's, or this conversation's
        // own answer in progress: heard at its next turn, where the words
        // appear as `you said`, not as a second run.
        const answer = await leaveDirection(project, steering ? steering.name : chatTask!.name, said)
        if (!answer.ok) setRefused(answer)
        else setText("")
        return
      }
      const into = thread ?? newThread()
      if (into !== thread) onThread(into)
      if (!chatTask) {
        const made = await createChatCard(project)
        if (!made.ok) {
          setRefused(made)
          return
        }
        setPending({ thread: into, message: said, had: 0 })
        setAwaitingCard(true)
        setText("")
        return
      }
      if (await start(chatTask, said, into)) setText("")
    } finally {
      setBusy(false)
    }
  }

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    // Enter sends and Shift+Enter breaks the line, as a chat box does -- but
    // not while an input method is still composing, where Enter commits the
    // characters and a send here would take half a word.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) return
    event.preventDefault()
    void send()
  }

  const conversations = conversationsOf(runs, live)
  const heard = steering ? visibleTimelineEvents(withoutThinking(steering.activity), { keepWords: true }) : []
  const working = liveHere ? visibleTimelineEvents(withoutThinking(liveHere.activity), { keepWords: true }) : []
  const shownPending = pending && pending.thread === thread && !liveHere ? pending : null

  return (
    <aside className="panel chat" aria-label="Chat">
      <header className="chat-head">
        <h2>chat</h2>
        {steering ? null : (
          <select
            className="chat-thread"
            aria-label="Conversation"
            value={thread ?? ""}
            disabled={busy}
            onChange={(event) => {
              setRefused(null)
              onThread(event.target.value || null)
            }}
          >
            <option value="">new conversation</option>
            {conversations.map((one) => (
              <option key={one.thread} value={one.thread}>
                {one.title}
              </option>
            ))}
          </select>
        )}
        {/* Only while something else runs: a picker with one option in it
            is furniture, the rule the project picker follows. */}
        {steerable.length ? (
          <select
            className="chat-target"
            aria-label="Talk to"
            value={target}
            disabled={busy}
            onChange={(event) => setTarget(event.target.value)}
          >
            <option value="chat">this conversation</option>
            {steerable.map((task) => (
              <option key={task.name} value={task.name}>
                {task.title} · running
              </option>
            ))}
          </select>
        ) : null}
        <button type="button" className="chat-close" aria-label="Close" onClick={onClose}>
          ✕
        </button>
      </header>
      <div className="chat-thread-view">
        {steering ? (
          heard.length ? (
            <Timeline events={heard} following />
          ) : (
            <p className="chat-empty">Nothing yet from this run.</p>
          )
        ) : past.length || liveHere || shownPending ? (
          <ol className="chat-turns">
            {past.map((run) => [
              <Asked key={`${run.run_id}-asked`} message={run.message ?? ""} />,
              <Answered key={`${run.run_id}-answered`} run={run} />,
            ])}
            {liveHere ? <Asked message={liveHere.message} /> : null}
            {liveHere ? (
              // The answer being worked on, drawn where it will land.
              // `aria-live` so a screen reader hears it as it comes.
              <li className="chat-turn chat-arriving" data-role="assistant" aria-live="polite">
                <span className="chat-who">answer</span>
                {working.length ? <Timeline events={working} following /> : null}
                <p className="chat-thinking" role="status">
                  working…
                </p>
              </li>
            ) : null}
            {shownPending ? <Asked message={shownPending.message} /> : null}
            {shownPending ? (
              <li className="chat-turn chat-arriving" data-role="assistant">
                <p className="chat-thinking" role="status">
                  starting…
                </p>
              </li>
            ) : null}
          </ol>
        ) : (
          <p className="chat-empty">
            Talk with this project. Each conversation is kept with the project, so you can come back to it.
          </p>
        )}
      </div>
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
              : liveHere
                ? "It hears this at its next step."
                : "Ask anything. Enter sends, Shift+Enter breaks the line."
          }
          value={text}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={onKeyDown}
        />
        <div className="chat-row">
          <button type="submit" data-do="chat-send" disabled={busy || awaitingCard || !text.trim()}>
            {busy ? "sending…" : "send"}
          </button>
        </div>
      </form>
    </aside>
  )
}
