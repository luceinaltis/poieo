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

The one worth knowing about is how much a reasoning model thinks. `max_tokens`
bounds *everything the model emits*, thinking included, so a model that thinks
hard can spend the whole ceiling before it starts answering and come back cut
off mid-turn. A run measured here spent **194,037 output tokens over thirty-one
turns and was cut off anyway**, at three to seven minutes a turn.

```yaml
params:
  max_tokens: 24000
  reasoning: {max_tokens: 16000}
```

**This does not do what its name suggests, and the difference matters.** For a
model whose endpoint only takes an *effort* level — most of them — OpenRouter
converts the number into one by its share of `max_tokens`:

| share of `max_tokens` | effort |
|---|---|
| ~95% | `max` / `xhigh` |
| ~80% | `high` |
| ~50% | `medium` |
| ~20% | `low` |
| ~10% | `minimal` |

So `16000` against a ceiling of `24000` is 67% — it asks for **roughly medium
effort**, not for a 16,000-token cap on thinking. Measured on the same step
afterwards: output fell to **181 tokens a turn on average**, nowhere near the
number written down, and the run went from sixty-five minutes to seven. The
parameter selects a mode; it does not put a lid on one.

Written as an effort level (`reasoning: {effort: "medium"}`) it says the same
thing more honestly, and does not depend on a ratio to a second number. Use the
token form when the endpoint really does take a budget.

### What a run cost, from the endpoint rather than a table

`Usage` carries `cost` alongside the token counts, and `reasoning_tokens` beside
the output ones. Both come from the endpoint. OpenRouter reports them when the
request asks:

```yaml
params:
  usage: {include: true}
```

which reaches it through the same passthrough as everything else. The response
then carries what it actually billed:

```json
"usage": {"prompt_tokens": 14, "completion_tokens": 16, "cost": 5.05e-06,
          "completion_tokens_details": {"reasoning_tokens": 9}}
```

**`cost: None` is not zero.** Zero is a local model that really costs nothing;
`None` is an endpoint that was not asked or does not say. Anything that spends
against a budget has to tell those apart, or a backend that stays quiet reads as
free.

It is not sent by default, and that is deliberate: `usage` is an OpenRouter
extension, and adding an unrecognised key to every request would risk endpoints
that reject what they do not know.

**No price table lives here.** Prices change, a table would go stale in silence,
and it would be wrong in the direction nobody checks — the same reasoning that
kept a table of context windows out.

For an endpoint that bills and does not say so — Anthropic's API reports no cost
at all, and it is the paid backend these examples ship for — a binding can write
the rates down:

```yaml
default:
  provider: claude
  model: claude-opus-5
  prices: {input: 5.0, output: 25.0, cache_read: 0.5, cache_write: 6.25}
```

**Per million tokens**, because that is the unit every vendor quotes in: the
number in the binding is the number on the pricing page rather than one somebody
converted by hand and got wrong by six zeroes.

The endpoint's own figure still wins where there is one — the same two-tier shape
as `context`, and for the same reason. What an endpoint reports is a fact; what a
binding declares is somebody's belief; and a belief beats nothing.

Cached input is charged at the cache rate and **not** also at the input one.
`input_tokens` is the whole prompt and `cache_read_tokens` is the part of it that
was already there, so counting both would bill the cached half twice.

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
| `anthropic` | Claude, direct or through AWS Bedrock / Google Vertex | official SDK, always streams |
| `openai_compatible` | vLLM, SGLang, llama.cpp, LM Studio, TGI, OpenRouter, Azure, and the hosted endpoints that speak this shape | `POST {base_url}/chat/completions` |
| `ollama` | Ollama | `POST {base_url}/api/chat`; `max_tokens`/`temperature` fold into `options` |
| `mock` | nothing | scripted replies for tests and dry runs |

Each preset is registered as a type of its own, so a typo in one is a parse
error rather than a connection failure at three in the morning.

`ProviderSpec.type` is a plain `str` validated against `KNOWN_PROVIDER_TYPES`
rather than a closed `Literal`. That is what lets
`poieo.providers.register("my_type", MyProvider)` add a backend from outside the
package while a typo in a binding file is still rejected at parse time.
`base_url` is required for `openai_compatible` and `ollama`, and API keys are
read from the environment by name (`api_key_env`) — never stored in the file.

### Endpoints poieo knows the address of

```yaml
providers:
  groq: {type: groq}          # that is the whole declaration
```

Fourteen names, each an `openai_compatible` endpoint with its address and key
variable filled in: `openai`, `openrouter`, `groq`, `deepseek`, `together`,
`fireworks`, `mistral`, `xai`, `cerebras`, `nebius`, `moonshot`, `zai`,
`gemini`, `perplexity`.

None of them is a new way of talking — they all speak the same wire format the
`openai_compatible` type already did. What a preset saves is the part a person
gets wrong: there is no guessing `https://api.groq.com/openai/v1` from the
vendor's name, and neither `/v1` nor `/openai` alone reaches it.

**A preset is a starting point, not a cage.** A `base_url` or `api_key_env` in
the binding wins — somebody pointing at a proxy, a mirror or a gateway means it.

