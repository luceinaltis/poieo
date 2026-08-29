/**
 * Everything that talks to the daemon.
 *
 * Reading is most of it. The calls that change anything come in exactly two
 * kinds, one fence each, and keeping them all here beside the reads is what
 * makes them easy to count: accept and discard are the only way anything the
 * page shows can change the reader's own files, and the control verbs --
 * pause, resume, run now -- touch the daemon's runtime state and nothing
 * else.
 */

import type { DiffReport, Listing, PoieoEvent, RunSummary } from "./types"

async function getJson<T>(path: string): Promise<T | null> {
  const response = await fetch(path)
  if (!response.ok) return null
  return (await response.json()) as T
}

export async function fetchTasks(): Promise<Listing> {
  // The whole envelope, not just the tasks out of it: the project rides on
  // the listing rather than on each row, because the listing a reader can
  // recognise least -- the one with no tasks in it -- needs naming most.
  const body = await getJson<Listing>("/api/tasks")
  return { projects: body?.projects ?? [], tasks: body?.tasks ?? [] }
}

/**
 * Which models a project runs on, and where that was decided.
 *
 * A key never crosses -- only the name of the variable it comes from, and
 * whether that is set. Nor does an endpoint's address: its own name tells one
 * from another, and a `base_url` is the one field in a binding that can carry
 * a private host.
 */
export interface ModelsReport {
  /** Null when the project names no models file at all. */
  binding: { name: string; path: string } | null
  providers: Record<
    string,
    {
      type: string
      /** The variable a key is read from; null when the endpoint names none. */
      api_key_env: string | null
      /** Null -- not false -- when it names none: its SDK resolves its own. */
      api_key_set: boolean | null
    }
  >
  /** `provider/model` for everything that does not name a role, or null. */
  default: string | null
  /**
   * The roles this project's models file names, and nothing else -- a role a
   * graph calls but the file has never named runs on the default and is not
   * this panel's business. Null for one the binding cannot resolve at all,
   * which is a broken file rather than a missing entry.
   */
  roles: Record<string, string | null>
}

export async function fetchModels(project: string): Promise<ModelsReport | null> {
  return getJson<ModelsReport>(
    `/api/projects/${encodeURIComponent(project)}/models`,
  )
}

export async function fetchRuns(
  opts: { task?: string; project?: string; limit?: number } = {},
): Promise<RunSummary[]> {
  const query = new URLSearchParams()
  if (opts.task) query.set("task", opts.task)
  // Both, or `?task=chores` answers with every project's chores at once.
  if (opts.project) query.set("project", opts.project)
  if (opts.limit !== undefined) query.set("limit", String(opts.limit))
  const suffix = query.toString() ? `?${query}` : ""

  const body = await getJson<{ runs: RunSummary[] }>(`/api/runs${suffix}`)
  return body?.runs ?? []
}

export async function fetchRunEvents(runId: string): Promise<PoieoEvent[]> {
  // 404 means the store has no such run, which a fresh daemon is entitled to.
  // An empty board with an invitation beats an error the user cannot act on.
  const body = await getJson<{ events: PoieoEvent[] }>(
    `/api/runs/${encodeURIComponent(runId)}`,
  )
  return body?.events ?? []
}

/**
 * A run's diff, regenerated on demand from two ids the store kept.
 *
 * `null` means it could not be read at all -- unknown run, or the daemon went
 * away. A body with `change: null` is different: the run really did alter
 * nothing, and saying so is the answer.
 */
export async function fetchDiff(runId: string): Promise<DiffReport | null> {
  try {
    return await getJson<DiffReport>(`/api/runs/${encodeURIComponent(runId)}/diff`)
  } catch {
    return null
  }
}

/**
 * Every write answers rather than throwing.
 *
 * A refusal is information the reader needs -- uncommitted edits in their own
 * project, or a run already in flight -- so it comes back as a value with
 * `ok: false` and travels the same path as a success. A daemon that has gone
 * away is the same kind of answer.
 */
