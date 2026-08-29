import asyncio

import pytest

from conftest import EXAMPLES
from poieo.binding import BindingSpec, load_binding
from poieo.graph import GraphSpec, load_graph
from poieo.providers import ProviderPool
from poieo.runtime.executor import execute, preflight
from poieo.store import NullStore
from poieo.errors import BindingError, SpecError


def mock_binding(responses, fallback=""):
    return BindingSpec.model_validate(
        {
            "name": "test",
            "providers": {
                "fake": {
                    "type": "mock",
                    "options": {"responses": responses, "fallback": fallback},
                }
            },
            "default": {"provider": "fake", "model": "mock-model"},
        }
    )


async def run_graph(graph, binding, **kwargs):
    store = kwargs.pop("store", None) or NullStore()
    async with ProviderPool(binding) as pool:
        return await execute(graph, binding, pool, store, **kwargs)


async def test_router_picks_the_matching_arm():
    graph = load_graph(EXAMPLES / "tasks/support-triage.graph.yaml")
    binding = mock_binding({"classifier": "feature", "writer": "ack"})
    result = await run_graph(graph, binding, input={"message": "please add dark mode"})

    assert result.status == "completed"
    assert result.path == ["classify", "route", "draft_feature"]
    assert result.outputs["draft_feature"] == "ack"


async def test_router_falls_through_to_default():
    graph = load_graph(EXAMPLES / "tasks/support-triage.graph.yaml")
    binding = mock_binding({"classifier": "question", "writer": "answer"})
    result = await run_graph(graph, binding, input={"message": "how do I log in?"})
    assert result.path[-1] == "draft_answer"


async def test_cycle_exits_when_the_critic_approves():
    graph = load_graph(EXAMPLES / "tasks/draft-review.graph.yaml")
    binding = mock_binding(
        {
            "writer": ["first draft", "revised draft"],
            "critic": ['{"approved": false, "feedback": "limp"}', '{"approved": true}'],
        }
    )
    result = await run_graph(graph, binding, input={"brief": "b"})

    assert result.status == "completed"
    assert result.path == ["draft", "review", "gate", "revise", "review", "gate"]
    assert result.state["latest_draft"] == "revised draft"


async def test_cycle_gives_up_after_two_revisions():
    graph = load_graph(EXAMPLES / "tasks/draft-review.graph.yaml")
    binding = mock_binding(
        {"writer": ["d"], "critic": ['{"approved": false, "feedback": "no"}']}
    )
    result = await run_graph(graph, binding, input={"brief": "b"})

    assert result.status == "completed"
    assert result.path.count("revise") == 2
    assert result.outputs["gate"] == "gave-up"


async def test_max_steps_aborts_a_runaway_graph():
    graph = GraphSpec.model_validate(
        {
            "name": "spin",
            "entry": "a",
            "max_steps": 5,
            "nodes": [{"id": "a", "type": "agent", "prompt": "go", "next": "a"}],
        }
    )
    result = await run_graph(graph, mock_binding({"*": "x"}))

    assert result.status == "aborted"
    assert "max_steps" in result.error
    assert result.steps == 5


async def test_json_output_survives_a_markdown_fence():
    graph = GraphSpec.model_validate(
        {
            "name": "j",
            "entry": "a",
            "nodes": [
                {
                    "id": "a",
                    "type": "agent",
                    "prompt": "go",
                    "output": {"format": "json", "path": "result.score"},
                }
            ],
        }
    )
    binding = mock_binding({"*": '```json\n{"result": {"score": 7}}\n```'})
    result = await run_graph(graph, binding)
    assert result.outputs["a"] == 7


async def test_bad_json_output_fails_the_run():
    graph = GraphSpec.model_validate(
        {
            "name": "j",
            "entry": "a",
            "nodes": [
                {"id": "a", "type": "agent", "prompt": "go", "output": {"format": "json"}}
            ],
        }
    )
    result = await run_graph(graph, mock_binding({"*": "not json at all"}))
    assert result.status == "failed"
    assert "expected JSON" in result.error


async def test_state_carries_into_the_next_run():
    graph = load_graph(EXAMPLES / "tasks/draft-review.graph.yaml")
    binding = mock_binding(
        {"writer": ["d"], "critic": ['{"approved": true, "feedback": "ok"}']}
    )
    first = await run_graph(graph, binding, input={"brief": "b"})
    second = await run_graph(
        graph, binding, input={"brief": "b"}, state=first.state, iteration=1
    )
    assert second.iteration == 1
    assert second.status == "completed"


async def test_prompt_sees_the_run_payload():
    graph = GraphSpec.model_validate(
        {
            "name": "p",
            "entry": "a",
            "nodes": [{"id": "a", "type": "agent", "prompt": "Hello {{ input.who }}"}],
        }
    )
    binding = mock_binding({"*": "hi"})
    async with ProviderPool(binding) as pool:
        await execute(graph, binding, pool, NullStore(), input={"who": "world"})
        sent = pool.get("fake").calls[0]
    assert sent.messages[0]["content"] == "Hello world"


def test_preflight_rejects_an_incomplete_binding():
    graph = load_graph(EXAMPLES / "tasks/support-triage.graph.yaml")
    binding = BindingSpec.model_validate({"providers": {"p": {"type": "mock"}}})
    with pytest.raises(BindingError, match="cannot resolve role"):
        preflight(graph, binding)


class _FlakyProvider:
    """Fails `failures` times with a retryable error, then succeeds."""

    instances: dict[str, "_FlakyProvider"] = {}

    def __init__(self, name, spec):
        self.name = name
        self.spec = spec
        self.remaining = spec.options.get("failures", 0)
        self.attempts = 0
        _FlakyProvider.instances[name] = self

    async def complete(self, request):
        from poieo.errors import ProviderError
        from poieo.providers.base import LLMResponse

        self.attempts += 1
        if self.remaining > 0:
            self.remaining -= 1
            raise ProviderError("temporarily overloaded", provider=self.name, retryable=True)
        return LLMResponse(text="recovered", model=request.model)

    async def context_for(self, model):
        # A stub stands in for a real provider, and a real one inherits this
        # from `Provider` rather than writing it.
        return None

    async def health(self):
        return True, "flaky"

    async def aclose(self):
        return


def flaky_binding(failures):
    from poieo.providers import register

    register("flaky", _FlakyProvider)
    return BindingSpec.model_validate(
        {
            "providers": {"f": {"type": "flaky", "options": {"failures": failures}}},
            "default": {"provider": "f", "model": "m"},
        }
    )


def retry_graph(attempts):
    return GraphSpec.model_validate(
        {
            "name": "r",
            "entry": "a",
            "nodes": [
                {
                    "id": "a",
                    "type": "agent",
                    "prompt": "go",
                    "retry": {"attempts": attempts, "backoff": 0},
                }
            ],
        }
    )


