# Binding and providers

`src/poieo/binding.py`, `src/poieo/providers/`

A binding maps the logical roles in a [graph](graph.md) to physical model
endpoints. It is the only configuration that names providers, model identifiers,
and the environment variables that hold credentials. It supplies default and
role-specific generation parameters; agent nodes may add final per-node
overrides.

## Configuration

```yaml
name: local-and-hosted
version: 1

providers:
  local:
    type: ollama
    base_url: http://127.0.0.1:11434
  hosted:
    type: anthropic
    api_key_env: ANTHROPIC_API_KEY
    timeout: 600
    max_retries: 2

default:
  provider: hosted
  model: claude-sonnet-4-5
  params: {max_tokens: 8000}

roles:
  classifier:
    provider: local
    model: qwen3:8b
    context: 32768
```

`ProviderSpec` accepts `type`, optional `base_url`, `api_key_env`, literal
`headers`, literal `query`, `timeout`, `max_retries`, and provider-specific
`options`. `ModelSpec` accepts `provider`, `model`, `params`, optional `context`,
and optional `prices`. Unknown keys are rejected.

Provider presets may supply a known endpoint and credential variable. Explicit
configuration wins over a preset. A credential named by `api_key_env` is read
from the environment at use time and is not stored in YAML, returned by the web
API, or written to a run record. `headers` and `query` are different: they are
literal values stored in YAML and sent verbatim. If they contain a secret, the
binding is secret-bearing and must not be committed or shared.

## Role resolution

Resolving a role layers configuration in this order:

1. `default`;
2. the named entry under `roles`;
3. parameters declared on the agent node.

Later parameter maps override earlier ones. The result carries the provider
name and spec, model id, merged parameters, optional context limit, and optional
prices. A compact `provider/model` reference is split only at its first slash,
because model ids may contain slashes.

An undeclared role can resolve through `default`, which keeps reusable graphs
practical. Loading a task still reports undeclared named roles so a spelling
mistake is visible before an unattended run chooses the default silently.

## Provider lifecycle and capabilities

The provider registry maps a provider `type` to its implementation. Built-in
entries cover ordinary HTTP model endpoints, known local and hosted presets,
and subscription-backed command harnesses. A `ProviderPool` creates at most one
provider instance per configured provider name and closes the instances at
shutdown.

Ordinary HTTP providers pass through unknown generation parameters and adapt
the common request to the endpoint's capabilities. Subscription harnesses have
a narrower contract and refuse parameters or execution modes they cannot honor.
This is a deliberate failure: silently dropping a requested constraint would
make the binding lie about the run.

Provider errors are normalized into poieo errors. `max_retries` is not a
portable provider policy: the built-in Anthropic provider passes it to that
SDK, while other built-in providers do not consume it. The runtime's node retry
is a separate, provider-neutral outer policy. Authentication and invalid-request
failures are not made plausible by repetition.

Embedding is an optional provider capability. Ollama and OpenAI-compatible
providers implement it; other providers refuse it through the common protocol.
The memory board uses only explicitly declared `memory_embedder` and
`memory_searcher` roles. Neither falls through to `default`: opening search
must not silently choose a chat model, an expensive endpoint, or a model that
cannot create embeddings. See [memory.md](memory.md).

## Credentials and preflight

Startup resolves the roles that tasks can actually use and checks only their
required credentials. `poieo check` goes further by probing configured
endpoints. Model discovery records endpoint and model metadata but never the
credential value; absence of reported context, size, or price remains unknown
rather than becoming zero.

Subscription providers have additional billing and isolation guards:

- they refuse the corresponding API-key environment variable when that would
  silently turn a subscription run into a metered API run;
- Claude Code receives poieo's tools through its SDK, so the normal executor
  and task isolation still apply;
- Codex uses its own workspace sandbox and refuses a task isolation or toolset
  request that poieo cannot enforce through that harness.

Never weaken one of these guards by falling back to a different execution path.

## Usage and cost

Every completion returns `Usage` with input, output, cache-read, cache-write,
and reasoning token counts supplied by the endpoint. Counts an endpoint omits
contribute zero. Cost preserves unknown as distinct from a measured zero; when
known and unknown charges mix, aggregation retains only the known subtotal.
Runtime aggregation adds the fields across attempts, turns, and nodes, and the
final run summary persists the totals.

Optional `prices` specify input, output, cache-read, and cache-write rates per
million tokens. An endpoint-reported cost is authoritative. Binding prices fill
in a cost only when the endpoint did not report one; cached input is not charged
again as ordinary input. Subscription-backed providers report zero charged cost
and may retain an estimated or notional value only as metadata.

Spend limits use only known persisted cost. Unknown cost is not guessed, so a
provider without prices can make the total an undercount; the CLI and browser
must preserve that distinction.

## Extending bindings

Add an endpoint family by implementing the provider protocol and registering
its `type`. Add a recognizable local service through discovery and preset data,
without duplicating it in binding resolution. Provider-specific request
translation belongs in the provider implementation; role layering, credential
lookup, usage, and cost stay common. A provider advertises embedding support
only when its wire and response validation are implemented.
