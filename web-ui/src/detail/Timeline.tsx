/**
 * A run's timeline, in the words of somebody watching rather than the words
 * of the machinery running it: what the model said each turn, each tool it
 * reached for and why, what the person told it, and where it stopped.
 *
 * Its own module because two places read it: the task drawer, for the run a
 * reader picked, and the chat, for a running task the reader is speaking to.
 */

import { Gauge } from "../Gauge"
import { subjectOf } from "../state/stage"
import type { PoieoEvent } from "../types"
import { shortTime } from "../when"

const MAX_INLINE_OUTPUT_LENGTH = 240

function appearsInTimeline(event: PoieoEvent): boolean {
  if (event.type === "node_turn") {
    const data = event.data ?? {}
    return Boolean(String(data.text ?? "") || String(data.thinking ?? ""))
  }
  return [
    "node_tool_call",
    "node_tool_asking",
    // Kept so the question it answers can say what was answered; drawn as nothing.
    "node_tool_answered",
    "node_directed",
    "node_context_cleared",
    "node_input_dropped",
    "run_change_failed",
    "node_compact_failed",
    "node_started",
    "run_failed",
    "run_aborted",
  ].includes(event.type)
}

function turnKey(event: PoieoEvent): string | null {
  const turn = Number(event.data?.turn)
  return event.node_id && Number.isFinite(turn) ? `${event.node_id}\u0000${turn}` : null
}

/**
 * The same events with the model's thinking taken out, for a reader who
 * wants what it said and did: a turn that only thought then shows nothing,
 * and does not split the tool calls around it.
 */
export function withoutThinking(events: PoieoEvent[]): PoieoEvent[] {
  return events.map((event) =>
    event.type === "node_turn" && event.data?.thinking ? { ...event, data: { ...event.data, thinking: "" } } : event,
  )
}

/**
 * Fold a tool preamble only when every call it promised has its own record.
 *
 * `keepWords` keeps a preamble that said something: the chat reads what the
 * model says between its steps as the thread of what it is doing, where the
 * drawer lets each call's own purpose say it.
 */
export function visibleTimelineEvents(
  events: PoieoEvent[],
  { keepWords = false }: { keepWords?: boolean } = {},
): PoieoEvent[] {
  const toolsByTurn = new Map<string, number>()
  for (const event of events) {
    if (event.type !== "node_tool_call") continue
    const key = turnKey(event)
    if (key) toolsByTurn.set(key, (toolsByTurn.get(key) ?? 0) + 1)
  }
  return events.flatMap((event) => {
    if (event.type === "node_turn") {
      const expected = Number(event.data?.tool_call_count ?? 0)
      const key = turnKey(event)
      if (expected > 0) {
        const recorded = key ? (toolsByTurn.get(key) ?? 0) : 0
        if (recorded >= expected) return keepWords && String(event.data?.text ?? "") ? [event] : []
        return [
          {
            ...event,
            data: {
              ...event.data,
              missing_tool_call_count: expected - recorded,
            },
          },
        ]
      }
    }
    return appearsInTimeline(event) ? [event] : []
  })
}

type ToolArguments = Record<string, unknown>

type TimelineGroup =
  | { kind: "one"; event: PoieoEvent }
  | { kind: "tools"; events: PoieoEvent[] }

/**
 * Two or more tool calls in a row fold into one line. A step that reads six
 * files before it speaks is six lines of the same shape, and what a reader
 * wants from them at a glance is that six things were read and what for;
 * each call is still there, whole, one line down.
 */
export function groupTimeline(events: PoieoEvent[]): TimelineGroup[] {
  const groups: TimelineGroup[] = []
  for (const event of events) {
    const last = groups[groups.length - 1]
    if (event.type === "node_tool_call" && last?.kind === "tools") {
      last.events.push(event)
    } else if (event.type === "node_tool_call") {
      groups.push({ kind: "tools", events: [event] })
    } else {
      groups.push({ kind: "one", event })
    }
  }
  return groups.map((group) =>
    group.kind === "tools" && group.events.length === 1 ? { kind: "one", event: group.events[0] } : group,
  )
}