async def test_a_retryable_failure_is_retried():
    result = await run_graph(retry_graph(3), flaky_binding(failures=2))
    assert result.status == "completed"
    assert result.outputs["a"] == "recovered"
    assert _FlakyProvider.instances["f"].attempts == 3


async def test_retries_stop_at_the_configured_limit():
    result = await run_graph(retry_graph(2), flaky_binding(failures=5))
    assert result.status == "failed"
    assert "after 2 attempt(s)" in result.error


async def test_a_failed_run_still_reports_the_path_it_took():
    result = await run_graph(retry_graph(1), flaky_binding(failures=1))
    assert result.status == "failed"
    assert result.path == ["a"]
    assert result.finished_at >= result.started_at


def agent_graph(workdir, **node_overrides):
    node = {
        "id": "work",
        "type": "agent",
        "role": "worker",
        "workdir": str(workdir),
        "prompt": "do it",
        "tools": ["files", "shell"],
        "output": {"as": "report"},
    }
    node.update(node_overrides)
    return GraphSpec.model_validate({"name": "ag", "entry": "work", "nodes": [node]})


async def test_agent_node_runs_tools_and_finishes(tmp_path):
    (tmp_path / "notes.txt").write_text("secret-content")
    graph = agent_graph(tmp_path)
    binding = mock_binding(
        {
            "worker": [
                {"tool_calls": [{"name": "read_file", "arguments": {"path": "notes.txt"}}]},
                "done",
            ]
        }
    )
    async with ProviderPool(binding) as pool:
        result = await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    assert result.status == "completed"
    assert result.outputs["work"] == "done"
    # The second model call must carry the tool result back.
    second_call = provider.calls[1]
    tool_turns = [m for m in second_call.messages if m["role"] == "tool"]
    assert tool_turns and "secret-content" in tool_turns[0]["content"]
    assert second_call.messages[-2]["role"] == "assistant"


async def test_agent_node_survives_tool_errors(tmp_path):
    graph = agent_graph(tmp_path)
    binding = mock_binding(
        {
            "worker": [
                {"tool_calls": [{"name": "read_file", "arguments": {"path": "missing"}}]},
                "recovered",
            ]
        }
    )
    result = await run_graph(graph, binding)
    assert result.status == "completed"
    assert result.outputs["work"] == "recovered"


async def test_a_broken_workdir_expression_fails_in_the_nodes_voice(tmp_path):
    """A workdir template is a template like the prompt and the system block.

    All three are rendered inside the node's own error wrap, so a typo in
    any of them reads the same way in a run log rather than escaping as a
    bare ExpressionError.
    """
    graph = agent_graph("{{ nowhere.at.all }}")
    result = await run_graph(graph, mock_binding({"worker": "done"}))

    assert result.status == "failed"
    assert "node 'work': unknown name 'nowhere'" in (result.error or "")
    # Not folder_gone: the template never got as far as naming a folder,
    # and a run log that said otherwise would send the reader after mkdir.
    assert (result.cause or {}).get("slug") == "bad_expression"


async def test_agent_node_stops_at_max_turns(tmp_path):
    graph = agent_graph(tmp_path, max_turns=3)
    # The script's last entry repeats forever, so the model never finishes.
    binding = mock_binding(
        {"worker": [{"tool_calls": [{"name": "list_dir", "arguments": {}}]}]}
    )
    result = await run_graph(graph, binding)
    assert result.status == "failed"
    assert "max_turns" in result.error


async def test_agent_node_refuses_a_turn_the_model_was_cut_off_mid(tmp_path):
    """A turn that ran out of output budget is not an answer.

    The loop ends on a turn with no tool calls, and a truncated turn has none
    -- so half a sentence became the node's output and the run reported
    success. Watched in the wild: a step that had read twenty files ended on
    "Let me search with different quoting", and everything downstream treated
    that as the finished work.

    The provider says so plainly, and poieo already carries it: OpenAI-shaped
    endpoints return `finish_reason: length`, Anthropic `max_tokens`. Nothing
    was reading it.
    """
    graph = agent_graph(tmp_path, max_turns=3)
    binding = mock_binding(
        {"worker": [{"text": "Let me search with different quoting.",
                     "stop_reason": "length"}]}
    )

    result = await run_graph(graph, binding)

    assert result.status == "failed"
    assert "cut off" in result.error


async def test_agent_node_accepts_a_turn_that_simply_ended(tmp_path):
    """The other side of it: a model that finished still finishes."""
    graph = agent_graph(tmp_path, max_turns=3)
    binding = mock_binding({"worker": "all done"})

    result = await run_graph(graph, binding)

    assert result.status == "completed"


def reads_the_same_file(times, path="big.txt"):
    """A model that reads one file over and over, then answers.

    The shape a step takes when it is looking around a repository, which is
    what fills a conversation up in the first place.
    """
    turn = {"tool_calls": [{"name": "read_file", "arguments": {"path": path}}]}
    return mock_binding({"worker": [dict(turn) for _ in range(times)] + ["done"]})


def numbered(line):
    """What `read_file` gives back for a one-line file: it numbers its lines."""
    return f"1	{line}"


def tool_contents(call):
    return [m["content"] for m in call.messages if m["role"] == "tool"]


def sized_binding(responses, context):
    """A binding whose model says how much it can hold."""
    return BindingSpec.model_validate(
        {
            "name": "test",
            "providers": {"fake": {"type": "mock", "options": {"responses": responses}}},
            "default": {"provider": "fake", "model": "mock-model", "context": context},
        }
    )


async def test_a_model_that_can_hold_more_is_not_emptied_as_early(tmp_path):
    """The cap the binding knows about beats the one the module guessed.

    Measured, a hardcoded 120,000 characters is 2.3% of what
    `z-ai/glm-5.3-flash` holds. A step was watched re-reading the same file
    eight times because its history was being emptied at a fortieth of what
    the model could carry -- so the trigger has to know the model.
    """
    (tmp_path / "big.txt").write_text("x" * 4_000)
    graph = agent_graph(tmp_path)
    script = {"worker": [{"tool_calls": [{"name": "read_file", "arguments": {"path": "big.txt"}}]}] * 6 + ["done"]}

    # Small window: the same conversation is over the line and gets cleared.
    async with ProviderPool(small := sized_binding(script, context=4_000)) as pool:
        cramped = _CapturingStore()
        await execute(graph, small, pool, cramped)

    # Large window: nothing is thrown away, because nothing needed to be.
    async with ProviderPool(roomy := sized_binding(script, context=10_000_000)) as pool:
        spacious = _CapturingStore()
        await execute(graph, roomy, pool, spacious)

    assert [e for e in cramped.events if e.type == "node_context_cleared"]
    assert not [e for e in spacious.events if e.type == "node_context_cleared"]


