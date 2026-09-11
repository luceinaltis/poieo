import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import {
  askMemory,
  fetchMemory,
  fetchMemoryEntry,
  keepMemory,
  putMemoryPage,
  searchMemory,
  setAsideMemory,
  settleMemorySuggestion,
} from "../api"
import { Gauge } from "../Gauge"
import { Constellation } from "./Constellation"
import { learnerLoad, pageLength } from "./load"
import type {
  LearningPass,
  MemoryAskReply,
  MemoryEntry,
  MemoryOverview,
  MemoryResult,
  MemorySearchMode,
} from "./types"
import "./memory.css"

type Mode = MemorySearchMode | "ask"
export const MEMORY_REFRESH_MS = 15_000

/** One pass in a sentence: what it read and what came of it. */
function passLine(pass: LearningPass): string {
  const records = `read ${pass.read} record${pass.read === 1 ? "" : "s"}`
  if (pass.error !== null) return `${records}, failed and will reread`
  const did = [
    pass.kept.length ? `kept ${pass.kept.length}` : "",
    pass.set_aside.length ? `set aside ${pass.set_aside.length}` : "",
    pass.dropped.length ? `let go ${pass.dropped.length}` : "",
  ].filter(Boolean)
  return did.length ? `${records}, ${did.join(", ")}` : `${records}, kept nothing`
}

/**
 * What learning did lately: the pass log, which was a file only the CLI ever
 * read. Every slug is a way into the entry; every reason is the harness's
 * own sentence for why a proposal was let go.
 */
function Learning({ passes, onSelect }: { passes: LearningPass[]; onSelect(slug: string): void }) {
  if (!passes.length) return null
  const latest = passes[0]
  const slugs = (list: string[]) =>
    list.map((slug) => (
      <button type="button" className="memory-related" data-related={slug} key={slug} onClick={() => onSelect(slug)}>
        {slug}
      </button>
    ))
  return (
    <details className="memory-learning">
      <summary>
        {`learning · ${new Date(latest.at).toLocaleString()} · ${passLine(latest)}`}
      </summary>
      <ol>
        {passes.map((pass) => (
          <li key={pass.at} data-failed={String(pass.error !== null)}>
            <time dateTime={pass.at}>{new Date(pass.at).toLocaleString()}</time>
            <span>{passLine(pass)}</span>
            {pass.error !== null ? <span className="memory-pass-error">{pass.error}</span> : null}
            {pass.kept.length ? <span>kept {slugs(pass.kept)}</span> : null}
            {pass.set_aside.length ? <span>set aside {slugs(pass.set_aside)}</span> : null}
            {pass.dropped.map((reason) => (
              <span className="memory-pass-dropped" key={reason}>
                let go · {reason}
              </span>
            ))}
            {pass.page ? <span>suggested for the page · {pass.page}</span> : null}
          </li>
        ))}
      </ol>
    </details>
  )
}

function AnswerText({ text, onCitation }: { text: string; onCitation(slug: string): void }) {
  const parts = text.split(/(\[\[[^\[\]]+\]\])/g)
  return (
    <p className="memory-answer">
      {parts.map((part, index) => {
        const match = /^\[\[([^\[\]]+)\]\]$/.exec(part)
        if (!match) return <span key={`${part}-${index}`}>{part}</span>
        const slug = match[1]
        return (
          <button
            key={`${slug}-${index}`}
            type="button"
            className="memory-citation"
            data-citation={slug}
            onClick={() => onCitation(slug)}
          >
            {slug}
          </button>
        )
      })}
    </p>
  )
}

