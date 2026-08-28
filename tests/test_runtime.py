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


def tool_contents(call):
    return [m["content"] for m in call.messages if m["role"] == "tool"]


async def test_a_conversation_under_the_cap_is_sent_whole(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 100)
    graph = agent_graph(tmp_path)
    async with ProviderPool(binding := reads_the_same_file(4)) as pool:
        result = await execute(graph, binding, pool, NullStore())
        provider = pool.get("fake")

    assert result.status == "completed"
    # Four reads of a hundred characters is nowhere near the cap, so every
    # result is still there in full on the last request.
    assert tool_contents(provider.calls[-1]) == ["x" * 100] * 4


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
    assert sent[2:] == ["x" * 100] * 3


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
    assert cleared[0].data["freed"] == 100 - len(nodes._CLEARED)


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