async def test_without_a_declared_window_the_old_cap_still_holds(tmp_path, monkeypatch):
    """A binding that says nothing must behave exactly as it did.

    `None` is not zero and not infinity -- it means nobody has said, and the
    character cap is what this loop did before anyone could.
    """
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 400)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()
    await run_graph(graph, reads_the_same_file(5), store=store)

    assert [e for e in store.events if e.type == "node_context_cleared"]


class _KnowsItsSize:
    """A provider that publishes a window, and counts how often it is asked."""

    instances: dict[str, "_KnowsItsSize"] = {}

    def __init__(self, name, spec):
        from poieo.providers.mock import MockProvider

        self.inner = MockProvider(name, spec)
        self.window = spec.options.get("window")
        self.asked = 0
        _KnowsItsSize.instances[name] = self

    async def complete(self, request):
        return await self.inner.complete(request)

    async def context_for(self, model):
        self.asked += 1
        return self.window

    async def health(self):
        return True, "sized"

    async def aclose(self):
        return


def sized_provider_binding(responses, window, context=None):
    from poieo.providers import register

    register("sized", _KnowsItsSize)
    default = {"provider": "s", "model": "m"}
    if context:
        default["context"] = context
    return BindingSpec.model_validate(
        {
            "providers": {
                "s": {"type": "sized", "options": {"responses": responses, "window": window}}
            },
            "default": default,
        }
    )


async def test_a_provider_is_asked_when_the_binding_has_not_said(tmp_path):
    """Nobody should have to look a number up that the endpoint publishes."""
    (tmp_path / "big.txt").write_text("x" * 4_000)
    graph = agent_graph(tmp_path)
    script = {"worker": [{"tool_calls": [{"name": "read_file", "arguments": {"path": "big.txt"}}]}] * 6 + ["done"]}

    binding = sized_provider_binding(script, window=10_000_000)
    store = _CapturingStore()
    await run_graph(graph, binding, store=store)

    assert _KnowsItsSize.instances["s"].asked >= 1
    # A window that large leaves nothing to clear, which is the point.
    assert not [e for e in store.events if e.type == "node_context_cleared"]


async def test_the_binding_is_not_second_guessed(tmp_path):
    """Someone who wrote the number down meant it -- a smaller real window, a
    deliberately tighter budget. The endpoint is the fallback, not the truth."""
    (tmp_path / "big.txt").write_text("x" * 4_000)
    graph = agent_graph(tmp_path)
    script = {"worker": [{"tool_calls": [{"name": "read_file", "arguments": {"path": "big.txt"}}]}] * 6 + ["done"]}

    binding = sized_provider_binding(script, window=10_000_000, context=4_000)
    store = _CapturingStore()
    await run_graph(graph, binding, store=store)

    assert _KnowsItsSize.instances["s"].asked == 0
    assert [e for e in store.events if e.type == "node_context_cleared"]


class _RefusesOnce:
    """Refuses the first call the way an endpoint refuses an oversized one.

    Non-retryable, because that is what a 400 is: sending the same bytes again
    buys the same answer. Only something *smaller* has a chance.
    """

    instances: dict[str, "_RefusesOnce"] = {}

    def __init__(self, name, spec):
        from poieo.providers.mock import MockProvider

        self.inner = MockProvider(name, spec)
        # Which call to start refusing on. A real endpoint takes the small
        # requests and refuses once the conversation has grown, so refusing
        # from the first call would be a different test.
        self.refuse_from = spec.options.get("refuse_from", 1)
        self.refusals = spec.options.get("refusals", 1)
        self.calls = 0
        _RefusesOnce.instances[name] = self

    async def complete(self, request):
        self.calls += 1
        if self.calls >= self.refuse_from and self.refusals > 0:
            self.refusals -= 1
            from poieo.errors import ProviderError

            raise ProviderError(
                "maximum context length exceeded", provider="x", retryable=False
            )
        return await self.inner.complete(request)

    async def context_for(self, model):
        return None

    async def health(self):
        return True, "refuses"

    async def aclose(self):
        return


def refusing_binding(responses, refusals=1, refuse_from=1):
    from poieo.providers import register

    register("refuses", _RefusesOnce)
    return BindingSpec.model_validate(
        {
            "providers": {
                "r": {
                    "type": "refuses",
                    "options": {
                        "responses": responses,
                        "refusals": refusals,
                        "refuse_from": refuse_from,
                    },
                }
            },
            "default": {"provider": "r", "model": "m"},
        }
    )


async def test_a_refused_request_goes_again_smaller(tmp_path, monkeypatch):
    """An endpoint that says no to a size is telling us something we could not
    have measured. Sending the same bytes again buys the same answer; only
    something smaller has a chance."""
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)  # keep clearing out of it
    (tmp_path / "big.txt").write_text("x" * 4_000)
    graph = agent_graph(tmp_path)
    script = {
        "worker": [{"tool_calls": [{"name": "read_file", "arguments": {"path": "big.txt"}}]}] * 5
        + ["done"]
    }
    store = _CapturingStore()

    # Refused on the fifth call, by which point four tool results have piled
    # up and one of them is old enough to drop.
    result = await run_graph(
        graph, refusing_binding(script, refusals=1, refuse_from=5), store=store
    )

    assert result.status == "completed", result.error
    assert [e for e in store.events if e.type == "node_retried_smaller"]


async def test_it_only_goes_again_once(tmp_path, monkeypatch):
    """Otherwise a genuinely broken request is paid for over and over."""
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    (tmp_path / "big.txt").write_text("x" * 4_000)
    graph = agent_graph(tmp_path)
    script = {
        "worker": [{"tool_calls": [{"name": "read_file", "arguments": {"path": "big.txt"}}]}] * 5
        + ["done"]
    }

    result = await run_graph(graph, refusing_binding(script, refusals=99, refuse_from=5))

    assert result.status == "failed"
    # One turn's worth of calls, plus the one retry. Not a loop.
    assert _RefusesOnce.instances["r"].calls <= 8


async def test_nothing_to_clear_means_nothing_to_retry(tmp_path, monkeypatch):
    """A refusal on the first turn is not about size -- there is only the
    prompt. Trying again would buy the same answer a second time."""
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()

    result = await run_graph(graph, refusing_binding({"worker": ["done"]}, refusals=1), store=store)

    assert result.status == "failed"
    assert _RefusesOnce.instances["r"].calls == 1
    assert not [e for e in store.events if e.type == "node_retried_smaller"]


class _QuietlyTruncates:
    """Reports having read less than it was sent, and says nothing about it.

    Measured against a real Ollama at num_ctx 4096: sending 45,000 characters
    after 18,000 made `prompt_eval_count` *fall* from 4,010 to 2,050. No error,
    no flag -- the model just answers from a conversation with its beginning
    missing.
    """

    instances: dict[str, "_QuietlyTruncates"] = {}

    def __init__(self, name, spec):
        from poieo.providers.mock import MockProvider

        self.inner = MockProvider(name, spec)
        self.ceiling = spec.options.get("ceiling", 0)
        _QuietlyTruncates.instances[name] = self

    async def complete(self, request):
        from poieo.providers.base import Usage

        response = await self.inner.complete(request)
        if self.ceiling and response.usage.input_tokens > self.ceiling:
            response.usage = Usage(
                input_tokens=self.ceiling // 2,   # what Ollama actually does
                output_tokens=response.usage.output_tokens,
            )
        return response

    async def context_for(self, model):
        return None

    async def health(self):
        return True, "truncates"

    async def aclose(self):
        return