export function Memory({
  project,
  focus = null,
  onOpenRun,
}: {
  project: string
  /**
   * An entry to open on arrival -- how the drawer's "memory shown to this
   * run" lands here. An object rather than the slug, so naming the same
   * entry twice from two places is two arrivals.
   */
  focus?: { slug: string } | null
  /** Open the task drawer on one of an entry's source runs. */
  onOpenRun?(task: string, runId: string): void
}) {
  const [overview, setOverview] = useState<MemoryOverview | null | undefined>(undefined)
  const [query, setQuery] = useState("")
  const [mode, setMode] = useState<Mode>("words")
  const [includeSetAside, setIncludeSetAside] = useState(true)
  const [results, setResults] = useState<MemoryResult[]>([])
  const [answer, setAnswer] = useState<MemoryAskReply | null>(null)
  const [detail, setDetail] = useState<MemoryEntry | null>(null)
  const [selected, setSelected] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [searched, setSearched] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [pageDraft, setPageDraft] = useState<string | null>(null)
  const [newSlug, setNewSlug] = useState("")
  const [newBody, setNewBody] = useState("")
  const [replacement, setReplacement] = useState("")
  const [writing, setWriting] = useState(false)
  const request = useRef(0)
  const detailRequest = useRef(0)
  const writeTurn = useRef(0)
  const overviewRevision = useRef<string | null>(null)
  // The overview reader of the open place, so a write can reread at once
  // rather than wait out the refresh interval.
  const refresh = useRef<(() => Promise<void>) | null>(null)

  useEffect(() => {
    let alive = true
    let reading = false
    let hasOverview = false
    overviewRevision.current = null
    setOverview(undefined)
    setResults([])
    setAnswer(null)
    setDetail(null)
    setSelected(null)
    setSearched(false)
    setBusy(false)
    setError(null)
    setPageDraft(null)
    setNewSlug("")
    setNewBody("")
    setReplacement("")
    setWriting(false)
    request.current += 1
    detailRequest.current += 1
    writeTurn.current += 1
    const readOverview = async () => {
      if (reading) return
      reading = true
      try {
        const found = await fetchMemory(project, overviewRevision.current ?? undefined)
        if (!alive || found === undefined) return
        if (found === null && hasOverview) return
        hasOverview = found !== null
        overviewRevision.current = found?.revision ?? null
        setOverview(found)
      } finally {
        reading = false
      }
    }
    refresh.current = readOverview
    void readOverview()
    const timer = window.setInterval(() => void readOverview(), MEMORY_REFRESH_MS)
    return () => {
      alive = false
      refresh.current = null
      window.clearInterval(timer)
    }
  }, [project])

  const selectEntry = useCallback(
    async (slug: string) => {
      const turn = ++detailRequest.current
      const previous = detail
      setSelected(slug)
      setError(null)
      const chosen = await fetchMemoryEntry(project, slug)
      if (turn !== detailRequest.current) return
      if (chosen?.slug === slug) {
        setDetail(chosen)
        return
      }
      setSelected(previous?.slug ?? null)
      setError(`The memory named ${slug} is not available.`)
    },
    [detail, project],
  )

  // Read through a ref so arriving with a focus does not re-run on every
  // detail change: `selectEntry` is rebuilt whenever the detail moves.
  const select = useRef(selectEntry)
  select.current = selectEntry
  useEffect(() => {
    if (focus) void select.current(focus.slug)
  }, [focus])

  const submit = async (event: React.FormEvent) => {
    event.preventDefault()
    const asked = query.trim()
    if (!asked || busy) return
    const turn = ++request.current
    setBusy(true)
    setError(null)
    setSearched(true)
    setDetail(null)
    setSelected(null)
    detailRequest.current += 1
    try {
      if (mode === "ask") {
        const reply = await askMemory(project, asked, includeSetAside)
        if (turn !== request.current) return
        if (!reply.ok) {
          setError(reply.error ?? "The memory search did not answer.")
          setAnswer(null)
          setResults([])
          return
        }
        setAnswer(reply)
        setResults(reply.evidence ?? [])
      } else {
        const reply = await searchMemory(project, asked, mode, includeSetAside)
        if (turn !== request.current) return
        if (!reply.ok) {
          setError(reply.error ?? "The memory search did not answer.")
          setAnswer(null)
          setResults([])
          return
        }
        setAnswer(null)
        setResults(reply.results ?? [])
      }
    } finally {
      if (turn === request.current) setBusy(false)
    }
  }

  // One shape for every write: refuse while one is in flight, keep a refusal
  // visible as a result, reread the place on success, and let a project
  // switch mid-flight discard the outcome.
  const written = async (
    go: () => Promise<{ ok: boolean; error?: string }>,
    then?: () => Promise<void>,
  ): Promise<boolean> => {
    if (writing) return false
    const turn = ++writeTurn.current
    setWriting(true)
    setError(null)
    try {
      const reply = await go()
      if (turn !== writeTurn.current) return false
      if (!reply.ok) {
        setError(reply.error ?? "The daemon refused the write.")
        return false
      }
      await refresh.current?.()
      if (turn !== writeTurn.current) return false
      await then?.()
      return true
    } finally {
      if (turn === writeTurn.current) setWriting(false)
    }
  }

  const savePage = async (event: React.FormEvent) => {
    event.preventDefault()
    if (pageDraft === null) return
    const draft = pageDraft
    if (await written(() => putMemoryPage(project, draft))) setPageDraft(null)
  }

  const settle = (accept: boolean) => void written(() => settleMemorySuggestion(project, accept))

  const keep = async (event: React.FormEvent) => {
    event.preventDefault()
    const slug = newSlug.trim()
    const body = newBody.trim()
    if (!slug || !body) return
    await written(
      () => keepMemory(project, slug, body),
      async () => {
        setNewSlug("")
        setNewBody("")
        await selectEntry(slug)
      },
    )
  }

  const retire = async (event: React.FormEvent) => {
    event.preventDefault()
    const slug = detail?.slug
    const because = replacement.trim()
    if (!slug || !because) return
    await written(
      () => setAsideMemory(project, slug, because),
      async () => {
        setReplacement("")
        await selectEntry(slug)
      },
    )
  }

  const visibleGraph = useMemo(() => {
    const graph = overview?.graph ?? {
      nodes: [],
      edges: [],
      total_nodes: 0,
      total_edges: 0,
      truncated: false,
      edges_truncated: false,
    }
    if (includeSetAside) return graph
    const nodes = graph.nodes.filter((node) => node.standing)
    const kept = new Set(nodes.map((node) => node.slug))
    return {
      ...graph,
      nodes,
      edges: graph.edges.filter((edge) => kept.has(edge.source) && kept.has(edge.target)),
    }
  }, [includeSetAside, overview])

  const highlighted = useMemo(() => new Set(results.map((row) => row.slug)), [results])
  const cited = useMemo(() => new Set(answer?.citations ?? []), [answer])

  const changePast = (checked: boolean) => {
    request.current += 1
    detailRequest.current += 1
    setIncludeSetAside(checked)
    setResults([])
    setAnswer(null)
    setDetail(null)
    setSelected(null)
    setSearched(false)
    setBusy(false)
    setError(null)
  }

  const changeMode = (next: Mode) => {
    if (next === mode) return
    request.current += 1
    detailRequest.current += 1
    setMode(next)
    setResults([])
    setAnswer(null)
    setDetail(null)
    setSelected(null)
    setSearched(false)
    setBusy(false)
    setError(null)
  }

  if (overview === undefined) {
    return <div className="memory-state">Reading this project's memory…</div>
  }
  if (overview === null) {
    return <div className="memory-state memory-state-error">The daemon did not return this project's memory.</div>
  }
  if (!overview.enabled) {
    return (
      <div className="memory-state">
        <strong>This project keeps no long memory.</strong>
        <span>Its memory begins when memory/longterm.sqlite3 exists.</span>
      </div>
    )
  }

  const load = learnerLoad(overview)
  const kept = overview.stats?.kept ?? visibleGraph.nodes.filter((node) => node.standing).length
  const past = overview.stats?.set_aside ?? visibleGraph.nodes.filter((node) => !node.standing).length
  const placeholder = mode === "ask" ? "Ask what this project knows" : "Search memory"

  return (
    <section className="memory" aria-label="Project memory">
      <form className="memory-search" onSubmit={submit}>
        <label className="memory-query">
          <span>Search memory</span>
          <input
            aria-label="Search memory"
            value={query}
            maxLength={2000}
            placeholder={placeholder}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className="memory-modes" role="group" aria-label="Search mode">
          <button
            type="button"
            data-mode="words"
            aria-pressed={mode === "words"}
            onClick={() => changeMode("words")}
          >
            words
          </button>
          <button
            type="button"
            data-mode="meaning"
            aria-pressed={mode === "meaning"}
            disabled={!overview.capabilities.meaning}
            title={overview.capabilities.meaning ? "Find close meanings" : "Name a memory_embedder role to use this"}
            onClick={() => changeMode("meaning")}
          >
            meaning
          </button>
          <button
            type="button"
            data-mode="ask"
            aria-pressed={mode === "ask"}
            disabled={!overview.capabilities.ask}
            title={overview.capabilities.ask ? "Answer from memory with citations" : "Name a memory_searcher role to use this"}
            onClick={() => changeMode("ask")}
          >
            ask
          </button>
        </div>
        <label className="memory-past">
          <input
            type="checkbox"
            checked={includeSetAside}
            onChange={(event) => changePast(event.target.checked)}
          />
          set aside
        </label>
        <button className="memory-go" type="submit" disabled={busy || !query.trim()}>
          {busy ? "looking…" : mode === "ask" ? "ask" : "find"}
        </button>
        {!overview.capabilities.meaning || !overview.capabilities.ask ? (
          <p className="memory-capability-note">
            {!overview.capabilities.meaning ? <span>meaning needs memory_embedder</span> : null}
            {!overview.capabilities.ask ? <span>ask needs memory_searcher</span> : null}
          </p>
        ) : null}
      </form>

      <div className="memory-main">
        <div className="memory-space">
          <div className="memory-caption">
            <span>{kept} kept</span>
            <span>{past} set aside</span>
            <span>{visibleGraph.edges.length} connections</span>
          </div>
          <div className="memory-gauges">
            {overview.stats ? (
              <Gauge label="page" used={overview.stats.page_chars} limit={overview.stats.page_budget} unit="chars" />
            ) : null}
            {load ? (
              <Gauge
                label="learner"
                used={load.tokens ?? load.chars}
                limit={load.context}
                unit={load.tokens === null ? "chars" : "tokens"}
                estimate={load.tokens !== null}
                title={
                  `the learner's next question: ${load.chars.toLocaleString("en-US")} characters over ${load.entries} memories` +
                  (load.context === null
                    ? `${load.model ? `; ${load.model}` : ""} names no window`
                    : `, about ${(load.tokens as number).toLocaleString("en-US")} of ${load.context.toLocaleString("en-US")} tokens (${load.measured ? "as the last pass counted" : "assuming four characters a token"}) on ${load.model}`)
                }
              />
            ) : null}
          </div>
          <Constellation
            graph={visibleGraph}
            highlighted={highlighted}
            cited={cited}
            selected={selected}
            onSelect={(slug) => void selectEntry(slug)}
          />
          <div className="memory-hint">relationships form regions · drag to orbit · wheel to travel · select a memory</div>
          <div className="memory-legend" aria-label="Connection legend">
            <span data-kind="mentions">mentions</span>
            <span data-kind="depends_on">leans on</span>
            <span data-kind="contradicts">disagrees</span>
            <span data-kind="supersedes">set aside</span>
          </div>
          {overview.graph.truncated || overview.graph.edges_truncated ? (
            <p className="memory-truncated">
              Showing {overview.graph.nodes.length} of {overview.graph.total_nodes} memories and {overview.graph.edges.length} of {overview.graph.total_edges} connections. Search reaches every memory.
            </p>
          ) : null}
        </div>

        <aside className="memory-evidence" aria-label="Memory evidence" aria-live="polite">
          <header className="memory-evidence-head">
            <span>{mode === "ask" ? "answer & evidence" : "search evidence"}</span>
            {answer?.model ? <code>{answer.model}</code> : null}
          </header>

          {overview.suggestion ? (
            <div className="memory-suggestion" data-suggestion={overview.suggestion}>
              <span>the last pass suggests</span>
              <p>{overview.suggestion}</p>
              <div>
                <button type="button" data-do="accept-suggestion" disabled={writing} onClick={() => settle(true)}>
                  add to page
                </button>
                <button type="button" data-do="dismiss-suggestion" disabled={writing} onClick={() => settle(false)}>
                  let go
                </button>
              </div>
            </div>
          ) : null}

          {error ? <p className="refusal memory-error" role="alert">{error}</p> : null}
          {answer?.degraded ? <p className="memory-degraded">{answer.degraded}</p> : null}
          {answer?.answer ? (
            <AnswerText text={answer.answer} onCitation={(slug) => void selectEntry(slug)} />
          ) : null}

          {results.length ? (
            <div className="memory-results" aria-label="Matching memories">
              {results.map((row) => (
                <button
                  type="button"
                  key={row.slug}
                  data-result={row.slug}
                  data-selected={selected === row.slug}
                  data-standing={row.standing}
                  onClick={() => void selectEntry(row.slug)}
                >
                  <span>{row.slug}</span>
                  <small>{row.preview}</small>
                </button>
              ))}
            </div>
          ) : searched && !busy && !error && !answer?.answer ? (
            <p className="memory-none">No matching memory.</p>
          ) : !detail ? (
            <p className="memory-invitation">Search, ask, or select a point to read the memory behind it.</p>
          ) : null}

          {detail ? (
            <article className="memory-detail" data-memory={detail.slug}>
              <div className="memory-detail-title">
                <strong>{detail.slug}</strong>
                {!detail.superseded_by ? null : <span>set aside</span>}
              </div>
              <p>{detail.body}</p>
              {detail.second_look.map((reason) => (
                <p className="memory-second-look" key={reason}>{reason}</p>
              ))}
              <dl>
                {[
                  ["mentions →", detail.mentions],
                  ["depends on →", detail.links.depends_on],
                  ["disagrees with ↔", detail.links.contradicts],
                  ["set aside for →", detail.superseded_by ? [detail.superseded_by] : []],
                ].map(([label, slugs]) =>
                  slugs.length ? (
                    <div className="memory-relation" key={label as string}>
                      <dt>{label as string}</dt>
                      <dd>
                        {(slugs as string[]).map((slug) => (
                          <button
                            type="button"
                            className="memory-related"
                            data-related={slug}
                            key={slug}
                            onClick={() => void selectEntry(slug)}
                          >
                            {slug}
                          </button>
                        ))}
                      </dd>
                    </div>
                  ) : null,
                )}
                <dt>scope</dt>
                <dd>{detail.scope.join(", ") || "global"}</dd>
                {detail.anchors.length ? (
                  <>
                    <dt>anchors</dt>
                    <dd>{detail.anchors.join(", ")}</dd>
                  </>
                ) : null}
                {detail.source.length ? (
                  <>
                    <dt>source</dt>
                    <dd>
                      {(detail.sources ?? detail.source.map((run_id) => ({ run_id, task: null }))).map(
                        ({ run_id, task }) =>
                          task && onOpenRun ? (
                            <button
                              type="button"
                              className="memory-related memory-source"
                              data-source={run_id}
                              key={run_id}
                              onClick={() => onOpenRun(task, run_id)}
                            >
                              {run_id}
                            </button>
                          ) : (
                            // The record is gone with runs/, so the id has
                            // nowhere to go -- said, but not offered.
                            <span className="memory-source" data-source={run_id} key={run_id}>
                              {run_id}
                            </span>
                          ),
                      )}
                    </dd>
                  </>
                ) : null}
                {detail.valid_from ? (
                  <>
                    <dt>valid from</dt>
                    <dd><time dateTime={detail.valid_from}>{detail.valid_from}</time></dd>
                  </>
                ) : null}
                <dt>updated</dt>
                <dd>{new Date(detail.updated_at).toLocaleString()}</dd>
              </dl>
              {detail.superseded_by ? null : (
                <form className="memory-set-aside" onSubmit={(event) => void retire(event)}>
                  <input
                    aria-label="Replaced by"
                    placeholder="set aside for…"
                    value={replacement}
                    onChange={(event) => setReplacement(event.target.value)}
                  />
                  <button type="submit" data-do="set-aside" disabled={writing || !replacement.trim()}>
                    set aside
                  </button>
                </form>
              )}
              {detail.history.length ? (
                <details className="memory-history">
                  <summary>history ({detail.history.length})</summary>
                  <ol>
                    {detail.history.map((event, index) => (
                      <li key={`${event.at}-${event.writer}-${index}`}>
                        <time dateTime={event.at}>{new Date(event.at).toLocaleString()}</time>
                        <span>{event.writer} · {event.did}{event.slug ? ` · ${event.slug}` : ""}</span>
                      </li>
                    ))}
                  </ol>
                </details>
              ) : null}
            </article>
          ) : null}

          <form className="memory-keep" aria-label="Keep a memory" onSubmit={(event) => void keep(event)}>
            <span>keep a memory</span>
            <input
              aria-label="Memory name"
              placeholder="a-name-like-this"
              value={newSlug}
              onChange={(event) => setNewSlug(event.target.value)}
            />
            <textarea
              aria-label="What stays true"
              placeholder="One statement that stays true."
              value={newBody}
              onChange={(event) => setNewBody(event.target.value)}
            />
            <button type="submit" data-do="keep" disabled={writing || !newSlug.trim() || !newBody.trim()}>
              keep
            </button>
          </form>

          <details className="memory-page" open={pageDraft !== null || undefined}>
            <summary>What this project always requires</summary>
            {pageDraft === null ? (
              <>
                {overview.page ? <p>{overview.page}</p> : <p className="memory-none">Nothing yet.</p>}
                <button type="button" data-do="edit-page" onClick={() => setPageDraft(overview.page_text)}>
                  edit
                </button>
              </>
            ) : (
              <form className="memory-page-edit" onSubmit={(event) => void savePage(event)}>
                <textarea aria-label="Page" value={pageDraft} onChange={(event) => setPageDraft(event.target.value)} />
                {/* Counted as a run reads it, against the budget. Over it the
                    colour and the word say so; saving is never refused, since
                    the page must not become a way to stop every task. */}
                <Gauge
                  label="as a run reads it"
                  used={pageLength(pageDraft)}
                  limit={overview.stats?.page_budget ?? null}
                  unit="chars"
                />
                <div>
                  <button type="submit" data-do="save-page" disabled={writing}>
                    save
                  </button>
                  <button type="button" data-do="cancel-page" onClick={() => setPageDraft(null)}>
                    cancel
                  </button>
                </div>
              </form>
            )}
          </details>

          <Learning passes={overview.learning ?? []} onSelect={(slug) => void selectEntry(slug)} />
        </aside>
      </div>
    </section>
  )
}
