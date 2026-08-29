/**
 * Every model this project can reach.
 *
 * Not what it is bound to -- that is one line of the answer and the smaller
 * one. The question this opens for is "what could I be running, and what would
 * it cost", so the shape is endpoint → its models, asked live because a
 * catalogue written down a month ago has since gone wrong.
 *
 * Shell UI, not a skin, so it is allowed to read the API. It hangs off the
 * rail rather than off a card because a project's endpoints are the project's,
 * not one task's.
 *
 * Everything a row shows is what the endpoint said about that model. A blank
 * is "it did not say", never a zero and never a guess -- poieo keeps no price
 * table, and this does not become one.
 */

import { useEffect, useState } from "react"

import { fetchModels } from "../api"
import type { Endpoint, ModelsReport, ServedModel } from "../api"
import "./models.css"

export function Models({
  project,
  onClose,
}: {
  project: string
  onClose(): void
}) {
  const [report, setReport] = useState<ModelsReport | null | undefined>(undefined)
  const [filter, setFilter] = useState("")

  useEffect(() => {
    let live = true
    setReport(undefined)
    void fetchModels(project).then((answer) => {
      if (live) setReport(answer)
    })
    return () => {
      live = false
    }
  }, [project])

  return (
    <aside className="models" aria-label="Models">
      <header className="models-head">
        <h2>models</h2>
        {report?.binding ? (
          <span className="models-file" title={report.binding.path}>
            {shortPath(report.binding.path)}
          </span>
        ) : null}
        <button type="button" className="models-close" onClick={onClose}>
          ✕
        </button>
      </header>
      {/* One endpoint can offer hundreds. Filtering is how a catalogue is read,
          and the alternative -- showing the first forty -- reads as all of
          them. */}
      {report?.binding ? (
        <input
          className="models-filter"
          type="search"
          aria-label="Filter models"
          placeholder="filter"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        />
      ) : null}
      {/* One box under the header, because the aside is a two-row grid: left
          loose, its `1fr` lands on whichever child happens to be second and
          stretches that one alone. */}
      <div className="models-body">
        <Body report={report} filter={filter.trim().toLowerCase()} />
      </div>
    </aside>
  )
}

function Body({
  report,
  filter,
}: {
  report: ModelsReport | null | undefined
  filter: string
}) {
  if (report === undefined) return <p className="models-note">asking…</p>
  // Null is the daemon not answering, which is a different thing from a
  // project with no models file -- and only one of them is yours to fix.
  if (report === null) {
    return <p className="models-note">the endpoints could not be asked.</p>
  }
  if (!report.binding) {
    return (
      <p className="models-note">
        This project names no models file. <code>poieo init</code> writes one.
      </p>
    )
  }
  const blocks = report.endpoints.map((endpoint) => ({
    endpoint,
    shown: filter
      ? endpoint.models.filter((m) => m.id.toLowerCase().includes(filter))
      : endpoint.models,
  }))
  // An endpoint with nothing matching is dropped rather than shown empty: with
  // a filter on, "no answer" under a heading would read as a broken endpoint
  // rather than as a search that missed.
  const matched = filter ? blocks.filter((b) => b.shown.length > 0) : blocks
  if (filter && matched.length === 0) {
    return <p className="models-note">nothing matches “{filter}”.</p>
  }
  return (
    <>
      {matched.map(({ endpoint, shown }) => (
        <EndpointBlock
          key={endpoint.name}
          endpoint={endpoint}
          shown={shown}
          filtered={Boolean(filter)}
        />
      ))}
    </>
  )
}