def truncating_binding(responses, ceiling):
    from poieo.providers import register

    register("truncates", _QuietlyTruncates)
    return BindingSpec.model_validate(
        {
            "providers": {
                "t": {
                    "type": "truncates",
                    "options": {"responses": responses, "ceiling": ceiling},
                }
            },
            "default": {"provider": "t", "model": "m"},
        }
    )


def reading_script(times, path="big.txt"):
    turn = {"tool_calls": [{"name": "read_file", "arguments": {"path": path}}]}
    return {"worker": [dict(turn) for _ in range(times)] + ["done"]}


async def test_an_endpoint_that_drops_our_conversation_is_noticed(tmp_path, monkeypatch):
    """The conversation only ever grows, so the count the endpoint reports for
    it must grow too. When it does not, the endpoint kept less than we sent --
    and no estimate was needed to work that out."""
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    (tmp_path / "big.txt").write_text("x" * 4_000)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()

    await run_graph(graph, truncating_binding(reading_script(6), ceiling=1_500), store=store)

    dropped = [e for e in store.events if e.type == "node_input_dropped"]
    assert dropped
    assert dropped[0].data["kept"] < dropped[0].data["before"]


async def test_a_turn_that_cleared_is_expected_to_shrink(tmp_path, monkeypatch):
    """Clearing makes the count fall on purpose. Reading that as the endpoint
    dropping something would cry wolf on the loop's own housekeeping."""
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 400)
    (tmp_path / "big.txt").write_text("x" * 4_000)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()

    await run_graph(graph, mock_binding(reading_script(6)), store=store)

    assert [e for e in store.events if e.type == "node_context_cleared"]
    assert not [e for e in store.events if e.type == "node_input_dropped"]


async def test_a_provider_that_counts_nothing_is_not_accused(tmp_path, monkeypatch):
    """No measurement and a bad measurement are different facts. A backend
    that reports zero has not told us anything, and zero is not a fall."""
    from poieo.runtime import nodes
    from poieo.providers.base import Usage
    from poieo.providers.mock import MockProvider

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    real = MockProvider.complete

    async def silent(self, request):
        response = await real(self, request)
        response.usage = Usage(input_tokens=0, output_tokens=1)
        return response

    monkeypatch.setattr(MockProvider, "complete", silent)
    (tmp_path / "big.txt").write_text("x" * 4_000)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()

    await run_graph(graph, mock_binding(reading_script(6)), store=store)

    assert not [e for e in store.events if e.type == "node_input_dropped"]


async def test_a_result_too_large_to_fit_is_replaced_with_what_to_do(tmp_path, monkeypatch):
    """The case clearing cannot reach.

    `_clear_old_results` always keeps the most recent few, so a single file
    bigger than the whole window survives every clearing and every retry. Once
    we know it did not fit, saying so beats failing -- and `read_file` has
    taken `offset` and `limit` since #178, which the model has never once used.
    """
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    (tmp_path / "huge.txt").write_text("x" * 40_000)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()

    await run_graph(
        graph,
        truncating_binding(reading_script(6, path="huge.txt"), ceiling=1_500),
        store=store,
    )

    said = [e for e in store.events if e.type == "node_input_dropped"]
    assert said
    # And the model is told, in the result's own place, what to do instead.
    assert any("offset" in str(e.data.get("note", "")) for e in said)


class _VerboseSummariser:
    """Answers the summarising call with more than it was given.

    The summarising call is the one made with no tools, which is how every
    other test here identifies it too. Scripting it through the mock is not
    possible: both it and the agent's turns resolve to the same role.
    """

    def __init__(self, name, spec):
        from poieo.providers.mock import MockProvider

        self.inner = MockProvider(name, spec)

    async def complete(self, request):
        if not request.tools:
            from poieo.providers.base import LLMResponse, Usage

            return LLMResponse(
                text="y" * 200_000,
                model=request.model,
                usage=Usage(input_tokens=1, output_tokens=1),
            )
        return await self.inner.complete(request)

    async def context_for(self, model):
        return None

    async def health(self):
        return True, "verbose"

    async def aclose(self):
        return


def verbose_summariser_binding(responses):
    from poieo.providers import register

    register("verbose", _VerboseSummariser)
    return BindingSpec.model_validate(
        {
            "providers": {"v": {"type": "verbose", "options": {"responses": responses}}},
            "default": {"provider": "v", "model": "m"},
        }
    )


async def test_a_fold_that_would_make_it_bigger_is_not_taken(tmp_path, monkeypatch):
    """Watched in the wild, in another harness: a compression pass took a
    conversation from 64,186 tokens to 71,173 -- fourteen messages in,
    fourteen out, seven thousand tokens larger. Rebuilding is not shrinking,
    and a summary longer than what it replaced is not a summary.
    """
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    monkeypatch.setattr(nodes, "_COMPACT_CAP", 400)
    monkeypatch.setattr(nodes, "_FOLD_AT_LEAST", 100)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    reads = {"tool_calls": [{"name": "read_file", "arguments": {"path": "big.txt"}}]}
    store = _CapturingStore()

    result = await run_graph(
        graph,
        verbose_summariser_binding({"worker": [dict(reads) for _ in range(8)] + ["done"]}),
        store=store,
    )

    assert result.status == "completed", result.error
    assert not [e for e in store.events if e.type == "node_compacted"]
    said = [e for e in store.events if e.type == "node_compact_failed"]
    assert said and "longer" in said[0].data["error"]


async def test_what_a_fold_freed_is_never_negative(tmp_path, monkeypatch):
    """The number reaches the board. A fold that grew the conversation used to
    put a negative there and call it progress."""
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    monkeypatch.setattr(nodes, "_COMPACT_CAP", 400)
    monkeypatch.setattr(nodes, "_FOLD_AT_LEAST", 100)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    reads = {"tool_calls": [{"name": "read_file", "arguments": {"path": "big.txt"}}]}
    store = _CapturingStore()

    await run_graph(
        graph,
        verbose_summariser_binding({"worker": [dict(reads) for _ in range(8)] + ["done"]}),
        store=store,
    )

    assert all(e.data["folded"] > 0 for e in store.events if e.type == "node_compacted")