/**
 * A picture the model looked at, small, from the file kept with its run. The
 * call's purpose is its alt text: it says what the model was looking for.
 */
function Preview({ event }: { event: PoieoEvent }) {
  const name = event.data?.preview
  if (typeof name !== "string" || !name) return null
  return (
    <img
      className="drawer-preview"
      src={`/api/runs/${encodeURIComponent(event.run_id)}/files/${encodeURIComponent(name)}`}
      alt={toolPurpose(event.data ?? {})}
      loading="lazy"
    />
  )
}

/** The folded line, open for the newest group while the run is in flight. */
export function ToolGroup({ events, open }: { events: PoieoEvent[]; open: boolean }) {
  const purposes = events.map((event) => toolPurpose(event.data ?? {}))
  const failed = events.filter((event) => event.data?.error === true).length
  const said = purposes.slice(0, 2).join(" · ") + (purposes.length > 2 ? " · …" : "")
  return (
    <li className="drawer-entry" data-kind="tools">
      <span className="drawer-when">{shortTime(events[0].at ?? "")}</span>
      <details className="drawer-event drawer-group" open={open || undefined}>
        <summary>
          <span className="drawer-tool-purpose">{`${events.length} tool calls${failed ? `, ${failed} failed` : ""}`}</span>
          <span className="drawer-tool-meta">{said}</span>
          {events.map((event, index) => (
            <Preview key={index} event={event} />
          ))}
        </summary>
        <ol className="drawer-timeline drawer-timeline-folded">
          {events.map((event, index) => (
            <TimelineEntry key={`${event.type}-${index}`} event={event} />
          ))}
        </ol>
      </details>
    </li>
  )
}

function parsedArguments(raw: unknown): ToolArguments | null {
  let value = raw
  if (typeof raw === "string") {
    try {
      value = JSON.parse(raw)
    } catch {
      return null
    }
  }
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as ToolArguments)
    : null
}