**And this table is safe in a way the ones this project refused are not.** A
stale price inflates a bill quietly; a stale context window truncates a
conversation quietly; **a stale address fails to connect, loudly, on the first
call.** Only tables that are wrong in silence are dangerous.

Every address was probed against the live endpoint when it was written. Two of
them are why that is worth saying: Gemini and Perplexity answer 404 on `/models`
and 400/401 on `/chat/completions`, so a check that only asked the first would
have called two correct addresses wrong.

### The same Claude, three counters

Companies reach Claude through Bedrock or Vertex because the billing and the
security review already run through the cloud account they have — many will not
register a card with Anthropic separately. It is the same model behind a
different counter, and the counter **signs its requests with AWS or Google
credentials** rather than taking an API key, which is why no header could have
bridged it.

```yaml
providers:
  claude:
    type: anthropic
    options: {through: bedrock, aws_region: us-east-1}

  # or
  claude:
    type: anthropic
    options: {through: vertex, region: us-east5, project_id: my-project}
```

`through` picks the client; everything else in `options` is handed to it, so a
region or a project goes where that SDK expects it. Credentials are **not**
named here — those clients resolve them the way boto3 and gcloud do, from the
environment or a profile.

Model ids differ at those counters (`anthropic.claude-sonnet-4-5-...-v1:0` on
Bedrock), and that is the binding's `model:` as usual.

**A `through` nobody has heard of is refused rather than ignored.** A typo would
otherwise send every request to Anthropic directly and bill the wrong account,
which is the kind of mistake noticed at the end of the month.

### Endpoints that speak the shape and none of the plumbing

`headers` and `query` go on every request, for an endpoint that wants its
credential or its version somewhere other than where OpenAI put them. Azure is
the one that needs both:

```yaml
providers:
  azure:
    type: openai_compatible
    base_url: https://my-resource.openai.azure.com/openai/deployments/gpt-4o
    api_key_env: AZURE_OPENAI_KEY     # still read from the environment
    headers: {api-key: "${AZURE_OPENAI_KEY}"}   # ...and Azure wants it here
    query: {api-version: "2024-10-21"}
```

`headers` is laid *over* what `api_key_env` built rather than replacing it, so
an endpoint that wants something extra need not restate the parts every
endpoint shares. **Values are literal**, so a key does not belong in them — the
rule the rest of this file exists to keep.

### Where the OpenAI shape is not one shape

OpenAI's own reasoning models (the o-series, GPT-5.x) **reject `max_tokens`**
and want `max_completion_tokens` instead. Nothing here needs changing for that:
`max_tokens` is only sent when a binding names it, and anything else in `params`
is passed through. So name the one that endpoint takes, and do not set the other:

```yaml
params: {max_completion_tokens: 24000}
```

A `max_tokens` inherited from `default` will still be sent, which is the trap —
a role on such a model has to override it away rather than merely not repeat it.

**Bedrock and Vertex are out of reach**, and not by an oversight that a header
would fix: they authenticate with SigV4 and with Google's own credentials, which
is a protocol rather than a field.

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
rest — so the smaller number is the only safe one to believe.

**A binding that claims more room than the endpoint gives is warned about, not
refused.** `poieo check` compares the two and says so:

```
warn builder          declares context: 1310720 but openrouter reports 1048576
                      for z-ai/glm-5.3-flash -- the conversation will be
                      cleared later than this endpoint allows
```

Said, never enforced, for three reasons and all three were measured. The
endpoint's answer can be **absent** — Ollama reports nothing for a model it has
not loaded. It can be **stale** — `num_ctx` is whatever the last request asked
for, and the next one can change it. And a daemon that will not start because a
local server happens to have a small model loaded is worse than one that warns.

It is also no longer the last line of defence: the runtime notices when an
endpoint keeps less than it was sent (`docs/runtime.md`), so a warning ignored
here becomes a visible event there rather than a silent corruption.

**The two answers keep for different lengths of time, and are cached
accordingly.** OpenRouter's is a property of a deployment and holds for the
process. Ollama's is "what is loaded right now", and a single request from any
client — poieo, or the editor somebody has open beside it — reloads the model at
a different size: measured, `num_ctx=16384` took 5.43s to load and the next
plain request took 3.91s to put 4,096 back. So that one is asked every time, and
being wrong about it is caught at runtime rather than prevented here. It is the second place the runtime looks: the binding's
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

**A pool survives an edit to the file it was built from**, and that is the point
of keying it by that file: the daemon re-reads a binding before every run (see
[daemon.md](daemon.md)) and hands the pool the new spec, without closing
anything. Nothing has to be closed, because nothing a pool holds can go stale.
It caches one client per provider *name*, built from that provider's own block,
and the model id never enters it — that travels per request. Moving a role
rewrites `default:`/`roles:` and leaves `providers:` alone; declaring an endpoint
only ever adds one. Neither supersedes a client already built.

What the pool does need is the spec itself, because `get()` looks a provider up
in it: a role pointed at an endpoint declared after startup would otherwise read
as undeclared. An edit that *changed* an existing provider's address or key would
be the third case, and there is no way to make one today — `rebind.declare()`
refuses to touch a provider already there.

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