export interface Answer {
  ok: boolean
  error?: string
}

async function post<T extends Answer>(path: string, body?: unknown): Promise<T> {
  try {
    // No body, no content-type: the control verbs take their whole argument
    // in the path, and a Content-Type on an empty request is a small lie.
    const init: RequestInit =
      body === undefined
        ? { method: "POST" }
        : {
            method: "POST",
            headers: { "content-type": "application/json" },
            body: JSON.stringify(body),
          }
    const response = await fetch(path, init)
    const payload = await response.json().catch(() => ({}))
    return { ok: response.ok, ...payload } as T
  } catch {
    return { ok: false, error: "the daemon did not answer" } as T
  }
}

// A project and a task name between them pick out one task; a name alone
// stopped being enough when one daemon could run several projects.
const taskUrl = (project: string, task: string, verb: string) =>
  `/api/tasks/${encodeURIComponent(project)}/${encodeURIComponent(task)}/${verb}`

/**
 * The review: the only two calls that can move the reader's own files. A
 * refused accept is an answer about the reader's own project, and the page
 * has to say which files stood in the way.
 */
export interface Decision extends Answer {
  accepted?: number
  discarded?: number
  dirty?: string[]
  conflict?: string[]
}

export function accept(
  project: string,
  task: string,
  throughRunId?: string,
): Promise<Decision> {
  return post(taskUrl(project, task, "accept"), { through_run_id: throughRunId })
}

export function discard(
  project: string,
  task: string,
  fromRunId?: string,
): Promise<Decision> {
  return post(taskUrl(project, task, "discard"), { from_run_id: fromRunId })
}

/**
 * Control: the other kind of write. Pause and resume answer the resulting
 * status; run answers "starting" or a refusal naming the run in flight.
 */
export interface ControlAnswer extends Answer {
  status?: string
  run_id?: string
}

export function pause(project: string, task: string): Promise<ControlAnswer> {
  return post(taskUrl(project, task, "pause"))
}

export function resume(project: string, task: string): Promise<ControlAnswer> {
  return post(taskUrl(project, task, "resume"))
}

export function runNow(project: string, task: string): Promise<ControlAnswer> {
  return post(taskUrl(project, task, "run"))
}

/**
 * Answering: neither review nor control. It touches none of the reader's own
 * files, so it is not the first; it outlives the daemon and can set a chain of
 * tasks going, so it is not the second either.
 *
 * A refusal carries the choices that *were* offered -- this page is holding a
 * list that may have moved on since it was drawn.
 */
export interface AnswerReply extends Answer {
  status?: string
  answer?: string
  choices?: string[]
}

export function answer(
  project: string,
  task: string,
  choice: string,
): Promise<AnswerReply> {
  return post(taskUrl(project, task, "answer"), { choice })
}

export type FeedStatus = "connecting" | "live" | "lost"

export interface FeedHandlers {
  onEvent(event: PoieoEvent): void
  onStatus(status: FeedStatus): void
  /**
   * Fired on every open, reconnects included. EventSource reconnects by
   * itself, but the events that happened while it was down are gone -- only
   * the caller knows how to go back and read them.
   */
  onResync(): void
}

export function openFeed(handlers: FeedHandlers): () => void {
  const source = new EventSource("/api/events")
  handlers.onStatus("connecting")

  source.onopen = () => {
    handlers.onStatus("live")
    handlers.onResync()
  }

  source.onerror = () => {
    // Not fatal: EventSource is already retrying. Say so and wait for onopen.
    handlers.onStatus("lost")
  }

  source.onmessage = (message: MessageEvent) => {
    let event: PoieoEvent
    try {
      event = JSON.parse(message.data) as PoieoEvent
    } catch {
      return // a torn frame must not take the page down
    }
    handlers.onEvent(event)
  }

  return () => {
    source.onopen = null
    source.onerror = null
    source.onmessage = null
    source.close()
  }
}