function commandPurpose(command: string): string {
  if (/\b(?:python|python3|py)\b[^;]*(?:-c|<<)/i.test(command)) {
    return "Run a Python command for this task"
  }

  const checkout = command.match(/\bgit\s+checkout\b([^;&|]*)/i)
  if (checkout) {
    const tokens = (checkout[1].match(/"[^"]*"|'[^']*'|[^\s]+/g) ?? []).map((token) =>
      token.replace(/^(?:"|')|(?:"|')$/g, ""),
    )
    const changesFiles =
      /(?:^|\s)--(?:\s|$)|(?:^|\s)(?:--ours|--theirs|-p|--patch|-2|-3)(?:\s|$)/i.test(
        checkout[1],
      )
    if (changesFiles) {
      const last = tokens.at(-1) ?? ""
      return last && !last.startsWith("-")
        ? `Restore ${last} from Git`
        : "Restore files from Git"
    }

    const switchFlags = new Set(["-q", "--quiet", "--detach"])
    const flags = tokens.filter((token) => token.startsWith("-"))
    const operands = tokens.filter((token) => !token.startsWith("-"))
    if (flags.every((flag) => switchFlags.has(flag)) && operands.length === 1) {
      return `Switch to ${operands[0]}`
    }
    return "Run a Git checkout command for this task"
  }

  const sedEdit = /\bsed\b[^;|]*(?:\s-i[^\s]*|\s--in-place(?:=\S*)?)(?:\s|$)/i.test(command)
  if (sedEdit) {
    const segment = command.match(/\bsed\b([^;|]*)/i)?.[1] ?? ""
    const files = segment.match(/(?:[\w.-]+[\\/])*[\w.-]+\.[A-Za-z0-9]+/g)
    return files?.length ? `Update ${files[files.length - 1]} with sed` : "Update files with sed"
  }

  const prDiff = command.match(/(?:^|\s)gh\s+pr\s+diff\s+(\d+)/i)
  if (prDiff) return `Review the changes in PR #${prDiff[1]}`
  const prChecks = command.match(/(?:^|\s)gh\s+pr\s+checks\s+(\d+)/i)
  if (prChecks) return `Check whether PR #${prChecks[1]} passed its checks`
  const prView = command.match(/(?:^|\s)gh\s+pr\s+view\s+(\d+)/i)
  if (prView) return `Check the status of PR #${prView[1]}`
  if (/\b(?:pytest|vitest|npm\s+test|ruff|tsc\s+-b)(?:\s|$)/i.test(command)) {
    return "Run the relevant verification checks"
  }
  if (/\bgit\s+merge-base\s+--is-ancestor\b/i.test(command)) {
    return "Check whether the candidate includes its base"
  }

  const search = command.match(/\b(?:rg|grep)\b[^;|]*?(?:"([^"]+)"|'([^']+)')/i)
  if (search) {
    const pattern = (search[1] || search[2]).replaceAll("\\\"", '"')
    return `Search the project for “${pattern.slice(0, 80)}${pattern.length > 80 ? "…" : ""}”`
  }

  const cat = command.match(/\b(?:cat|type|Get-Content)\s+(?:-[^\s]+\s+)*(?:"([^"]+)"|'([^']+)'|([^\s;|]+))/i)
  if (cat) return `Read ${cat[1] || cat[2] || cat[3]}`

  const sedSegment = command.match(/\bsed\b([^;|]*)/i)?.[1] ?? ""
  const sedFiles = sedSegment.match(/(?:[\w.-]+[\\/])*[\w.-]+\.[A-Za-z0-9]+/g)
  if (sedFiles?.length) return `Read ${sedFiles[sedFiles.length - 1]}`

  const listing = command.match(/\b(?:ls|dir|Get-ChildItem)\s+(?:-[^\s]+\s+)*([^\s;|]+)/i)
  if (listing) return `Look through ${listing[1]}`

  const switchCommand = command.match(/\bgit\s+switch\b([^;&|]*)/i)
  if (switchCommand) {
    const tokens = switchCommand[1].trim().split(/\s+/).filter(Boolean)
    const flags = tokens.filter((token) => token.startsWith("-"))
    const operands = tokens.filter((token) => !token.startsWith("-"))
    if (flags.every((flag) => ["-q", "--quiet", "--detach"].includes(flag)) && operands.length === 1) {
      return `Switch to ${operands[0]}`
    }
    return "Run a Git switch command for this task"
  }

  const show = command.match(/\bgit\s+show\b(?:\s+--?[\w=-]+)*\s+([^\s;|]+)/i)
  if (show) return `Inspect ${show[1]}`

  if (/Independent review/i.test(command)) return "Prepare the independent review"
  if (/(?:^|\s)git\s+status(?:\s|$)/i.test(command)) return "Check the working tree"
  if (/(?:^|\s)git\s+diff(?:\s|$)/i.test(command)) return "Review the current changes"
  if (/(?:^|\s)git\s+log(?:\s|$)/i.test(command)) return "Review recent commits"
  if (/(?:^|\s)git\s+fetch(?:\s|$)/i.test(command)) return "Refresh remote branch information"
  return "Run a command for this task"
}

/**
 * Older events predate agent-written purposes. Say only what their recorded
 * arguments prove; a guessed reason would be more polished and less true.
 */
function fallbackPurpose(name: string, raw: unknown): string {
  const args = parsedArguments(raw)
  const subject = subjectOf(raw)
  if (name === "run_command") {
    const command = args?.command
    return commandPurpose(typeof command === "string" ? command : subject)
  }
  if (name === "read_file") return subject ? `Read ${subject}` : "Read a file"
  if (["write_file", "edit_file", "append_file"].includes(name)) {
    return subject ? `Update ${subject}` : "Update a file"
  }
  if (name === "search_files") {
    return subject ? `Search the project for ${subject}` : "Search the project"
  }
  if (name === "glob_files") {
    return subject ? `Find files matching ${subject}` : "Find relevant files"
  }
  if (name === "list_dir") {
    return subject ? `Look through ${subject}` : "Look through the working folder"
  }
  if (name === "tell") return subject ? `Send an update to ${subject}` : "Send a task update"
  const words = name.replaceAll("_", " ").trim()
  return words ? words[0].toUpperCase() + words.slice(1) : "Continue the task"
}

export function toolPurpose(data: Record<string, any>): string {
  const written = typeof data.purpose === "string" ? data.purpose.trim() : ""
  return written || fallbackPurpose(String(data.name ?? ""), data.arguments)
}

function missingToolActivity(count: number): string {
  return `${count} tool call${count === 1 ? "" : "s"} ${count === 1 ? "was" : "were"} not fully recorded`
}

function displayArguments(raw: unknown, command: string): string {
  const parsed = parsedArguments(raw)
  if (!parsed) return command ? "" : String(raw ?? "")
  const rest = Object.fromEntries(Object.entries(parsed).filter(([key]) => key !== "command"))
  return Object.keys(rest).length ? JSON.stringify(rest, null, 2) : ""
}

function RunOutput({ text }: { text: string }) {
  if (text.length <= MAX_INLINE_OUTPUT_LENGTH) {
    return <p className="drawer-text">{text}</p>
  }
  const opening = text.trim().split(/\r?\n/).find((line) => line.trim()) ?? text
  return (
    <details className="drawer-said">
      <summary>{opening.slice(0, 120)}…</summary>
      <p className="drawer-text">{text}</p>
    </details>
  )
}

/**
 * A run's timeline, in the words of somebody watching rather than the words
 * of the machinery running it.
 *
 * Six lines used to carry four machine words -- the node's id, the node's
 * type, the turn counter and a millisecond count -- which is the vocabulary
 * DESIGN.md's principle 7 spends its whole budget avoiding everywhere else.
 * The step's name stays, because the author chose it and it is on the board
 * too; what goes is everything that describes the loop rather than the work.
 */
/** A person's answer to a call a step asked about, by call id: true, false, or absent while it waits. */
type Answers = Record<string, boolean>

/** A person's say-so on one call, or null where nobody here can give it. */
type OnAnswer = ((call: string, allow: boolean) => void) | null

export function TimelineEntry({
  event,
  answers = {},
  onAnswer = null,
}: {
  event: PoieoEvent
  answers?: Answers
  onAnswer?: OnAnswer
}) {
  const data = event.data ?? {}

  if (event.type === "node_tool_answered") return null

  if (event.type === "node_tool_asking") {
    // The step's question, with the answer folded in once it comes: a line
    // of its own for the answer would say twice what one line can.
    const call = String(data.call_id ?? "")
    const answer = answers[call]
    const kind = data.kind === "commands" ? "run a command" : "edit a file"
    return (
      <li className="drawer-entry" data-kind="asking" data-answer={answer === undefined ? "waiting" : String(answer)}>
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-event drawer-asking">
          <span className="drawer-tool-purpose">{`wants to ${kind}: ${toolPurpose(data)}`}</span>
          <span className="drawer-tool-meta">{String(data.name ?? "")}</span>
          {answer !== undefined ? (
            <p className="drawer-text">{answer ? "allowed" : "not allowed"}</p>
          ) : onAnswer ? (
            <div className="drawer-answer">
              <button type="button" data-do="allow" onClick={() => onAnswer(call, true)}>
                allow
              </button>
              <button type="button" data-do="deny" onClick={() => onAnswer(call, false)}>
                deny
              </button>
            </div>
          ) : (
            <p className="drawer-text">waiting for a person to allow it</p>
          )}
        </div>
      </li>
    )
  }

  if (event.type === "node_turn") {
    const text = String(data.text ?? "")
    const thinking = String(data.thinking ?? "")
    const missingCalls = Number(data.missing_tool_call_count ?? 0)
    // A complete set of tool records folds an empty preamble before this
    // point. If it survived, the gap is itself evidence worth keeping.
    if (!text && !thinking) {
      const missing = missingCalls || Number(data.tool_call_count ?? 0)
      if (missing <= 0) return null
      return (
        <li className="drawer-entry" data-kind="stuck">
          <span className="drawer-when">{shortTime(event.at ?? "")}</span>
          <div className="drawer-event drawer-label">
            {missingToolActivity(missing)}
          </div>
        </li>
      )
    }
    const sent = Number(data.input_tokens ?? 0)
    const wrote = Number(data.output_tokens ?? 0)
    // The window this turn was measured against, when the binding or the
    // endpoint said; an older event or a silent endpoint leaves the count alone.
    const window = typeof data.window === "number" && data.window > 0 ? Number(data.window) : null
    // The turn number is the loop's bookkeeping. What a reader wants from a
    // second turn is that the model spoke again, which the entry already is.
    return (
      <li className="drawer-entry" data-kind="turn">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-event">
          {text ? <RunOutput text={text} /> : null}
          {thinking ? (
            <details className="drawer-thinking">
              <summary>thinking</summary>
              <p>{thinking}</p>
            </details>
          ) : null}
          {/* What this turn cost. The run's total says what the whole step
              spent; a reader chasing a step that slowed down wants to know
              which turn it happened on. */}
          {sent > 0 ? (
            <p className="drawer-cost">
              {window !== null ? (
                <Gauge label="context" used={sent} limit={window} unit="tokens" />
              ) : (
                `${sent.toLocaleString("en-US")} in`
              )}
              {wrote > 0 ? ` · ${wrote.toLocaleString("en-US")} out` : ""}
            </p>
          ) : null}
          {missingCalls > 0 ? (
            <p className="drawer-missing">{missingToolActivity(missingCalls)}</p>
          ) : null}
        </div>
      </li>
    )
  }

  if (event.type === "node_tool_call") {
    // The daemon writes a boolean here, and the message a reader wants is in
    // `result` either way -- a failing tool explains itself there.
    const failed = data.error === true
    // Milliseconds only when they are worth a reader's attention. A tool that
    // answered instantly said "0ms" on every line and meant nothing by it.
    const ms = Number(data.duration_ms ?? 0)
    const slow = ms >= 1000 ? ` · ${(ms / 1000).toFixed(1)}s` : ""
    const name = String(data.name ?? "")
    const purpose = toolPurpose(data)
    const args = parsedArguments(data.arguments)
    const command = typeof args?.command === "string" ? args.command : ""
    const otherArguments = displayArguments(data.arguments, command)
    const result = String(data.result ?? "")
    return (
      <li className="drawer-entry" data-kind="tool" data-error={String(failed)}>
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <details className="drawer-event drawer-tool">
          <summary>
            <span className="drawer-tool-purpose">{purpose}</span>
            <span className="drawer-tool-meta">
              {`${name || "tool"} · ${failed ? "failed" : "completed"}${slow}`}
            </span>
            <Preview event={event} />
          </summary>
          <div className="drawer-tool-raw">
            <div className="drawer-tool-part">
              <span>Tool</span>
              <pre>{name || "unknown"}</pre>
            </div>
            {command ? (
              <div className="drawer-tool-part">
                <span>Command</span>
                <pre>{command}</pre>
              </div>
            ) : null}
            {otherArguments ? (
              <div className="drawer-tool-part">
                <span>{command ? "Options" : "Input"}</span>
                <pre>{otherArguments}</pre>
              </div>
            ) : null}
            {result ? (
              <div className="drawer-tool-part">
                <span>{command ? "Output" : "Result"}</span>
                <pre>{result}</pre>
              </div>
            ) : (
              <p className="drawer-tool-empty">No result was recorded.</p>
            )}
          </div>
        </details>
      </li>
    )
  }

  if (event.type === "node_context_cleared") {
    // A step whose history quietly shrinks is a step nobody can reason about
    // afterwards -- least of all when the question is why it stopped. The
    // results are gone from the conversation, not from the disk, and the line
    // says which by naming what was kept.
    const freed = Number(data.freed ?? 0)
    const kept = Number(data.kept ?? 0)
    return (
      <li className="drawer-entry" data-kind="cleared">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-event drawer-label">
          {`cleared ${freed.toLocaleString("en-US")} characters of older results, `}
          {`keeping the last ${kept}`}
        </div>
      </li>
    )
  }

  if (event.type === "node_input_dropped") {
    // What the endpoint kept against what it was sent. Both numbers, because
    // the gap is the news -- and because a run that ends badly later is
    // explained by this line more often than by anything after it.
    const before = Number(data.before ?? 0)
    const kept = Number(data.kept ?? 0)
    return (
      <li className="drawer-entry" data-kind="stuck">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-event">
          <div className="drawer-label">
            {`the endpoint kept ${kept.toLocaleString("en-US")} of `}
            {`${before.toLocaleString("en-US")} tokens it was sent`}
          </div>
          {data.note ? <p className="drawer-text">{String(data.note)}</p> : null}
        </div>
      </li>
    )
  }

  if (event.type === "run_change_failed" || event.type === "node_compact_failed") {
    // Housekeeping that could not do its job. Neither stops the work, which
    // is exactly why both have to be seen: a run whose change was never
    // recorded reads as a run that had nothing to do, and every `then:`
    // written against `run.change` quietly stops firing while the board goes
    // on showing green.
    const what =
      event.type === "run_change_failed"
        ? "the change could not be recorded"
        : "the older turns could not be folded"
    return (
      <li className="drawer-entry" data-kind="stuck">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-event">
          <div className="drawer-label">{what}</div>
          <p className="drawer-text">{String(data.error ?? "")}</p>
        </div>
      </li>
    )
  }

  if (event.type === "node_started") {
    // The step's name, and nothing about what kind of node it is: `agent` and
    // `router` are how the graph is built, not what is happening.
    return (
      <li className="drawer-entry" data-kind="node">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-event drawer-label">{event.node_id}</div>
      </li>
    )
  }

  if (event.type === "node_directed") {
    // The person's words, where the model heard them: after the calls that
    // were running when they were said, before the turn that read them.
    return (
      <li className="drawer-entry" data-kind="directed">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <div className="drawer-event drawer-directed">
          <span className="drawer-tool-purpose">you said</span>
          <p className="drawer-text">{String(data.text ?? "")}</p>
        </div>
      </li>
    )
  }

  if (event.type === "run_failed" || event.type === "run_aborted") {
    return (
      <li className="drawer-entry" data-kind="tool" data-error="true">
        <span className="drawer-when">{shortTime(event.at ?? "")}</span>
        <p className="drawer-event drawer-text">{String(data.error ?? data.reason ?? "stopped")}</p>
      </li>
    )
  }

  return null
}

/**
 * The grouped list. `following` says the run is in flight: the newest group
 * of tool calls then stays open, because it is what the run is doing now.
 */
export function Timeline({
  events,
  following,
  onAnswer = null,
}: {
  events: PoieoEvent[]
  following: boolean
  /** Answers a call a step is waiting on; absent where nobody here can. */
  onAnswer?: OnAnswer
}) {
  const answers: Answers = {}
  for (const event of events) {
    if (event.type === "node_tool_answered") answers[String(event.data?.call_id ?? "")] = event.data?.allowed === true
  }
  const groups = groupTimeline(events)
  const newest = groups.findLastIndex((group) => group.kind === "tools")
  return (
    <ol className="drawer-timeline">
      {groups.map((group, index) =>
        group.kind === "tools" ? (
          <ToolGroup key={`tools-${index}`} events={group.events} open={following && index === newest} />
        ) : (
          <TimelineEntry key={`${group.event.type}-${index}`} event={group.event} answers={answers} onAnswer={onAnswer} />
        ),
      )}
    </ol>
  )
}
