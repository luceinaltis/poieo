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

import { addEngine, fetchModels, fetchUndeclared, pickModel } from "../api"
import type {
  Endpoint,
  ModelsAnswer,
  ModelsReport,
  ServedModel,
  UndeclaredEngine,
} from "../api"
import { useAct } from "../useAct"
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
  // Which role a click moves. `default` unless the file names others and the
  // reader picks one -- the common project has no others and never sees this.
  const [role, setRole] = useState("default")
  const [reload, setReload] = useState(0)
  const [asking, setAsking] = useState(true)
  // Two requests, not one. Looking for an engine this project has never used
  // means asking ports nothing may be listening on, and a closed one costs a
  // whole timeout -- so the catalogue would have waited a second and a half
  // for its own footnote. This lands under it whenever it arrives.
  const [offers, setOffers] = useState<UndeclaredEngine[]>([])
  // A write can land in the file and still be refused by the running daemon,
  // which keeps the last good spec -- and the panel reads that same spec, so it
  // would redraw off the old one with nothing said. Kept until the next write,
  // and it holds either write: `use` and `add` both answer `adopted`.
  const [notTaken, setNotTaken] = useState<ModelsAnswer | null>(null)
  const [at, setAt] = useState("")
  const [atName, setAtName] = useState("")
  const [atKeyEnv, setAtKeyEnv] = useState("")
  const { busy, refused, act } = useAct<ModelsAnswer>((answer) => {
    setNotTaken(answer.adopted === false ? answer : null)
    setReload((n) => n + 1)
  })

  // Blanking belongs to a change of subject, not to a re-ask. Every refresh
  // and every write asks again, and a panel that flashed to "asking…" each
  // time would take away the list the reader is comparing against.
  //
  // The change of subject is handled a level up, by `App` keying this on the
  // project: one field reset by hand covered the list and left the address
  // half-typed for another project and the "daemon has not taken it" warning
  // behind, redrawn under the new project's name.

  useEffect(() => {
    let live = true
    setAsking(true)
    void fetchModels(project).then((answer) => {
      if (!live) return
      setReport(answer)
      setAsking(false)
    })
    return () => {
      live = false
    }
  }, [project, reload])

  useEffect(() => {
    let live = true
    void fetchUndeclared(project).then((found) => {
      if (live) setOffers(found)
    })
    return () => {
      live = false
    }
  }, [project, reload])

  // A role the file stopped naming is not a role to keep pointing at.
  useEffect(() => {
    if (report && !report.roles.includes(role)) setRole("default")
  }, [report, role])

  const use = (model: ServedModel) =>
    void act(() => pickModel(project, model.ref, role))

  const add = (engine: UndeclaredEngine) =>
    void act(() => addEngine(project, { engine: engine.name }))

  // An engine at an address nobody guessed. Detection knows four ports on this
  // machine; a vLLM on 8001, an Ollama on a desktop and an office box had no
  // way in at all. The reader types where it is -- which backend it is comes
  // from asking it, not from a field asking them to classify their own server.
  const addAt = () => {
    if (!at.trim()) return
    void act(async () => {
      const answer = await addEngine(project, {
        url: at.trim(),
        ...(atName.trim() ? { name: atName.trim() } : {}),
        ...(atKeyEnv.trim() ? { key_env: atKeyEnv.trim() } : {}),
      })
      // Emptied here and not off `act`'s answer, which is *whether the request
      // went out* -- a refused address counts, and clearing on it left the
      // reader with "nothing usable answered at ..." beside an empty box and a
      // dead button, having to retype the address to find the typo in it.
      //
      // All three together, as one thing typed. `name` and `key_env` were
      // never cleared at all, so a name meant for one endpoint rode along to
      // the next address and was refused as a duplicate of the one just added.
      // `ok` alone is not enough, for the reason `MakeTask` gives beside its
      // own: a 2xx whose body did not parse arrives as `{ok: true}` with
      // nothing in it, and emptying the form over an endpoint that may not
      // have been declared is the same loss under a friendlier status.
      if (answer.ok && answer.engine) {
        setAt("")
        setAtName("")
        setAtKeyEnv("")
      }
      return answer
    })
  }

  return (
    <aside className="models" aria-label="Models">
      <header className="models-head">
        <h2>models</h2>
        {report?.binding ? (
          <span className="models-file" title={report.binding.path}>
            {shortPath(report.binding.path)}
          </span>
        ) : null}
        {/* The panel reads when it opens and not again. Pull a model in a
            terminal with it open and the list is stale, and closing and
            reopening was the only way to find out. Everything goes out again
            -- the declared endpoints and the machine both. */}
        <button
          type="button"
          className="models-again"
          data-do="refresh"
          aria-label="Ask the endpoints again"
          title="Ask again"
          disabled={asking}
          onClick={() => setReload((n) => n + 1)}
        >
          ↻
        </button>
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
      {/* What a click will move. Only where there is a choice: a project whose
          file names no roles has one answer, and a picker with one option in
          it is furniture -- the same rule the project picker follows. */}
      {report?.roles && report.roles.length > 1 ? (
        <label className="models-for">
          use for
          <select
            className="models-role"
            aria-label="Role to bind"
            value={role}
            onChange={(event) => setRole(event.target.value)}
          >
            {report.roles.map((one) => (
              <option key={one} value={one}>
                {one === "default" ? "everything" : one}
              </option>
            ))}
          </select>
        </label>
      ) : null}
      {/* Not a refusal: the file really did change. What did not happen is the
          running daemon taking it -- and since the panel draws from what the
          daemon kept, the reader is about to see the screen they had, with no
          explanation. This is that explanation. */}
      {notTaken ? (
        <p className="models-not-taken" data-do="not-taken" role="alert">
          {report?.binding ? shortPath(report.binding.path) : "The models file"} now{" "}
          {notTaken.status === "added" ? (
            <>
              declares <code>{notTaken.engine}</code>
            </>
          ) : (
            <>
              says <code>{notTaken.ref}</code>
            </>
          )}
          , but the daemon has not taken it — {sentence(notTaken.why)}{" "}
          {/* What the reader is about to see, which is not the same for each
              write. `use` redraws the model that was there before; `add` goes
              on offering the endpoint just declared, and pressing that offer
              again answers "this project already reaches it". */}
          {notTaken.status === "added" ? (
            <>
              The list below is what the daemon has, so it will go on offering{" "}
              <code>{notTaken.engine}</code> until that is fixed.
            </>
          ) : (
            <>
              It is still running the previous model, and will not start from
              this file until that is fixed.
            </>
          )}
        </p>
      ) : null}
      {refused ? (
        <p className="models-refusal" role="alert">
          {refused.error || "That didn't work."}
          {refused.providers?.length
            ? ` This project declares: ${refused.providers.join(", ")}.`
            : ""}
          {refused.models?.length
            ? ` It has: ${refused.models.slice(0, 6).join(", ")}.`
            : ""}
        </p>
      ) : null}
      <div className="models-body">
        {/* Above the lists, not under them. It is the one piece of news here,
            and under a 396-model catalogue it sat 2181px down a 729px panel --
            the last thing a reader would ever find. Drawn only when there is
            one, so the usual panel is not pushed down by an empty slot.

            Outside `Body` on purpose: a filter is about models, and an engine
            with none of them yet is not something a search can miss. */}
        {offers.map((one) => (
          <p className="models-offer" data-offer={one.name} key={one.name}>
            <span>
              <strong>{one.label}</strong> is answering on this machine, with{" "}
              {one.models.length} model{one.models.length === 1 ? "" : "s"} this
              project cannot use yet.
            </span>
            {/* Not "add", which the reader would have to guess the object of.
                Pressing this declares the endpoint; it moves nothing that is
                already in use, and choosing among these models is still a
                separate click on one of them. */}
            <button type="button" data-do="add" disabled={busy} onClick={() => add(one)}>
              let it use them
            </button>
          </p>
        ))}
        <Body
          report={report}
          filter={filter.trim().toLowerCase()}
          onUse={use}
          busy={busy}
        />
        {/* Last, because it is what you reach for when nothing above it was
            what you were looking for. One field that matters: which backend an
            address is comes from asking it, and the name from what it answers.
            The other two are for the project that has two vLLMs, or an
            endpoint that wants a key.

            No key field, here or anywhere on this page. A variable's *name* is
            not a secret and belongs in the file; the key belongs in the
            environment the daemon reads. */}
        {report?.binding ? (
          <section className="models-at">
            <h3>somewhere else</h3>
            <input
              data-do="url"
              type="url"
              aria-label="Address of an engine"
              placeholder="http://gpu-box:8001"
              value={at}
              disabled={busy}
              onChange={(event) => setAt(event.target.value)}
            />
            <div className="models-at-more">
              <input
                data-do="url-name"
                aria-label="What to call it"
                placeholder="name it (optional)"
                value={atName}
                disabled={busy}
                onChange={(event) => setAtName(event.target.value)}
              />
              <input
                data-do="url-key-env"
                aria-label="Variable its key is read from"
                placeholder="key variable (optional)"
                value={atKeyEnv}
                disabled={busy}
                onChange={(event) => setAtKeyEnv(event.target.value)}
              />
            </div>
            <button type="button" data-do="add-at" disabled={busy || !at.trim()} onClick={addAt}>
              ask it
            </button>
          </section>
        ) : null}
      </div>
    </aside>
  )
}

