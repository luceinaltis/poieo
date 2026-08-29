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
`ResolvedModel` (`provider_name`, `provider`, `model`, `params`, `context`):

```
node params   >   roles[role]   >   default
```

`provider` and `model` take the first non-empty value; `params` merge key by key,
so a role that sets `temperature` keeps the default's `max_tokens`. A role with
no provider or no model after merging raises `BindingError` — never a silent
fallback, because "which model answered" must always have an answer.

**`context` is how much the model can hold, in tokens.** It sits beside `model`
rather than inside `params` because it describes the endpoint rather than asking
it for anything: in `params` it would be posted in the request body, where a
strict API rejects what it does not recognise.

It has no default, and that is deliberate. The models this project binds differ
by a factor of five — a local `qwen3.5` holds 262,144 tokens and
`z-ai/glm-5.3-flash` holds 1,310,720 — so any single number would be wrong for
most of them, and wrong while looking like a measurement. `None` means "nobody
has said", which is a different fact from any number and is left for the caller
to answer however it can.

### Params the provider has never heard of, on purpose

`params` is passed to the endpoint as it stands — `local.py` does
`payload.update(params)` after lifting `max_tokens` out, and the Anthropic
provider forwards what it does not recognise. A parameter a new API version
adds is usable from a binding without a code change here, which is deliberate.

The one worth knowing about is how a reasoning model divides its output budget.
`max_tokens` bounds *everything the model emits*, thinking included, so a model
that thinks hard can spend the whole ceiling before it starts answering and
come back cut off mid-turn. A run measured here spent **194,037 output tokens
over thirty-one turns and was cut off anyway**. OpenAI-shaped endpoints take:

```yaml
params:
  max_tokens: 24000
  reasoning: {max_tokens: 16000}   # thinking gets 16k; 8k is left to answer with
```

The reasoning budget has to leave room under `max_tokens`, or there is nothing
left to say the answer in. Raising `max_tokens` alone also works, and pays for
it with turns that are slower and cost more — measured at three to seven
minutes each on a model given 24,000 to think in.

### Two questions about roles, and why both exist

`resolve()` falls back to `default` for **any** role at all — that is the point
of having a default, and a mock binding declaring no roles is a legitimate way
to run a graph. Which means two different questions have to be asked separately:

| method | asks | answer used for |
|---|---|---|
| `check_roles(roles)` | which of these cannot be resolved **at all** | `preflight()` — a hard failure |
| `undeclared(roles)` | which of these the binding **never names** | `load_tasks()` — a warning |

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
Provider      complete()  ·  health()  ·  aclose()  ·  context_for()
```

`role` travels on the request for logging and for the mock's scripting, and is
never sent to a backend. `meta` carries anything provider-specific worth keeping
— notably `raw_content`, the provider's own content blocks, which the agent loop
replays verbatim on the next turn so thinking blocks and their signatures
survive a tool round trip. Other providers ignore the key.

`context_for(model)` answers how many tokens that model can hold **where it is
actually running**, and the base class answers `None` — so a backend that cannot
say inherits the right answer and writes nothing.

*Where it is actually running* is the whole difficulty. Both endpoints publish
two numbers and only one of them is enforced:

| endpoint | what the model can do | what will be allowed |
|---|---|---|
| OpenRouter | `context_length` 1,310,720 | `top_provider.context_length` 1,048,576 |
| Ollama | `/api/show` → 262,144 | `/api/ps` → **4,096** |

Forty of OpenRouter's models disagree with themselves like this. Ollama's gap is
sixty-four fold, because `/api/show` describes the file on disk and the server
loads it with whatever `num_ctx` it was told. **Nothing announces the
difference** — an endpoint asked to hold more than it loaded simply drops the
rest — so the smaller number is the only safe one to believe. It is the second place the runtime looks: the binding's
`context:` is the first, because somebody who wrote the number down meant it.
Implementations cache; a window does not change while a process runs, and this
must not become a round trip per turn. An endpoint that will not answer is not
a failure — asking is an optimisation, and the character caps take over.

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
  down for its key would make the binding harder to keep than the tasks it
  serves.
- **`poieo check` / `Provider.health()`** actually talks to each endpoint. That
  costs a network round trip, so it is a command the user runs, never something
  startup does.
