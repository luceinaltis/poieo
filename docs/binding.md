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

An answer can be read as it is written. `Provider.stream` yields pieces
of text and thinking and then the whole response, the same object
`complete` returns; the Ollama and OpenAI-compatible providers stream on
their own wires, every other backend answers in one piece through the same
seam, and a call that offers tools is answered whole because a tool call
arrives in fragments. A stream that stops before it is done is a provider
error, not a shorter answer.

A message's content is words, or a list of blocks when it carries a picture:
`{"type": "text", "text"}` and `{"type": "image", "media_type", "data"}`, the
data in base64, in a user message or a tool's result. Each provider puts the
picture in its own wire shape -- an Anthropic image block, inside the
`tool_result` when a tool returned it; an OpenAI-shaped `image_url` data URL,
shown as the next user message after a turn's tool results because that API
takes only text in a tool message; Ollama's `images` beside the words. A
harness and Jev take words only and refuse a picture rather than drop it: a
model told about an image it was never shown answers about nothing. Whether
the model behind a provider can see is the binding's business; one that
cannot answers with the provider's own refusal. A picture weighs a fixed
amount in the measure a node keeps of its conversation, never its encoded
length, and a folded history names it as `[image]`.

Embedding is an optional provider capability. Ollama and OpenAI-compatible
providers implement it; other providers refuse it through the common protocol.
The memory board uses only explicitly declared `memory_embedder` and
`memory_searcher` roles. Neither falls through to `default`: opening search
must not silently choose a chat model, an expensive endpoint, or a model that
cannot create embeddings. See [memory.md](memory.md).

The board's new-task conversation asks the `task_writer` role, and that one
does fall through to `default`: a person typed the message and pressed the
button, and the reply names the model that answered, so nothing is chosen in
silence. Declaring `task_writer` moves that conversation to another model
without touching any task. See [web.md](web.md).

## A provider that decides

`typesafe` reaches TypeSafe's System One API, whose model Jev answers typed
questions instead of writing text. It is an ordinary provider: the binding
declares it, a role chooses it, and the graph goes on naming roles.

```yaml
providers:
  jev:
    type: typesafe    # https://api.typesafe.ai and $TYPESAFE_API_KEY unless told otherwise
roles:
  judge: {provider: jev, model: jev-latest}
```

A node bound to it must say what to decide. Its typed `questions`, in the
API's own shape, travel in the node's `params`; the rendered `system` and
`prompt` become the one `state` the model is shown. The answers return as the
node's text, as JSON keyed by question: a yes/no question answers with one
probability; a choice or a score answers with the pick, the probabilities over
its options and a confidence. Read them the way any JSON answer is read:

```yaml
  - id: judge
    type: agent
    role: judge
    prompt: "Proposal: {{ input.proposal }}"
    params:
      questions:
        verdict:
          type: choice
          instructions: Is this proposal ready to build?
          criteria: {NARROW: too big for one change, DROP: not wanted, BUILD: ready}
    output: {as: verdict, format: json, path: verdict.choice}
```

A router then branches on `verdict == 'NARROW'`. Do not test the raw text with
`in`: every option's name appears in the probabilities, so the substring check
that works on a one-word answer would match whatever was asked.

The contract is narrower than a text model's, and the provider refuses rather
than pretends: a node with `tools`, a node with a history, and a node with no
`questions` each fail before any request. Generation parameters inherited from
`default` -- `max_tokens`, `temperature`, a thinking setting -- describe
writing, which this model does not do; they are not sent, and the run record
lists them under `ignored_params`. Nothing in the graph names the provider,
but a node carrying `questions` only makes sense bound to a model that
decides: rebind its role to a text model and prose comes back where JSON was
declared, and the output rule fails the node.

The endpoint publishes neither a context size nor a cost on the wire. Set
`context:` on the role if a step should be checked against the window, and
`prices` if spend should be tracked. `poieo check` probes it with one two-word
question, the only request the API has. As with any hosted provider, the state
is sent to the vendor's servers.

## Credentials and preflight

Startup resolves the roles that tasks can actually use and checks only their
required credentials, including a key variable the binding left to a preset or
to the provider's own address. `poieo check` goes further by probing configured
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

Subscription CLI calls run in an owned process group (a Job Object on Windows).
Timeout or cancellation terminates and drains the whole tree before the call
returns, so an interrupted provider cannot keep editing a released task copy.

Add an endpoint family by implementing the provider protocol and registering
its `type`. Add a recognizable local service through discovery and preset data,
without duplicating it in binding resolution. Provider-specific request
translation belongs in the provider implementation; role layering, credential
lookup, usage, and cost stay common. A provider advertises embedding support
only when its wire and response validation are implemented.
