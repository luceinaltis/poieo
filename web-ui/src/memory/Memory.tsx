import { useCallback, useEffect, useMemo, useRef, useState } from "react"

import { askMemory, fetchMemory, fetchMemoryEntry, searchMemory } from "../api"
import { Constellation } from "./Constellation"
import type {
  MemoryAskReply,
  MemoryEntry,
  MemoryOverview,
  MemoryResult,
  MemorySearchMode,
} from "./types"
import "./memory.css"

type Mode = MemorySearchMode | "ask"

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

export function Memory({ project }: { project: string }) {
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
  const request = useRef(0)
  const detailRequest = useRef(0)

  useEffect(() => {
    let alive = true
    setOverview(undefined)
    setResults([])
    setAnswer(null)
    setDetail(null)
    setSelected(null)
    setSearched(false)
    setBusy(false)
    setError(null)
    request.current += 1
    detailRequest.current += 1
    void fetchMemory(project).then((found) => {
      if (alive) setOverview(found)
    })
    return () => {
      alive = false
    }
  }, [project])

  const selectEntry = useCallback(
    async (slug: string) => {
      const turn = ++detailRequest.current
      setSelected(slug)
      setDetail(null)
      const chosen = await fetchMemoryEntry(project, slug)
      if (turn === detailRequest.current && chosen?.slug === slug) setDetail(chosen)
    },
    [project],
  )

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
            onClick={() => setMode("words")}
          >
            words
          </button>
          <button
            type="button"
            data-mode="meaning"
            aria-pressed={mode === "meaning"}
            disabled={!overview.capabilities.meaning}
            title={overview.capabilities.meaning ? "Find close meanings" : "Name a memory_embedder role to use this"}
            onClick={() => setMode("meaning")}
          >
            meaning
          </button>
          <button
            type="button"
            data-mode="ask"
            aria-pressed={mode === "ask"}
            disabled={!overview.capabilities.ask}
            title={overview.capabilities.ask ? "Answer from memory with citations" : "Name a memory_searcher role to use this"}
            onClick={() => setMode("ask")}
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
      </form>

      <div className="memory-main">
        <div className="memory-space">
          <div className="memory-caption">
            <span>{kept} kept</span>
            <span>{past} set aside</span>
            <span>{visibleGraph.edges.length} connections</span>
          </div>
          <Constellation
            graph={visibleGraph}
            highlighted={highlighted}
            cited={cited}
            selected={selected}
            onSelect={(slug) => void selectEntry(slug)}
          />
          <div className="memory-hint">drag to orbit · wheel to travel · select a memory</div>
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
                {!detail.superseded_by ? null : <span>set aside for {detail.superseded_by}</span>}
              </div>
              <p>{detail.body}</p>
              {detail.second_look.map((reason) => (
                <p className="memory-second-look" key={reason}>{reason}</p>
              ))}
              <dl>
                <dt>scope</dt>
                <dd>{detail.scope.join(", ") || "global"}</dd>
                {detail.anchors.length ? (
                  <>
                    <dt>anchors</dt>
                    <dd>{detail.anchors.join(", ")}</dd>
                  </>
                ) : null}
                <dt>updated</dt>
                <dd>{new Date(detail.updated_at).toLocaleString()}</dd>
              </dl>
            </article>
          ) : null}

          {overview.page ? (
            <details className="memory-page">
              <summary>What this project always requires</summary>
              <p>{overview.page}</p>
            </details>
          ) : null}
        </aside>
      </div>
    </section>
  )
}
