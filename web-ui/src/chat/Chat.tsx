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

import { useEffect, useRef, useState } from "react"
import type { ChangeEvent, KeyboardEvent } from "react"

import { approve, createChatCard, fetchRunEvents, leaveDirection, runNow, setPermission } from "../api"
import type { Answer, Attaching, ChatPermission } from "../api"
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
  attachments: string[]
  activity: PoieoEvent[]
}

/**
 * A first message, said before the project's chat card existed: held by the
 * shell, which outlives this panel, and sent once the daemon has the card.
 */
export interface Queued {
  project: string
  thread: string
  message: string
  attachments?: Attaching[]
}

/** A message on its way, drawn where it will land until its run shows up. */
interface Pending {
  thread: string
  message: string
  attachments?: Attaching[]
  /** How many runs the thread had when it was sent: one more means it landed. */
  had: number
  /** Why the task was held when it was sent: a run-now goes through a hold, so only a new reason refuses. */
  held: string
}

const TITLE_AT_MOST = 60

// What the chat may do, in the picker's words: the card's own four settings.
const PERMISSIONS: [ChatPermission, string][] = [
  ["read", "read only"],
  ["ask", "ask each time"],
  ["edits", "accept edits"],
  ["all", "allow all"],
]

// What a message may carry: the daemon's own limits, said here first so a
// file it would refuse is refused before anything is sent.
const ATTACH_AT_MOST = 4
const IMAGE_CAP = 3_750_000
const TEXT_CAP = 200_000
const PICTURES = new Set(["image/png", "image/jpeg", "image/gif", "image/webp"])
const TEXTS: Record<string, string> = {
  txt: "text/plain",
  log: "text/plain",
  md: "text/markdown",
  markdown: "text/markdown",
  csv: "text/csv",
  json: "application/json",
}

/** What a chosen file is, as the daemon names it, or null for what it will not take. */
function mediaTypeOf(file: File): string | null {
  if (PICTURES.has(file.type)) return file.type
  if (Object.values(TEXTS).includes(file.type)) return file.type
  const extension = file.name.split(".").pop()?.toLowerCase() ?? ""
  return TEXTS[extension] ?? null
}

function base64Of(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader()
    reader.onload = () => resolve(String(reader.result).split(",")[1] ?? "")
    reader.onerror = () => reject(reader.error)
    reader.readAsDataURL(file)
  })
}

const isPicture = (name: string) => /\.(png|jpe?g|gif|webp)$/i.test(name)

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
    attachments: Array.isArray(input.attachments) ? input.attachments.map(String) : [],
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

/**
 * What was attached to a message: a picture drawn small from the file kept
 * with its run, a text file by name. Before the run exists, names only.
 */
function Attached({ names, runId }: { names: string[]; runId?: string }) {
  if (!names.length) return null
  return (
    <ul className="chat-files">
      {names.map((name) => (
        <li key={name}>
          {runId && isPicture(name) ? (
            <img
              className="chat-picture"
              src={`/api/runs/${encodeURIComponent(runId)}/files/${encodeURIComponent(name)}`}
              alt={name}
              loading="lazy"
            />
          ) : (
            <span className="chat-file">{name}</span>
          )}
        </li>
      ))}
    </ul>
  )
}