function Body({
  report,
  filter,
  onUse,
  busy,
}: {
  report: ModelsReport | null | undefined
  filter: string
  onUse(model: ServedModel): void
  busy: boolean
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
  // What is on this machine first. The report is in the binding file's order,
  // which is where `poieo init` happened to write each endpoint -- provenance,
  // not an answer to "what can I run". Measured on a real board, that order put
  // the eight models sitting on the disk 1786px below a 396-model menu of
  // things that cost money and needed a key nobody had set.
  //
  // One step, not a sort: `installed` before the rest, and inside each half the
  // reader's own arrangement is left alone. `sort` is stable, so that holds.
  const ordered = [...report.endpoints].sort((a, b) => rank(b) - rank(a))
  const blocks = ordered.map((endpoint) => ({
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
          onUse={onUse}
          busy={busy}
        />
      ))}
    </>
  )
}

function EndpointBlock({
  endpoint,
  shown,
  filtered,
  onUse,
  busy,
}: {
  endpoint: Endpoint
  shown: ServedModel[]
  filtered: boolean
  onUse(model: ServedModel): void
  busy: boolean
}) {
  const groups = groupsOf(endpoint, shown)
  return (
    <section className="models-endpoint" data-endpoint={endpoint.name}>
      <h3>
        {/* What it *is* leads; the key beside it is only the handle its owner
            typed into a file. Reading a config back to somebody is not telling
            them what is there -- a binding says what its author believed, and
            the whole reason to ask an endpoint is to find out. When nothing
            answered the question the key is all there is, so it leads then. */}
        <span className="models-endpoint-name">{endpoint.label ?? endpoint.name}</span>
        <span className="models-kind">
          {endpoint.label ? endpoint.name : endpoint.type}
        </span>
        {/* What the listing *means*, not just how long it is. Ollama's is
            `ollama list` -- pulled onto this disk, ready now. A routed
            endpoint's is a catalogue of what it would run for money, with
            nothing here yet. Identical-looking lists, different things. */}
        {/* Which machine. `poieo config` names an Ollama `ollama` wherever it
            runs, so a project with one here and one on an office server had
            two headings a reader could not tell apart -- and both of them said
            "on this machine". Host and port, and no more of the address. */}
        {endpoint.host ? (
          <span className="models-host" title={endpoint.host}>
            {endpoint.host}
          </span>
        ) : null}
        <span
          className="models-count"
          data-listing={runsOn(endpoint) ?? "offered"}
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
      {shown.length === 0 ? (
        <p className="models-note">{emptyBecause(endpoint)}</p>
      ) : groups ? (
        groups.map(([maker, models]) => (
          // Open while a filter is on: a reader who typed "deepseek" is
          // looking at the matches, not at a folder holding them.
          <details key={maker} className="models-maker" data-maker={maker} open={filtered}>
            <summary>
              <span className="models-maker-name">{maker}</span>
              <span className="models-maker-count">{models.length}</span>
            </summary>
            <ul className="models-list">
              {models.map((model) => (
                <Row
                  key={model.id}
                  model={model}
                  runs={runsOn(endpoint)}
                  // The maker is the card's own heading; repeating it on every
                  // row inside costs the width the model's name needs.
                  drop={`${maker}/`}
                  onUse={onUse}
                  busy={busy}
                />
              ))}
            </ul>
          </details>
        ))
      ) : (
        <ul className="models-list">
          {shown.map((model) => (
            <Row
              key={model.id}
              model={model}
              runs={runsOn(endpoint)}
              onUse={onUse}
              busy={busy}
            />
          ))}
        </ul>
      )}
    </section>
  )
}