async def test_a_turn_says_how_big_it_was(tmp_path):
    """A run reports one usage total for the whole of itself, which cannot
    answer the question that keeps coming up: does a model write more as the
    conversation it is reading grows?

    Two runs measured here disagreed by ninety times on output -- 2,165 tokens
    against 194,037 -- but they also differed in whether the step was working
    or thrashing, so neither says which caused which. Telling those apart
    needs the two numbers turn by turn, inside one run, and nothing recorded
    them.
    """
    (tmp_path / "big.txt").write_text("x" * 4_000)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()

    await run_graph(graph, reads_the_same_file(4), store=store)

    turns = [e for e in store.events if e.type == "node_turn"]
    assert len(turns) > 2
    assert all(t.data["input_tokens"] > 0 for t in turns)
    # And the conversation grows, so the input does too -- which is the shape
    # the question is about.
    sizes = [t.data["input_tokens"] for t in turns]
    assert sizes == sorted(sizes)


async def test_a_conversation_under_the_cap_is_sent_whole(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    async with ProviderPool(binding := reads_the_same_file(4)) as pool:
        result = await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    assert result.status == "completed"
    # Four reads of a hundred characters is nowhere near the cap, so every
    # result is still there in full on the last request.
    assert tool_contents(provider.calls[-1]) == [numbered("x" * 100)] * 4


async def test_an_overgrown_conversation_loses_its_oldest_tool_results(tmp_path, monkeypatch):
    """The fix for a run that spent 160,360 input tokens to produce 6,578.

    Tool results are what fill a conversation -- one file read can be tens of
    thousands of characters -- and the loop resends all of them every turn.
    Past a cap the older ones are replaced by a note saying so; the file is
    still on disk, so the model can read it again if it turns out to need it.
    """
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 400)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    async with ProviderPool(binding := reads_the_same_file(5)) as pool:
        result = await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    assert result.status == "completed"
    sent = tool_contents(provider.calls[-1])
    assert len(sent) == 5
    # The two oldest are gone; the three most recent are whole.
    assert sent[0] == nodes._CLEARED
    assert sent[1] == nodes._CLEARED
    assert sent[2:] == [numbered("x" * 100)] * 3


async def test_clearing_keeps_the_record_that_the_tool_was_called(tmp_path, monkeypatch):
    """What the model must not lose is that it already looked.

    Only the result goes. The assistant turn that asked for it stays, so a
    model reading its own history still knows it has read this file -- and the
    tool definitions are re-offered every turn either way, so the ability to
    read it again never goes anywhere.
    """
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 400)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    async with ProviderPool(binding := reads_the_same_file(5)) as pool:
        await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    last = provider.calls[-1]
    asked = [m for m in last.messages if m["role"] == "assistant" and m.get("tool_calls")]
    assert len(asked) == 5
    assert all(c[0]["name"] == "read_file" for c in (m["tool_calls"] for m in asked))
    # And the task itself is never touched.
    assert last.messages[0] == {"role": "user", "content": "do it"}


async def test_clearing_says_so_in_the_run_log(tmp_path, monkeypatch):
    """A run that quietly shrinks its own history is a run nobody can debug."""
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 400)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()
    await run_graph(graph, reads_the_same_file(5), store=store)

    cleared = [e for e in store.events if e.type == "node_context_cleared"]
    assert cleared, "clearing the conversation must leave a trace"
    assert cleared[0].data["kept"] == nodes._KEEP_RESULTS
    # Net, not gross: the note takes the result's place, so what a hundred
    # characters actually bought back is a hundred less the note.
    assert cleared[0].data["freed"] == len(numbered("x" * 100)) - len(nodes._CLEARED)


async def test_a_result_is_only_cleared_once(tmp_path, monkeypatch):
    """Freed characters are a measurement, not a running total of intent.

    Once a result is a placeholder there is nothing left in it to free, and
    counting it again would report work that did not happen.
    """
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 400)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()
    await run_graph(graph, reads_the_same_file(6), store=store)

    cleared = [e for e in store.events if e.type == "node_context_cleared"]
    # Every firing freed something; a firing that found only placeholders
    # older than the keep window emits nothing at all.
    assert all(e.data["freed"] > 0 for e in cleared)


def summarizing(call):
    """The compaction call is the one made without tools.

    An agent turn is always offered the node's toolset, so nothing else in the
    loop asks the model anything with an empty `tools`.
    """
    return not call.tools


async def test_a_conversation_under_the_second_cap_is_never_summarized(tmp_path, monkeypatch):
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 400)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    async with ProviderPool(binding := reads_the_same_file(6)) as pool:
        result = await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    assert result.status == "completed"
    # Clearing is cheap and fires often; summarizing costs a model call and
    # loses what it does not keep, so it must not fire until it has to.
    assert not any(summarizing(c) for c in provider.calls)


async def test_an_overgrown_conversation_folds_its_older_turns_into_a_summary(
    tmp_path, monkeypatch
):
    """Clearing empties tool results; the turns themselves still pile up.

    A model's own reasoning and its tool call arguments survive a clearing --
    a `write_file` carries a whole file body in them -- so past a second, much
    higher cap the older turns are folded into one summary and the task keeps
    going from there.
    """
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)  # clearing out of the way
    monkeypatch.setattr(nodes, "_COMPACT_CAP", 400)
    monkeypatch.setattr(nodes, "_FOLD_AT_LEAST", 100)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    async with ProviderPool(binding := reads_the_same_file(8)) as pool:
        result = await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    assert result.status == "completed"
    folded = [c for c in provider.calls if summarizing(c)]
    assert folded, "past the second cap the older turns must be folded"
    # The task itself is never folded away: it is the whole of what the step
    # is for, and a summary of it is not it.
    after = next(c for c in provider.calls if c.tools and c.messages[0]["content"] != "do it")
    assert after.messages[0]["content"].startswith("do it")


async def test_a_summary_never_leaves_a_tool_result_without_its_call(tmp_path, monkeypatch):
    """The one way this breaks that a provider will not forgive.

    A tool result answers a call, and the two are a pair. Cutting the history
    anywhere but a turn boundary leaves a result whose call is gone, and both
    APIs reject that outright -- so the tail after a fold always starts with
    the model speaking, never with an answer to nobody.
    """
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    monkeypatch.setattr(nodes, "_COMPACT_CAP", 400)
    monkeypatch.setattr(nodes, "_FOLD_AT_LEAST", 100)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    async with ProviderPool(binding := reads_the_same_file(8)) as pool:
        await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    for call in provider.calls:
        seen: set[str] = set()
        for message in call.messages:
            for made in message.get("tool_calls") or []:
                seen.add(made["id"])
            if message["role"] == "tool":
                assert message["tool_call_id"] in seen, "a result outlived its call"