function Asked({ message, attachments = [], runId }: { message: string; attachments?: string[]; runId?: string }) {
  return (
    <li className="chat-turn" data-role="user">
      <span className="chat-who">you</span>
      <div className="chat-said">{message}</div>
      <Attached names={attachments} runId={runId} />
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
  queued = null,
  onQueue = () => {},
  refusedLater = null,
  onRefusalSeen = () => {},
  onClose,
  steerable = [],
}: {
  project: string
  /** The project's chat task, live from the stage, or null before the chat has made one. */
  chatTask: TaskState | null
  /** The conversation open in the panel, or null for a new one. */
  thread: string | null
  onThread(thread: string | null): void
  /** The first message waiting for the chat's card, held by the shell. */
  queued?: Queued | null
  onQueue?(queued: Queued | null): void
  /** What the daemon said when the shell sent that message and it was refused. */
  refusedLater?: Answer | null
  onRefusalSeen?(): void
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
  // The setting just chosen, shown until the card on disk says the same.
  const [choosing, setChoosing] = useState<string | null>(null)
  const held = chatTask?.permission ?? null
  useEffect(() => {
    if (choosing !== null && choosing === held) setChoosing(null)
  }, [choosing, held])
  const shownPermission = choosing ?? held
  // What the next message will carry, read and checked as it is chosen.
  const [attached, setAttached] = useState<Attaching[]>([])
  const fileRef = useRef<HTMLInputElement>(null)

  const runs = chatTask?.runs ?? []
  const live = liveOf(chatTask)
  const past = thread ? runs.filter((run) => run.thread === thread && run.run_id !== live?.runId).reverse() : []
  const liveHere = live && thread !== null && live.thread === thread ? live : null

  // A pending message has landed once its run is live or on the record --
  // or will not, because the task was held back from starting it, which the
  // daemon says only on the task: a run-now it accepted is not a run begun.
  const heldBecause = chatTask?.heldBecause ?? ""
  useEffect(() => {
    if (!pending) return
    const landed = runs.filter((run) => run.thread === pending.thread).length > pending.had
    if (landed || (live && live.thread === pending.thread)) setPending(null)
    else if (heldBecause && heldBecause !== pending.held) {
      setPending(null)
      setRefused({ ok: false, error: heldBecause })
    }
  }, [pending, runs, live, heldBecause])

  const start = async (task: TaskState, said: string, into: string, files: Attaching[]): Promise<boolean> => {
    const had = task.runs.filter((run) => run.thread === into).length
    setPending({ thread: into, message: said, attachments: files, had, held: task.heldBecause })
    const answer = await runNow(project, task.name, {
      message: said,
      thread: into,
      ...(files.length ? { attachments: files } : {}),
    })
    if (!answer.ok) {
      setPending(null)
      setRefused(answer)
      return false
    }
    return true
  }

  const send = async () => {
    const said = text.trim()
    if (!said || busy || queued) return
    setRefused(null)
    onRefusalSeen()
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
        // Sent by the shell once the daemon has picked the card up, so a
        // panel closed in the meantime does not take the message with it.
        onQueue({ project, thread: into, message: said, ...(attached.length ? { attachments: attached } : {}) })
        setText("")
        setAttached([])
        return
      }
      if (await start(chatTask, said, into, attached)) {
        setText("")
        setAttached([])
      }
    } finally {
      setBusy(false)
    }
  }

  const choose = async (event: ChangeEvent<HTMLInputElement>) => {
    const chosen = [...(event.target.files ?? [])]
    event.target.value = ""
    setRefused(null)
    const taken: Attaching[] = []
    const refuse = (error: string) => setRefused({ ok: false, error })
    for (const file of chosen) {
      const media_type = mediaTypeOf(file)
      if (media_type === null) {
        refuse(`${file.name}: a message takes pictures and text files`)
        break
      }
      if (attached.length + taken.length >= ATTACH_AT_MOST) {
        refuse(`a message takes at most ${ATTACH_AT_MOST} attachments`)
        break
      }
      if ([...attached, ...taken].some((one) => one.name === file.name)) {
        refuse(`${file.name} is attached already`)
        break
      }
      // Before reading: a file the daemon would refuse is not read into
      // memory, encoded and sent only to be turned away. Bytes for a text
      // file bound its characters from above, so the daemon has the last word.
      const cap = PICTURES.has(media_type) ? IMAGE_CAP : TEXT_CAP * 4
      if (file.size > cap) {
        refuse(`${file.name} is too large to send (${file.size} bytes)`)
        break
      }
      try {
        taken.push({ name: file.name, media_type, data: await base64Of(file) })
      } catch {
        refuse(`${file.name} could not be read`)
        break
      }
    }
    if (taken.length) setAttached((current) => [...current, ...taken])
  }

  const choosePermission = async (mode: ChatPermission) => {
    if (!chatTask) return
    setRefused(null)
    setChoosing(mode)
    const answer = await setPermission(project, chatTask.name, mode)
    if (!answer.ok) {
      setChoosing(null)
      setRefused(answer)
    }
  }

  // A person's say-so on a call the answer is waiting on.
  const answerCall = async (call: string, allow: boolean) => {
    if (!chatTask) return
    const answer = await approve(project, chatTask.name, call, allow)
    if (!answer.ok) setRefused(answer)
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
  const waiting = pending ?? (queued && queued.project === project ? queued : null)
  const shownPending = waiting && waiting.thread === thread && !liveHere ? waiting : null

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
        {chatTask && !steering ? (
          <select
            className="chat-permission"
            aria-label="Permission"
            value={shownPermission ?? "read"}
            onChange={(event) => void choosePermission(event.target.value as ChatPermission)}
          >
            {PERMISSIONS.map(([mode, label]) => (
              <option key={mode} value={mode}>
                {label}
              </option>
            ))}
            {shownPermission === "custom" ? <option value="custom">as its card says</option> : null}
          </select>
        ) : null}
        <button type="button" className="chat-close" aria-label="Close" onClick={onClose}>
          ✕
        </button>
      </header>
      {shownPermission === "all" && !steering ? (
        // Said where it is chosen: nothing on this machine fences a command in.
        <p className="chat-caution" role="note">
          Edits and commands run without asking. Commands run on this machine as you.
        </p>
      ) : null}
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
              <Asked
                key={`${run.run_id}-asked`}
                message={run.message ?? ""}
                attachments={run.attachments}
                runId={run.run_id}
              />,
              <Answered key={`${run.run_id}-answered`} run={run} />,
            ])}
            {liveHere ? (
              <Asked message={liveHere.message} attachments={liveHere.attachments} runId={liveHere.runId} />
            ) : null}
            {liveHere ? (
              // The answer being worked on, drawn where it will land.
              // `aria-live` so a screen reader hears it as it comes.
              <li className="chat-turn chat-arriving" data-role="assistant" aria-live="polite">
                <span className="chat-who">answer</span>
                {working.length ? (
                  <Timeline events={working} following onAnswer={(call, allow) => void answerCall(call, allow)} />
                ) : null}
                <p className="chat-thinking" role="status">
                  working…
                </p>
              </li>
            ) : null}
            {shownPending ? (
              <Asked
                message={shownPending.message}
                attachments={(shownPending.attachments ?? []).map((one) => one.name)}
              />
            ) : null}
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
      {refused || refusedLater ? <Refusal answer={(refused ?? refusedLater)!} /> : null}
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
        {attached.length ? (
          <ul className="chat-attached" aria-label="Attached">
            {attached.map((one) => (
              <li key={one.name}>
                {one.name}
                <button
                  type="button"
                  aria-label={`Remove ${one.name}`}
                  onClick={() => setAttached((current) => current.filter((other) => other.name !== one.name))}
                >
                  ✕
                </button>
              </li>
            ))}
          </ul>
        ) : null}
        <div className="chat-row">
          {/* Pictures and text files ride with a new message; words for a
              run already going are direction, which carries none. */}
          <input
            ref={fileRef}
            type="file"
            multiple
            hidden
            accept="image/png,image/jpeg,image/gif,image/webp,.txt,.log,.md,.markdown,.csv,.json"
            onChange={(event) => void choose(event)}
          />
          <button
            type="button"
            className="chat-attach"
            data-do="chat-attach"
            disabled={busy || queued !== null || steering !== null || liveHere !== null}
            onClick={() => fileRef.current?.click()}
          >
            attach
          </button>
          <button type="submit" data-do="chat-send" disabled={busy || queued !== null || !text.trim()}>
            {busy ? "sending…" : "send"}
          </button>
        </div>
      </form>
    </aside>
  )
}
