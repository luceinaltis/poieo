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
import type {
  MemoryAskReply,
  MemoryEntry,
  MemoryOverview,
  MemorySearchMode,
  MemorySearchReply,
} from "./memory/types"

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

const memoryUrl = (project: string, tail = "") =>
  `/api/projects/${encodeURIComponent(project)}/memory${tail}`

export async function fetchMemory(
  project: string,
  revision?: string,
): Promise<MemoryOverview | null | undefined> {
  try {
    const response = await fetch(memoryUrl(project), {
      cache: "no-store",
      ...(revision ? { headers: { "if-none-match": revision } } : {}),
    })
    if (response.status === 304) return undefined
    if (!response.ok) return null
    const overview = (await response.json()) as MemoryOverview
    const current = response.headers.get("etag")
    return current ? { ...overview, revision: current } : overview
  } catch {
    return null
  }
}

export async function fetchMemoryEntry(
  project: string,
  slug: string,
): Promise<MemoryEntry | null> {
  try {
    return await getJson<MemoryEntry>(memoryUrl(project, `/${encodeURIComponent(slug)}`))
  } catch {
    return null
  }
}

/**
 * One model an endpoint says it has.
 *
 * Everything but `id` and `ref` is **null when the endpoint did not say**, and
 * nothing is filled in from anywhere else. `price` in particular: poieo keeps
 * no price table, because one written down would be wrong the week after.
 * Where an endpoint publishes rates on its own listing they are reported;
 * where it does not, this is null rather than a guess -- and never a zero,
 * which would read as free.
 */
export interface ServedModel {
  id: string
  /** `provider/model` -- the one spelling, and what `config use` takes back. */
  ref: string
  context: number | null
  /** Ollama's own words for a local build: "9.0B", "Q4_K_M". */
  size: string | null
  quantization: string | null
  capabilities: string[]
  /** USD per million tokens. */
  price: { input: number; output: number } | null
  /** Which roles are on this model right now. Empty for most of them. */
  used_by: string[]
}

export interface Endpoint {
  /** The name the reader gave it in their own models file. */
  name: string
  type: string
  /**
   * What a person would recognise this as -- "OpenRouter", "LM Studio".
   * Null when the address is one nobody wrote down, and `type` is the
   * fallback: `openai_compatible` is vLLM and SGLang and LM Studio and
   * llama.cpp and every hosted router at once, which tells a reader nothing.
   */
  label: string | null
  /** False for `mock`, which answers from the binding file rather than a port. */
  askable: boolean
  /**
   * Whether this listing is what is **pulled and ready** or what the endpoint
   * offers. Ollama's is `ollama list`; a routed endpoint's is a catalogue of
   * what it would run for money, with nothing here yet. They look identical
   * and are not. A property of the backend: true of an Ollama wherever it runs.
   */
  installed: boolean
  /**
   * Whether that machine is *this* one. Only the address can answer it, and
   * reading `installed` as both had every Ollama anywhere -- an office server,
   * the desktop under the desk -- claiming to be on this laptop.
   *
   * Null when the endpoint has no address: Claude's SDK resolves its own, and
   * calling that "somewhere else" would be a claim about a machine nobody
   * named.
   */
  here: boolean | null
  /**
   * `host:port`, and no more of the address than that -- the scheme and path
   * say nothing about which box answered. Null when there is no address.
   *
   * This used not to cross at all. `poieo config` names an Ollama `ollama`
   * wherever it runs, so two of them were two endpoints a reader could not
   * tell apart; docs/web.md said the argument for letting an address through
   * would have to be concrete, and that is the concrete one.
   */
  host: string | null
  /** The variable a key is read from; null when the endpoint names none. */
  api_key_env: string | null
  /** Null -- not false -- when it names none: its SDK resolves its own. */
  api_key_set: boolean | null
  models: ServedModel[]
}

/**
 * Every model a project can reach, endpoint by endpoint, asked just now.
 *
 * A key never crosses -- only the name of the variable it comes from and
 * whether that is set, which is usually the whole explanation for an endpoint
 * that listed nothing. Nor does an endpoint's address: its own name tells one
 * from another, and a `base_url` is the one binding field that can carry a
 * private host.
 */
export interface ModelsReport {
  /** Where these endpoints were declared. Null if the project names no file. */
  binding: { name: string; path: string } | null
  /**
   * What a model may be pointed at: `default`, then the roles this file
   * already names. Not every role the graphs call -- offering one the file has
   * never named is how a panel creates a misspelled role.
   */
  roles: string[]
  endpoints: Endpoint[]
}

export async function fetchModels(project: string): Promise<ModelsReport | null> {
  return getJson<ModelsReport>(
    `/api/projects/${encodeURIComponent(project)}/models`,
  )
}