/** Below this a flat list is easier to read than folders holding one row each. */
const WORTH_GROUPING = 12

/**
 * The models by who made them, or null when that would not help.
 *
 * A hosted catalogue names every model `maker/model` -- 396 of them across 58
 * makers -- and a flat list of that is not read, it is scrolled past. What is
 * on a machine is named the way its owner pulled it (`qwen3.5:latest`,
 * `hf.co/user/repo`), where the leading segment is a host or nothing at all,
 * so grouping there would invent a structure the names do not have.
 *
 * The test is mechanical rather than a list of endpoints that "have makers":
 * every id carries a prefix, and there are enough of them to be worth folding.
 * An endpoint that grows into that shape gets it without anybody deciding.
 */
function groupsOf(
  endpoint: Endpoint,
  shown: ServedModel[],
): [string, ServedModel[]][] | null {
  if (endpoint.models.length < WORTH_GROUPING) return null
  if (!endpoint.models.every((m) => m.id.includes("/"))) return null
  const by = new Map<string, ServedModel[]>()
  for (const model of shown) {
    const maker = model.id.slice(0, model.id.indexOf("/"))
    const bucket = by.get(maker)
    if (bucket) bucket.push(model)
    else by.set(maker, [model])
  }
  // Biggest first, then alphabetically: the makers a reader is looking for are
  // usually the ones with most on offer, and ties should not shuffle.
  return [...by].sort((a, b) => b[1].length - a[1].length || a[0].localeCompare(b[0]))
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
/**
 * Where this endpoint's models actually run.
 *
 * Two facts the panel used to carry as one. `installed` says the listing is
 * things **pulled and ready** rather than a menu -- a property of the backend,
 * as true of an Ollama on an office server as of one here. `here` says whose
 * machine that is, which only the address can answer. Reading the first as
 * both had every Ollama anywhere claiming to be on this laptop.
 */
type Runs = "here" | "elsewhere" | null

function rank(endpoint: Endpoint): number {
  // This machine, then somebody else's, then the menus. Both of the first two
  // are models that exist and are ready; only the first costs nothing but the
  // memory in front of the reader.
  const runs = runsOn(endpoint)
  return runs === "here" ? 2 : runs === "elsewhere" ? 1 : 0
}

function runsOn(endpoint: Endpoint): Runs {
  if (!endpoint.installed) return null
  return endpoint.here === false ? "elsewhere" : "here"
}

const WHERE: Record<string, string> = {
  here: "on this machine",
  elsewhere: "on that machine",
}

function countText(endpoint: Endpoint, shown: ServedModel[], filtered: boolean): string {
  const whole = endpoint.models.length
  if (!whole) return ""
  const what = WHERE[runsOn(endpoint) ?? ""] ?? "offered"
  if (filtered && shown.length !== whole) return `${shown.length} of ${whole} ${what}`
  return `${whole} ${what}`
}


function Row({
  model,
  runs,
  drop = "",
  onUse,
  busy,
}: {
  model: ServedModel
  runs: Runs
  /** A prefix the surrounding card already shows; stripped from the name. */
  drop?: string
  onUse(model: ServedModel): void
  busy: boolean
}) {
  const shown = drop && model.id.startsWith(drop) ? model.id.slice(drop.length) : model.id
  return (
    <li data-model={model.ref}>
      {/* The row is the button. A catalogue is read by scanning names, and a
          verb beside each of four hundred of them is four hundred words the
          eye has to skip. The whole id is on the tooltip either way: it is the
          half of `ref` a reader copies out, and a stripped name is not one
          they could type. */}
      <button
        type="button"
        className="models-id"
        title={model.id}
        data-do="use"
        disabled={busy}
        onClick={() => onUse(model)}
      >
        {shown}
      </button>
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
      <span className="models-price" data-price={priceKind(model, runs)}>
        {priceText(model, runs)}
      </span>
      {/* One word, and only on the models a role is actually on. */}
      {model.used_by.length > 0 ? (
        <span className="models-using">{model.used_by.join(", ")}</span>
      ) : null}
    </li>
  )
}

function priceKind(model: ServedModel, runs: Runs): string {
  if (model.price) return model.price.input === 0 && model.price.output === 0 ? "free" : "paid"
  // Ollama bills nothing per token wherever it runs -- a fact about the
  // backend, not a rate looked up in a table. Which machine is running it is
  // still worth saying, because it is the difference between spending your own
  // memory and spending somebody's server.
  if (runs === "here") return "local"
  return runs === "elsewhere" ? "self-hosted" : "unknown"
}

function priceText(model: ServedModel, runs: Runs): string {
  if (model.price) {
    if (model.price.input === 0 && model.price.output === 0) return "free"
    return `$${money(model.price.input)} / $${money(model.price.output)}`
  }
  return runs === "here" ? "local" : runs === "elsewhere" ? "self-hosted" : ""
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

/**
 * The daemon's own words, ended so a sentence can follow them.
 *
 * `why` is a message written to be logged, so it stops without punctuation --
 * and the paragraph it lands in has another sentence after it, which ran
 * straight on: "…is not set It is still running the previous model".
 */
function sentence(said: string | undefined): string {
  const said_ = (said ?? "").trim()
  return !said_ || /[.!?]$/.test(said_) ? said_ : `${said_}.`
}

/** The tail of a path: enough to recognise, short enough for a header. */
function shortPath(path: string): string {
  const parts = path.split(/[\\/]/).filter(Boolean)
  return parts.slice(-2).join("/")
}
