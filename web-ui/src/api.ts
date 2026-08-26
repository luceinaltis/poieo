/**
 * Everything that talks to the daemon.
 *
 * Reading is the whole of it but for two calls: accept and discard, at the
 * bottom, are the only POSTs the page can make and the only way anything it
 * shows can change the reader's own files. Keeping them here, beside the
 * reads, is what makes that easy to count.
 */

import type { DiffReport, FlowRow, PoieoEvent, RunSummary } from "./types"

async function getJson<T>(path: string): Promise<T | null> {
  const response = await fetch(path)
  if (!response.ok) return null
  return (await response.json()) as T
}

export async function fetchFlows(): Promise<FlowRow[]> {
  const body = await getJson<{ flows: FlowRow[] }>("/api/flows")
  return body?.flows ?? []
}

export async function fetchRuns(
  opts: { flow?: string; limit?: number } = {},
): Promise<RunSummary[]> {
  const query = new URLSearchParams()
  if (opts.flow) query.set("flow", opts.flow)
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
 * The only two calls in the app that change anything.
 *
 * Both answer with a decision rather than throwing: a refused accept is an
 * answer about the reader's own project -- uncommitted edits, or a file they
 * changed too -- and the page has to say which.
 */
export interface Decision {
  ok: boolean
  accepted?: number
  discarded?: number
  dirty?: string[]
  conflict?: string[]
  error?: string
}

async function post(path: string, body: unknown): Promise<Decision> {
  try {
    const response = await fetch(path, {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(body),
    })
    const payload = await response.json().catch(() => ({}))
    return { ok: response.ok, ...payload }
  } catch {
    return { ok: false, error: "the daemon did not answer" }
  }
}

export function accept(flow: string, throughRunId?: string): Promise<Decision> {
  return post(`/api/flows/${encodeURIComponent(flow)}/accept`, {
    through_run_id: throughRunId,
  })
}

export function discard(flow: string, fromRunId?: string): Promise<Decision> {
  return post(`/api/flows/${encodeURIComponent(flow)}/discard`, {
    from_run_id: fromRunId,
  })
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