/**
 * An engine answering on this machine that this project cannot reach.
 *
 * Detection otherwise runs once, at `poieo init`. Install Ollama the week
 * after and the binding has never heard of it, so the panel shows nothing from
 * it and no reason why -- which reads as "there is nothing there". Almost
 * always none, and none draws nothing: a standing button whose usual answer is
 * "nothing new" is a button people learn to ignore.
 *
 * No address crosses here either. The panel names one back by `name`, and the
 * daemon looks up where it lives.
 */
export interface UndeclaredEngine {
  /** The key it would be declared under, and what `models/add` takes back. */
  name: string
  label: string
  type: string
  /** Ids only: this is a notice that something is here, not a catalogue. */
  models: string[]
}

/**
 * Asked **separately from the catalogue**, and that is the point: a candidate
 * port nothing is listening on costs a whole timeout rather than refusing, so
 * a catalogue that carried this would wait a second and a half to draw a list
 * it already had. This lands under it whenever it arrives.
 */
export async function fetchUndeclared(project: string): Promise<UndeclaredEngine[]> {
  const body = await getJson<{ undeclared: UndeclaredEngine[] }>(
    `/api/projects/${encodeURIComponent(project)}/models/undeclared`,
  )
  return body?.undeclared ?? []
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

// PUT rewrites the card, PATCH renames the file it lives in; they differ in
// the verb and nothing else, so they share the one sender.
async function withBody<T extends Answer>(
  method: "PUT" | "PATCH",
  path: string,
  body: unknown,
): Promise<T> {
  try {
    const response = await fetch(path, {
      method,
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    })
    const payload = await response.json().catch(() => ({}))
    return { ok: response.ok, ...payload } as T
  } catch {
    return { ok: false, error: "the daemon did not answer" } as T
  }
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

export function searchMemory(
  project: string,
  query: string,
  mode: MemorySearchMode,
  includeSetAside: boolean,
): Promise<MemorySearchReply> {
  return post<MemorySearchReply>(memoryUrl(project, "/search"), {
    query,
    mode,
    limit: 20,
    include_set_aside: includeSetAside,
  })
}

export function askMemory(
  project: string,
  question: string,
  includeSetAside: boolean,
): Promise<MemoryAskReply> {
  return post<MemoryAskReply>(memoryUrl(project, "/ask"), {
    question,
    include_set_aside: includeSetAside,
  })
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

/**
 * Pointing a role at another model: the fourth kind of write here.
 *
 * It edits the project's models file and nothing else, and never carries a
 * credential. A refusal brings what the reader needs to fix it -- the
 * endpoints that *are* declared, or the models one really has.
 */
export interface ModelsAnswer extends Answer {
  status?: string
  role?: string
  ref?: string
  /** False when the endpoint stayed silent: the name could not be checked. */
  checked?: boolean
  /** From `addEngine`: the key the endpoint was declared under. */
  engine?: string
  /**
   * Whether the **running daemon** took the edit, not just the file.
   *
   * `rebind` verifies the file reloads, but the daemon validates what start-up
   * validates and may keep the last good spec -- a role pointed at an endpoint
   * whose key is unset is the case that happens, and it refuses *every* write
   * to that file, not only the one that caused it. It went unsaid, and the
   * panel then redrew off that same kept spec: a reader told "using" watched
   * nothing change, and a reader told "added" watched the panel go on offering
   * what had just been written.
   *
   * Both writes answer it, so the warning below reads either.
   */
  adopted?: boolean
  /** Why it was not taken, in the daemon's words. Absent when it was. */
  why?: string
  providers?: string[]
  models?: string[]
  /** From `addEngine`: the engine keys detection knows how to look for. */
  engines?: string[]
}

// Not `useModel`: a plain function wearing React's hook prefix costs every
// reader a double-take. The route, the CLI and the button all still say `use`.
export function pickModel(
  project: string,
  target: string,
  role: string,
): Promise<ModelsAnswer> {
  return post(`/api/projects/${encodeURIComponent(project)}/models/use`, {
    target,
    role,
  })
}

/**
 * Declare an engine, so this project can reach its models.
 *
 * Either one detection found on this machine (`{engine}`), or an address
 * nobody guessed (`{url}`) -- a vLLM on 8001, an Ollama on a desktop, an
 * office box. Which backend an address is comes from asking it, so the reader
 * types where it is and nothing else; `name` and `key_env` are theirs to give
 * when the defaults do not fit.
 *
 * `key_env` is a variable's **name**. This never takes a key, here or
 * anywhere: the value belongs in the environment the daemon reads, and the
 * file this writes is one people commit.
 *
 * Only adds. Nothing about what a role uses moves -- declaring a model and
 * choosing one are different decisions, and `pickModel` is the second.
 */
export interface EngineToAdd {
  engine?: string
  url?: string
  name?: string
  key_env?: string
}

export function addEngine(project: string, what: EngineToAdd): Promise<ModelsAnswer> {
  return post(`/api/projects/${encodeURIComponent(project)}/models/add`, what)
}

/**
 * Making a task: the only call here that creates a file that did not exist.
 *
 * Three things and no fourth, which is what DESIGN.md says a task cannot do
 * without. The folder is not optional and has no default -- it is the one
 * thing the model's hands will touch.
 */
export interface MadeTask extends Answer {
  task?: string
  path?: string
}

export function createTask(
  project: string,
  name: string,
  folder: string,
  prompt: string,
  /** False makes the card switched off: written, on the board, not running. */
  enabled = true,
): Promise<MadeTask> {
  return post(`/api/projects/${encodeURIComponent(project)}/tasks`, {
    name,
    folder,
    prompt,
    enabled,
  })
}

/**
 * One task's card, as the file and as its three fields.
 *
 * The text is what the editor holds; the fields are what "make one like it"
 * prefills. Both come from the daemon because parsing YAML here would be a
 * second parser to keep honest against the one that runs the card.
 */
export interface Card {
  task: string
  text: string
  name: string
  folder: string | null
  prompt: string | null
  /**
   * Whether the card can be rebuilt from the three fields alone. Plain, the
   * board offers a form and the daemon spells the file; carrying more -- a
   * schedule, an isolation, a comment -- it stays a file on screen, because
   * a form must never drop what it cannot show.
   */
  plain: boolean
}

export async function fetchCard(project: string, task: string): Promise<Card | null> {
  try {
    const response = await fetch(
      `/api/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(task)}`,
    )
    if (!response.ok) return null
    return (await response.json()) as Card
  } catch {
    return null
  }
}

/**
 * Rewriting that card in place -- the same fence making one built.
 *
 * `live` is the daemon's own truth about the edit: whether the next run reads
 * it, or whether it waits for a restart because more than the prompt changed.
 */
export interface RewrittenCard extends Answer {
  task?: string
  live?: boolean
}

export function rewriteCard(
  project: string,
  task: string,
  card: string | { name: string; folder: string; prompt: string },
): Promise<RewrittenCard> {
  // Two spellings of one write: the raw file, or the three fields the daemon
  // serialises itself -- through the same dump make uses, so a person who
  // came in through the form never touches YAML.
  return withBody(
    "PUT",
    `/api/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(task)}`,
    typeof card === "string" ? { text: card } : card,
  )
}

/**
 * Renaming that task: the card's file moves, and nothing inside it is touched.
 *
 * The filename is the task's identity -- the `name:` line in the card is a
 * title `rewriteCard` owns -- so this is the one write that changes which task
 * the board is looking at. The name given here is a name, not a filename: the
 * daemon spells it, refusing one that reads like a path or one the folder
 * already uses, so `task` in the answer is the daemon's spelling and the only
 * one to go on afterwards.
 */
export interface RenamedCard extends Answer {
  /** The new slug, as the daemon spelled it. */
  task?: string
  /** Where the card now lives, so the sentence on screen can say it. */
  path?: string
}

export function renameCard(
  project: string,
  task: string,
  name: string,
): Promise<RenamedCard> {
  return withBody(
    "PATCH",
    `/api/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(task)}`,
    { name },
  )
}

/**
 * Setting the task aside: the card moves to `.set-aside/` in the tasks
 * folder, whole -- putting it back is putting the task back. The schedule
 * stops now; the board forgets the task on the daemon's next start.
 */
export interface SetAside extends Answer {
  task?: string
  /** Where the file went, so the sentence on screen can say it. */
  kept?: string
}

export async function setAside(project: string, task: string): Promise<SetAside> {
  try {
    const response = await fetch(
      `/api/projects/${encodeURIComponent(project)}/tasks/${encodeURIComponent(task)}`,
      { method: "DELETE" },
    )
    const payload = await response.json().catch(() => ({}))
    return { ok: response.ok, ...payload } as SetAside
  } catch {
    return { ok: false, error: "the daemon did not answer" }
  }
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
    // The one frame that is not a run event. It belongs to no run and carries
    // no detail -- it says a file the listing is built from has changed, so go
    // and read it again. Sent because nothing else is: the board reads
    // `/api/tasks` when it opens, and a card edited by hand under an open page
    // would otherwise reach nobody until they reconnected.
    if (event.type === "tasks_changed") {
      handlers.onResync()
      return
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