async def test_a_summary_that_cannot_be_written_does_not_end_the_run(tmp_path, monkeypatch):
    """A step is not worth losing over the machinery meant to save it."""
    from poieo.errors import ProviderError
    from poieo.providers.mock import MockProvider
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    monkeypatch.setattr(nodes, "_COMPACT_CAP", 400)
    monkeypatch.setattr(nodes, "_FOLD_AT_LEAST", 100)
    real = MockProvider.complete

    async def refuse_to_summarize(self, request):
        if not request.tools:
            raise ProviderError("the summarizer is down", provider="fake", retryable=False)
        return await real(self, request)

    monkeypatch.setattr(MockProvider, "complete", refuse_to_summarize)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()
    result = await run_graph(graph, reads_the_same_file(8), store=store)

    assert result.status == "completed", result.error
    # Loudly, though: the run log has to say the history was left whole.
    assert [e for e in store.events if e.type == "node_compact_failed"]


async def test_a_fold_that_would_reclaim_little_is_not_worth_the_call(tmp_path, monkeypatch):
    """Otherwise it fires on every turn once it has fired once.

    A fold leaves exactly `_KEEP_TURNS` turns behind it, so the very next turn
    is one over the line again -- and folding that single turn away would cost
    another whole model call. The floor is what stops the loop paying for a
    summary of nothing, over and over.
    """
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    monkeypatch.setattr(nodes, "_COMPACT_CAP", 400)
    monkeypatch.setattr(nodes, "_FOLD_AT_LEAST", 10_000_000)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    async with ProviderPool(binding := reads_the_same_file(8)) as pool:
        result = await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    assert result.status == "completed"
    assert not any(summarizing(c) for c in provider.calls)


async def test_folding_says_so_in_the_run_log(tmp_path, monkeypatch):
    from poieo.runtime import nodes

    monkeypatch.setattr(nodes, "_CONTEXT_CAP", 10_000_000)
    monkeypatch.setattr(nodes, "_COMPACT_CAP", 400)
    monkeypatch.setattr(nodes, "_FOLD_AT_LEAST", 100)
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    store = _CapturingStore()
    await run_graph(graph, reads_the_same_file(8), store=store)

    folded = [e for e in store.events if e.type == "node_compacted"]
    assert folded
    assert folded[0].data["kept"] == nodes._KEEP_TURNS
    assert folded[0].data["folded"] > 0


async def test_agent_node_fails_cleanly_on_missing_workdir(tmp_path):
    graph = agent_graph(tmp_path / "not-there")
    binding = mock_binding({"worker": "hi"})
    result = await run_graph(graph, binding)
    assert result.status == "failed"
    assert "workdir" in result.error


async def test_agent_example_graph_runs_on_the_mock_binding(tmp_path):
    graph = load_graph(EXAMPLES / "tasks/agent-task.graph.yaml")
    binding = load_binding(EXAMPLES / "models/mock.yaml")
    result = await run_graph(graph, binding, workdir=tmp_path)
    assert result.status == "completed"
    assert (tmp_path / "TODO.md").exists()


async def test_agent_node_carries_raw_content_into_the_next_turn(tmp_path):
    # Provider-specific blocks (e.g. anthropic thinking blocks) arrive on
    # LLMResponse.meta["raw_content"]; AgentNode must round-trip them onto
    # the neutral history's assistant turn unchanged so the provider can
    # replay them verbatim on the next call.
    raw_blocks = [
        {"type": "thinking", "thinking": "hmm", "signature": "sig-xyz"},
        {"type": "tool_use", "id": "mock_1", "name": "read_file", "input": {"path": "notes.txt"}},
    ]
    (tmp_path / "notes.txt").write_text("secret-content")
    graph = agent_graph(tmp_path)
    binding = mock_binding(
        {
            "worker": [
                {
                    "tool_calls": [{"name": "read_file", "arguments": {"path": "notes.txt"}}],
                    "raw_content": raw_blocks,
                },
                "done",
            ]
        }
    )
    async with ProviderPool(binding) as pool:
        result = await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    assert result.status == "completed"
    second_call = provider.calls[1]
    assistant_turn = second_call.messages[-2]
    assert assistant_turn["role"] == "assistant"
    assert assistant_turn["raw_content"] == raw_blocks


async def test_agent_node_aborts_when_cancelled(tmp_path):
    # The last script entry repeats forever, so without cancellation this
    # node would loop until max_turns. Cancellation is checked at the top of
    # every turn (both the executor's and the agent node's), so a pre-set
    # event aborts the run before the first model call ever fires.
    graph = agent_graph(tmp_path)
    binding = mock_binding(
        {"worker": [{"tool_calls": [{"name": "list_dir", "arguments": {}}]}]}
    )
    cancel = asyncio.Event()
    cancel.set()
    result = await run_graph(graph, binding, cancel=cancel)
    assert result.status == "aborted"


class _CapturingStore(NullStore):
    def __init__(self):
        super().__init__()
        self.events = []

    def append(self, event):
        self.events.append(event)


async def test_agent_node_emits_a_turn_event_per_model_turn(tmp_path):
    graph = GraphSpec.model_validate(
        {
            "name": "g",
            "entry": "work",
            "nodes": [
                {
                    "id": "work",
                    "type": "agent",
                    "role": "worker",
                    "workdir": str(tmp_path),
                    "tools": ["files", "shell"],
                    "prompt": "go",
                }
            ],
        }
    )
    binding = mock_binding(
        {
            "worker": [
                {
                    "text": "looking",
                    "thinking": "let me see",
                    "tool_calls": [{"name": "list_dir", "arguments": {}}],
                },
                "all done",
            ]
        }
    )
    store = _CapturingStore()
    result = await run_graph(graph, binding, store=store)

    assert result.status == "completed"
    turns = [e for e in store.events if e.type == "node_turn"]
    assert [t.data["turn"] for t in turns] == [1, 2]
    assert turns[0].data["tool_call_count"] == 1
    assert turns[0].data["thinking"] == "let me see"
    assert turns[1].data["text"] == "all done"
    assert turns[1].data["tool_call_count"] == 0


def agent_graph_without_workdir(**node_overrides):
    node = {
        "id": "work",
        "type": "agent",
        "role": "worker",
        "prompt": "do it",
        # Tools are what need a directory, so a node with nowhere to work has
        # to have asked for them or there is nothing to refuse.
        "tools": ["files", "shell"],
        "output": {"as": "report"},
    }
    node.update(node_overrides)
    return GraphSpec.model_validate({"name": "ag", "entry": "work", "nodes": [node]})


def writes_a_file(name="made.txt"):
    return mock_binding(
        {
            "worker": [
                {
                    "tool_calls": [
                        {
                            "name": "write_file",
                            "arguments": {"path": name, "content": "hi"},
                        }
                    ]
                },
                "done",
            ]
        }
    )


async def test_agent_node_inherits_the_run_workdir(tmp_path):
    # The graph says what the work is; the task says where it happens. A graph
    # that hardcodes a path cannot be moved to another machine.
    result = await run_graph(
        agent_graph_without_workdir(), writes_a_file(), workdir=tmp_path
    )

    assert result.status == "completed"
    assert (tmp_path / "made.txt").read_text(encoding="utf-8") == "hi"