function EndpointBlock({
  endpoint,
  shown,
  filtered,
}: {
  endpoint: Endpoint
  shown: ServedModel[]
  filtered: boolean
}) {
  return (
    <section className="models-endpoint" data-endpoint={endpoint.name}>
      <h3>
        <span className="models-endpoint-name">{endpoint.name}</span>
        <span className="models-kind">{endpoint.type}</span>
        {/* What the listing *means*, not just how long it is. Ollama's is
            `ollama list` -- pulled onto this disk, ready now. A routed
            endpoint's is a catalogue of what it would run for money, with
            nothing here yet. Identical-looking lists, different things. */}
        <span
          className="models-count"
          data-listing={endpoint.installed ? "here" : "offered"}
        >
          {countText(endpoint, shown, filtered)}
        </span>
        {/* Only when the endpoint names a variable. One that does not is
            resolving its own credential, which is not news. */}
        {endpoint.api_key_env ? (
          <span
            className="models-key"
            data-key={endpoint.api_key_set ? "set" : "missing"}
          >
            {endpoint.api_key_env}
            {endpoint.api_key_set ? " ✓" : " — not set"}
          </span>
        ) : null}
      </h3>
      {shown.length > 0 ? (
        <ul className="models-list">
          {shown.map((model) => (
            <Row key={model.id} model={model} local={endpoint.installed} />
          ))}
        </ul>
      ) : (
        <p className="models-note">{emptyBecause(endpoint)}</p>
      )}
    </section>
  )
}

/**
 * Why an endpoint listed nothing.
 *
 * Three different facts, and a panel that ran them together would report a
 * working `mock` as a broken server. The missing key comes first because it is
 * the one the reader can do something about.
 */
function emptyBecause(endpoint: Endpoint): string {
  if (!endpoint.askable) return "answers from the models file, so there is nothing to ask"
  if (endpoint.api_key_set === false) return `no answer — ${endpoint.api_key_env} is not set`
  return "no answer"
}

/** How many, and of what -- the endpoint's own count when a filter narrows it. */
function countText(endpoint: Endpoint, shown: ServedModel[], filtered: boolean): string {
  const whole = endpoint.models.length
  if (!whole) return ""
  const what = endpoint.installed ? "on this machine" : "offered"
  if (filtered && shown.length !== whole) return `${shown.length} of ${whole} ${what}`
  return `${whole} ${what}`
}


function Row({ model, local }: { model: ServedModel; local: boolean }) {
  return (
    <li data-model={model.ref}>
      <span className="models-id" title={model.id}>
        {model.id}
      </span>
      <span className="models-facts">
        {model.context ? <span data-fact="context">{compact(model.context)}</span> : null}
        {model.size ? <span data-fact="size">{model.size}</span> : null}
        {model.quantization ? (
          <span data-fact="quant">{model.quantization}</span>
        ) : null}
        {model.capabilities
          .filter((c) => c !== "completion")
          .map((c) => (
            <span key={c} data-fact="can">
              {c}
            </span>
          ))}
      </span>
      <span className="models-price" data-price={priceKind(model, local)}>
        {priceText(model, local)}
      </span>
      {/* One word, and only on the models a role is actually on. */}
      {model.used_by.length > 0 ? (
        <span className="models-using">{model.used_by.join(", ")}</span>
      ) : null}
    </li>
  )
}

function priceKind(model: ServedModel, local: boolean): string {
  if (model.price) return model.price.input === 0 && model.price.output === 0 ? "free" : "paid"
  // Ollama runs the model here and bills nothing for it. That is a fact about
  // the backend, not a rate looked up in a table.
  return local ? "local" : "unknown"
}

function priceText(model: ServedModel, local: boolean): string {
  if (model.price) {
    if (model.price.input === 0 && model.price.output === 0) return "free"
    return `$${money(model.price.input)} / $${money(model.price.output)}`
  }
  return local ? "runs here" : ""
}

/**
 * Per million tokens, at the precision the difference is visible in.
 *
 * Three places under a dollar, because the cheap end of a catalogue is where
 * models are actually told apart -- $0.042 and $0.15 are a 3.5x difference
 * that two places would render as $0.04 and $0.15. Trailing zeros go: a column
 * of `$0.150` reads as more precision than anybody published.
 */
function money(value: number): string {
  if (value >= 100) return value.toFixed(0)
  if (value >= 1) return value.toFixed(2)
  return value.toFixed(3).replace(/0+$/, "").replace(/\.$/, "")
}

/** 262144 reads as 262k. A window is compared, not counted. */
function compact(tokens: number): string {
  if (tokens >= 1_000_000) return `${Math.round(tokens / 100_000) / 10}M`
  if (tokens >= 1_000) return `${Math.round(tokens / 1_000)}k`
  return String(tokens)
}

/** The tail of a path: enough to recognise, short enough for a header. */
function shortPath(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts.slice(-2).join("/")
}
