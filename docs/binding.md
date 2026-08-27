# Binding and providers — the physical layer

`src/poieo/binding.py`, `src/poieo/providers/`

A binding says **which model actually answers each role**. It is the only place
in poieo where a model id, an endpoint or an API key is named.

## The shape

```yaml
name: hybrid
providers:                          # physical endpoints, by name
  ollama: {type: ollama, base_url: http://localhost:11434}
  claude: {type: anthropic}

default:                            # applied to every role that does not override
  provider: claude
  model: claude-opus-5
  params: {max_tokens: 16000, effort: high}

roles:
  classifier: {provider: ollama, model: llama3.2:3b, params: {max_tokens: 16}}
```

## Resolution

`BindingSpec.resolve(role, overrides)` layers three sources and returns a
`ResolvedModel` (`provider_name`, `provider`, `model`, `params`):

```
node params   >   roles[role]   >   default
```

`provider` and `model` take the first non-empty value; `params` merge key by key,
so a role that sets `temperature` keeps the default's `max_tokens`. A role with
no provider or no model after merging raises `BindingError` — never a silent
fallback, because "which model answered" must always have an answer.

### Two questions about roles, and why both exist

`resolve()` falls back to `default` for **any** role at all — that is the point
of having a default, and a mock binding declaring no roles is a legitimate way
to run a graph. Which means two different questions have to be asked separately:

| method | asks | answer used for |
|---|---|---|
| `check_roles(roles)` | which of these cannot be resolved **at all** | `preflight()` — a hard failure |
| `undeclared(roles)` | which of these the binding **never names** | `load_flows()` — a warning |

`check_roles` is narrower than a reader expects: it only reports for a binding
that declares neither a provider nor a model to fall back on. It is
`undeclared` that catches the case that matters — `role: classifer` is one
letter from `classifier`, and the node quietly gets the binding's `default`
instead of the cheap model it asked for. In a cloud binding that is the
difference between a 256-token Haiku and Opus at 16 000, run every 30 seconds,
unattended, with nothing said.

A **warning, not a refusal**, because falling back is what a default is for.
And only asked of a binding that declares roles at all — one that declares none
is saying "one model for everything". The graph's own `default_role` is
excluded for the same reason: a node that named no role reaching the binding's
default is the arrangement working.

## Provider types

| type | talks to | notes |
|---|---|---|
| `anthropic` | Claude API | official SDK, always streams |
| `openai_compatible` | vLLM, SGLang, llama.cpp, LM Studio, TGI | `POST {base_url}/chat/completions` |
| `ollama` | Ollama | `POST {base_url}/api/chat`; `max_tokens`/`temperature` fold into `options` |
| `mock` | nothing | scripted replies for tests and dry runs |

`ProviderSpec.type` is a plain `str` validated against `KNOWN_PROVIDER_TYPES`
rather than a closed `Literal`. That is what lets
`poieo.providers.register("my_type", MyProvider)` add a backend from outside the
package while a typo in a binding file is still rejected at parse time.
`base_url` is required for `openai_compatible` and `ollama`, and API keys are
read from the environment by name (`api_key_env`) — never stored in the file.

## The provider contract

`providers/base.py` is deliberately small, and everything crossing it is
provider-neutral:

```
LLMRequest    model, messages, system, params, role, tools[]
LLMResponse   text, model, usage, stop_reason, meta, tool_calls[]
Provider      complete()  ·  health()  ·  aclose()
```

`role` travels on the request for logging and for the mock's scripting, and is
never sent to a backend. `meta` carries anything provider-specific worth keeping
— notably `raw_content`, the provider's own content blocks, which the agent loop
replays verbatim on the next turn so thinking blocks and their signatures
survive a tool round trip. Other providers ignore the key.

`ProviderError` carries `retryable`, and that flag is the whole retry policy:
`call_with_retry()` in the runtime backs off only when it is set.

## The Anthropic provider is capability-aware

One binding may point different roles at different model generations, so the
provider adapts the request to the model rather than making the user track which
parameter each family accepts:

- `thinking: auto` becomes adaptive thinking on families that support it, and is
  omitted entirely on ones that use the removed `budget_tokens` form
- `effort` is dropped where it is not accepted
- sampling parameters (`temperature`, `top_p`, `top_k`) are stripped for
  families that reject them

Unrecognised params pass through untouched, so a new API parameter is usable
from a binding file without a code change. The lists of affected families are
constants at the top of `anthropic_provider.py` and are the thing to edit when a
new model ships.

The provider always streams, because a large `max_tokens` otherwise trips the
SDK's HTTP timeout, and collects the final message.

## The pool

`ProviderPool` builds one instance per declared provider name, lazily, and keeps
it. Provider construction opens HTTP clients, so a long-lived daemon builds each
endpoint once; the daemon holds **one pool per distinct binding file** and closes
them all on shutdown. `ProviderPool` is an async context manager, which is how
`poieo run` and the learning pass use it.

## Two different checks

They are easy to confuse, and both exist:

- **`check_credentials(binding, roles)`** reads the environment and opens
  nothing. It runs at load time, for the roles a graph actually names — a spare
  endpoint bound to nothing is not going to be called, and holding the daemon
  down for its key would make the binding harder to keep than the flows it
  serves.
- **`poieo check` / `Provider.health()`** actually talks to each endpoint. That
  costs a network round trip, so it is a command the user runs, never something
  startup does.