async def test_node_workdir_overrides_the_run_workdir(tmp_path):
    chosen = tmp_path / "chosen"
    chosen.mkdir()

    result = await run_graph(agent_graph(chosen), writes_a_file(), workdir=tmp_path)

    assert result.status == "completed"
    assert (chosen / "made.txt").exists()
    assert not (tmp_path / "made.txt").exists()


def test_preflight_rejects_an_agent_node_with_nowhere_to_work():
    with pytest.raises(SpecError, match="work"):
        preflight(agent_graph_without_workdir(), mock_binding({"worker": "hi"}))


def test_preflight_accepts_a_run_workdir_on_the_nodes_behalf(tmp_path):
    preflight(
        agent_graph_without_workdir(), mock_binding({"worker": "hi"}), workdir=tmp_path
    )


async def test_a_run_with_nowhere_to_work_fails_before_the_model(tmp_path):
    binding = writes_a_file()
    # Misconfiguration raises rather than becoming a failed run: it is not
    # flaky, and it must surface before a single token is spent.
    with pytest.raises(SpecError):
        await run_graph(agent_graph_without_workdir(), binding)


async def test_the_executor_is_torn_down_even_when_the_node_fails(tmp_path, monkeypatch):
    """`async with` is the whole reason the seam has a lifecycle: a node that
    raises must still release whatever the executor was holding."""
    from poieo import tools as tools_module
    from poieo.runtime import nodes as nodes_module

    torn_down = []
    real = tools_module.make_executor

    class Spy:
        """A wrapper class, not a patched instance: `async with` looks dunders
        up on the type, so assigning executor.__aexit__ would do nothing."""

        def __init__(self, inner):
            self.inner = inner

        async def __aenter__(self):
            return await self.inner.__aenter__()

        async def __aexit__(self, *exc_info):
            torn_down.append(True)
            return await self.inner.__aexit__(*exc_info)

    monkeypatch.setattr(
        nodes_module,
        "make_executor",
        lambda *args, **kwargs: Spy(real(*args, **kwargs)),
    )

    graph = agent_graph(tmp_path, max_turns=1)
    # The script repeats, so the model never stops calling tools and the node
    # hits max_turns and raises.
    binding = mock_binding(
        {"worker": [{"tool_calls": [{"name": "list_dir", "arguments": {}}]}]}
    )
    result = await run_graph(graph, binding)

    assert result.status == "failed"
    assert torn_down, "the executor was never torn down"


async def test_a_run_summary_says_what_the_run_said(tmp_path):
    """Ten runs that changed nothing used to read as ten rows of "2 steps",
    which is the graph's shape and not news about any of them."""
    graph = GraphSpec.model_validate(
        {
            "name": "quiet",
            "entry": "a",
            "nodes": [{"id": "a", "type": "agent", "prompt": "go", "next": "b"},
                      {"id": "b", "type": "agent", "prompt": "go"}],
        }
    )
    binding = mock_binding({"*": "nothing needed doing"})

    result = await run_graph(graph, binding)

    # The last node on the path that produced text, which is the same reading
    # the journal and the commit subject use.
    assert result.said() == "nothing needed doing"
    assert result.summary()["said"] == "nothing needed doing"


async def test_a_run_that_said_nothing_says_so_with_an_empty_string(tmp_path):
    graph = GraphSpec.model_validate(
        {"name": "mute", "entry": "a", "nodes": [{"id": "a", "type": "agent", "prompt": "go"}]}
    )

    result = await run_graph(graph, mock_binding({"*": ""}))

    # Empty, not "(said nothing)": that wording is a journal line's default,
    # and a summary is read by a board that wants to know there was nothing.
    assert result.summary()["said"] == ""


# -- the command node --------------------------------------------------------


def _command_graph(**node) -> GraphSpec:
    return GraphSpec.model_validate(
        {
            "name": "g",
            "entry": "check",
            "nodes": [
                {"id": "check", "type": "command", "next": "gate", **node},
                {
                    "id": "gate",
                    "type": "router",
                    "branches": [{"when": "check.exit_code == 0", "to": None,
                                  "label": "green"}],
                    "default": None,
                },
            ],
        }
    )


async def test_a_command_node_puts_the_exit_code_in_scope_as_a_number(tmp_path):
    """The whole point: a router branches on the number the process returned,
    not on a model's account of it."""
    graph = _command_graph(command="exit 0", output={"as": "check"}, workdir=str(tmp_path))

    result = await run_graph(graph, mock_binding({}), workdir=tmp_path)

    assert result.status == "completed"
    assert result.outputs["check"]["exit_code"] == 0
    assert result.outputs["gate"] == "green"


async def test_a_red_command_is_a_fact_to_branch_on_not_a_failed_run(tmp_path):
    """A failing test suite is what the graph is there to react to. The run
    only fails when the command could not run at all."""
    graph = _command_graph(command="exit 1", output={"as": "check"}, workdir=str(tmp_path))

    result = await run_graph(graph, mock_binding({}), workdir=tmp_path)

    assert result.status == "completed"
    assert result.outputs["check"]["exit_code"] == 1
    assert result.outputs["gate"] == "default"


async def test_a_command_node_spends_no_model_turn(tmp_path):
    """A binding that can answer nothing at all still runs this graph. If the
    node reached a provider, this would raise instead."""
    graph = _command_graph(command="exit 0", output={"as": "check"}, workdir=str(tmp_path))
    binding = BindingSpec.model_validate(
        {"name": "empty", "providers": {"none": {"type": "mock"}},
         "default": {"provider": "none", "model": "m"}}
    )

    result = await run_graph(graph, binding, workdir=tmp_path)

    assert result.status == "completed"
    assert result.usage["input_tokens"] == 0
    assert result.usage["output_tokens"] == 0


async def test_a_commands_output_is_readable_by_a_later_prompt(tmp_path):
    graph = GraphSpec.model_validate(
        {
            "name": "g",
            "entry": "check",
            "nodes": [
                {"id": "check", "type": "command", "command": "echo boom",
                 "output": {"as": "check"}, "workdir": str(tmp_path), "next": "fix"},
                {"id": "fix", "type": "agent", "prompt": "Fix: {{ check.output }}"},
            ],
        }
    )

    result = await run_graph(graph, mock_binding({}, fallback="fixed"), workdir=tmp_path)

    assert result.status == "completed"
    assert "boom" in result.outputs["check"]["output"]


async def test_a_command_that_never_finished_fails_the_run(tmp_path):
    """"This did not start" and "this went red" are different facts, and the
    graph must not be able to confuse them."""
    graph = _command_graph(
        command="python -c \"import time; time.sleep(5)\"",
        timeout=0.3,
        workdir=str(tmp_path),
    )

    result = await run_graph(graph, mock_binding({}), workdir=tmp_path)

    assert result.status == "failed"
    assert "timed out" in (result.error or "")


