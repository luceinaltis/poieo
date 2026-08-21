import pytest

from conftest import EXAMPLES
from poieo.binding import BindingSpec, load_binding
from poieo.graph import GraphSpec, load_graph
from poieo.providers import ProviderPool
from poieo.runtime.executor import execute, preflight
from poieo.store import NullStore
from poieo.errors import BindingError


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
    async with ProviderPool(binding) as pool:
        return await execute(graph, binding, pool, NullStore(), **kwargs)


async def test_router_picks_the_matching_arm():
    graph = load_graph(EXAMPLES / "graphs/support-triage.yaml")
    binding = mock_binding({"classifier": "feature", "writer": "ack"})
    result = await run_graph(graph, binding, input={"message": "please add dark mode"})

    assert result.status == "completed"
    assert result.path == ["classify", "route", "draft_feature"]
    assert result.outputs["draft_feature"] == "ack"


async def test_router_falls_through_to_default():
    graph = load_graph(EXAMPLES / "graphs/support-triage.yaml")
    binding = mock_binding({"classifier": "question", "writer": "answer"})
    result = await run_graph(graph, binding, input={"message": "how do I log in?"})
    assert result.path[-1] == "draft_answer"


async def test_cycle_exits_when_the_critic_approves():
    graph = load_graph(EXAMPLES / "graphs/draft-review.yaml")
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
    graph = load_graph(EXAMPLES / "graphs/draft-review.yaml")
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
            "nodes": [{"id": "a", "type": "llm", "prompt": "go", "next": "a"}],
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
                    "type": "llm",
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
                {"id": "a", "type": "llm", "prompt": "go", "output": {"format": "json"}}
            ],
        }
    )
    result = await run_graph(graph, mock_binding({"*": "not json at all"}))
    assert result.status == "failed"
    assert "expected JSON" in result.error


async def test_state_carries_into_the_next_run():
    graph = load_graph(EXAMPLES / "graphs/draft-review.yaml")
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
            "nodes": [{"id": "a", "type": "llm", "prompt": "Hello {{ input.who }}"}],
        }
    )
    binding = mock_binding({"*": "hi"})
    async with ProviderPool(binding) as pool:
        await execute(graph, binding, pool, NullStore(), input={"who": "world"})
        sent = pool.get("fake").calls[0]
    assert sent.messages[0]["content"] == "Hello world"


def test_preflight_rejects_an_incomplete_binding():
    graph = load_graph(EXAMPLES / "graphs/support-triage.yaml")
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
                    "type": "llm",
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


async def test_agent_node_stops_at_max_turns(tmp_path):
    graph = agent_graph(tmp_path, max_turns=3)
    # The script's last entry repeats forever, so the model never finishes.
    binding = mock_binding(
        {"worker": [{"tool_calls": [{"name": "list_dir", "arguments": {}}]}]}
    )
    result = await run_graph(graph, binding)
    assert result.status == "failed"
    assert "max_turns" in result.error


async def test_agent_node_fails_cleanly_on_missing_workdir(tmp_path):
    graph = agent_graph(tmp_path / "not-there")
    binding = mock_binding({"worker": "hi"})
    result = await run_graph(graph, binding)
    assert result.status == "failed"
    assert "workdir" in result.error