async def test_a_command_node_runs_where_the_task_works(tmp_path):
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    import os

    from poieo.tools.shell import posix_shell

    # Not "which OS is this" any more, but "was a POSIX shell found" -- which
    # on Windows is usually yes, and used to make no difference.
    graph = _command_graph(
        command="ls" if (os.name != "nt" or posix_shell()) else "dir /b",
        output={"as": "check"},
    )

    result = await run_graph(graph, mock_binding({}), workdir=tmp_path)

    assert "marker.txt" in result.outputs["check"]["output"]


async def test_a_script_node_runs_real_code_with_quotes_and_newlines(tmp_path):
    """The case a `command:` cannot express: this does not parse as YAML on one
    line, and a shell would eat the quotes if it did."""
    graph = GraphSpec.model_validate(
        {
            "name": "g",
            "entry": "gate",
            "nodes": [
                {
                    "id": "gate",
                    "type": "command",
                    "language": "python",
                    "script": (
                        "import json, sys\n"
                        "report = {'pct': 87.5}\n"
                        "print(json.dumps(report))\n"
                        "sys.exit(0 if report['pct'] >= 90 else 1)\n"
                    ),
                    "output": {"as": "gate"},
                }
            ],
        }
    )

    result = await run_graph(graph, mock_binding({}), workdir=tmp_path)

    assert result.status == "completed"
    assert result.outputs["gate"]["exit_code"] == 1
    assert '"pct": 87.5' in result.outputs["gate"]["output"]
    # No model was asked anything about it.
    assert result.usage["output_tokens"] == 0


async def test_a_script_can_read_the_scope_it_runs_in(tmp_path):
    """Templated like a command and a prompt are, so a script can act on what
    an earlier step produced."""
    graph = GraphSpec.model_validate(
        {
            "name": "g",
            "entry": "gate",
            "nodes": [
                {
                    "id": "gate",
                    "type": "command",
                    "language": "python",
                    "script": "print('floor is {{ input.floor }}')",
                    "output": {"as": "gate"},
                }
            ],
        }
    )

    result = await run_graph(
        graph, mock_binding({}), workdir=tmp_path, input={"floor": 90}
    )

    assert "floor is 90" in result.outputs["gate"]["output"]


async def test_env_values_are_templated(tmp_path):
    """The escape hatch a compiled script depends on. `script:` and `command:`
    are rendered against the run, and `env:` has to be too or "put what varies
    in env" is advice that does not work."""
    graph = _command_graph(
        language="python",
        script="import os; print(os.environ['WHO'])",
        env={"WHO": "{{ input.who }}"},
        output={"as": "check"},
        workdir=str(tmp_path),
    )

    result = await run_graph(
        graph, mock_binding({}), input={"who": "world"}, workdir=tmp_path
    )

    assert result.status == "completed"
    assert "world" in result.outputs["check"]["output"]
    assert "{{" not in result.outputs["check"]["output"]


def _guard_graph(when: str) -> GraphSpec:
    """One model turn, then a guard that either stops the run or lets it spend
    again. The second turn is what a real overnight loop keeps paying for."""
    return GraphSpec.model_validate(
        {
            "name": "g",
            "entry": "first",
            "nodes": [
                {"id": "first", "type": "agent", "prompt": "go", "next": "guard"},
                {
                    "id": "guard",
                    "type": "router",
                    "branches": [{"when": when, "to": None, "label": "enough"}],
                    "default": "again",
                },
                {"id": "again", "type": "agent", "prompt": "go on"},
            ],
        }
    )


def _confirm_graph(**node) -> GraphSpec:
    return GraphSpec.model_validate(
        {
            "name": "g",
            "entry": "look",
            "nodes": [
                {"id": "look", "type": "agent", "prompt": "look", "next": "confirm"},
                {
                    "id": "confirm",
                    "type": "confirm",
                    "prompt": "Merge it? {{ nodes.look }}",
                    "choices": ["merge", "hold"],
                    **node,
                },
            ],
        }
    )


async def test_a_run_can_stop_itself_on_what_it_has_spent():
    """The guard an unattended run needs. Nothing bounds cost today: max_steps
    counts steps, and one agent node with tools is a single step no matter how
    many turns or tokens it spends inside it."""
    graph = _guard_graph("run.usage.output_tokens > 3")

    result = await run_graph(graph, mock_binding({}, fallback="one two three four five"))

    assert result.status == "completed"
    assert result.path == ["first", "guard"]
    assert "again" not in result.outputs


async def test_a_run_under_its_limit_carries_on():
    """The same guard, not tripped -- so the threshold is read, not assumed."""
    graph = _guard_graph("run.usage.output_tokens > 100")

    result = await run_graph(graph, mock_binding({}, fallback="short"))

    assert result.path == ["first", "guard", "again"]


async def test_a_run_knows_how_long_it_has_been_going(tmp_path):
    """Real elapsed seconds, not a constant: a run that has been going since
    2am is the other thing worth stopping on."""
    graph = GraphSpec.model_validate(
        {
            "name": "g",
            "entry": "wait",
            "nodes": [
                {
                    "id": "wait",
                    "type": "command",
                    "language": "python",
                    "script": "import time; time.sleep(0.2)",
                    "workdir": str(tmp_path),
                    "next": "guard",
                },
                {
                    "id": "guard",
                    "type": "router",
                    "branches": [
                        {"when": "run.elapsed > 0.1", "to": None, "label": "long enough"}
                    ],
                    "default": "again",
                },
                {"id": "again", "type": "agent", "prompt": "go on"},
            ],
        }
    )

    result = await run_graph(graph, mock_binding({}), workdir=tmp_path)

    # Both, and the status first: without `elapsed` in scope the condition
    # raises, the run fails, and the path stops here for the wrong reason.
    assert result.status == "completed", result.error
    assert result.path == ["wait", "guard"]
async def test_a_confirm_node_ends_the_run_asking():
    """Not paused mid-walk: the run really ends. Nothing is held open, and the
    answer arrives afterwards as a fact about a finished run."""
    result = await run_graph(_confirm_graph(), mock_binding({}, fallback="a PR"))

    assert result.status == "asking"
    assert result.path == ["look", "confirm"]


async def test_a_confirm_node_records_the_question_it_asked():
    """Rendered, so what the person reads is what the run actually found."""
    result = await run_graph(_confirm_graph(), mock_binding({}, fallback="a PR"))

    assert result.asked["question"] == "Merge it? a PR"
    assert result.asked["choices"] == ["merge", "hold"]
    assert result.asked["node"] == "confirm"


async def test_a_run_that_asks_spends_no_model_turn_on_the_question():
    """One turn for the node before it, none for the asking."""
    result = await run_graph(_confirm_graph(), mock_binding({}, fallback="x"))

    assert result.outputs["confirm"] == "Merge it? x"
    assert result.status == "asking"
