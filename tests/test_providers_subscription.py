"""The two backends that spend a subscription rather than an API key.

Nothing here starts a CLI or opens a socket. Both providers are tested the way
`test_providers.py` tests the Anthropic one: by looking at what they *would*
send, which is where the answers capable of being wrong live. Neither Claude
Code nor Codex is installed in CI, and this suite has to pass there.
"""

from __future__ import annotations

import pytest

from poieo.binding import ProviderSpec
from poieo.errors import ProviderError
from poieo.providers import build_provider
from poieo.providers.base import Hands, LLMRequest, ToolDef


def _request(**kwargs) -> LLMRequest:
    fields = {
        "model": "claude-opus-5",
        "messages": [{"role": "user", "content": "say hello"}],
    }
    fields.update(kwargs)
    return LLMRequest(**fields)


HANDS = ToolDef(name="write_file", description="write a file", input_schema={"type": "object"})


# -- a key in the environment is the silent failure -----------------------------


@pytest.mark.parametrize(
    ("kind", "variable"),
    [("claude_code", "ANTHROPIC_API_KEY"), ("codex", "OPENAI_API_KEY")],
)
def test_a_key_in_the_environment_is_refused_rather_than_worked_around(monkeypatch, kind, variable):
    """The one failure a person would not notice until the end of the month.

    Both CLIs prefer a key over the subscription login, and neither can be told
    to ignore one: the SDK inherits the environment and merges on top of it, so
    a variable can be overwritten but never removed, and an empty key still
    wins its slot and authenticates as empty. So the choice is to refuse or to
    quietly bill somebody's API account, and it is not a close call.
    """
    monkeypatch.setenv(variable, "sk-test-not-a-real-key")
    provider = build_provider("subscription", ProviderSpec(type=kind))

    with pytest.raises(ProviderError) as raised:
        provider.plan(_request())

    assert variable in str(raised.value)
    # The message has to say what to do, not only what is wrong: the reader is
    # holding a shell where somebody exported this months ago.
    assert "unset" in str(raised.value).lower()


@pytest.mark.parametrize("kind", ["claude_code", "codex"])
def test_the_other_vendors_key_is_none_of_this_providers_business(monkeypatch, kind):
    """A binding may hold both kinds of endpoint, and usually does."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.setenv("GROQ_API_KEY", "sk-test")
    provider = build_provider("subscription", ProviderSpec(type=kind))

    provider.plan(_request())  # does not raise


# -- a step with hands is refused, and says why ---------------------------------


@pytest.mark.parametrize("kind", ["claude_code", "codex"])
def test_a_step_with_hands_is_refused_by_name(monkeypatch, kind):
    """Read as a limit, not a bug -- and name the step, because a graph has
    several and only some of them carry tools."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type=kind))

    with pytest.raises(ProviderError) as raised:
        provider.plan(_request(tools=[HANDS], role="builder"))

    message = str(raised.value)
    assert "builder" in message
    assert "tools" in message.lower()


# -- what each one would actually send ------------------------------------------


def test_claude_code_offers_the_model_no_tools_at_all(monkeypatch):
    """`tools=[]` empties Claude's context of built-ins, which is the whole of
    what makes this a completion rather than an agent loose in a folder."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="claude_code"))

    options = provider.plan(_request(system="be terse", model="claude-opus-5"))

    assert options["tools"] == []
    assert options["model"] == "claude-opus-5"
    assert options["system_prompt"] == "be terse"
    # Nothing of the reader's own checkout may reach a poieo step: a node's
    # answer must not depend on whose machine it ran on.
    assert options["setting_sources"] == []
    assert options["strict_mcp_config"] is True


def test_claude_code_carries_effort_over_from_the_binding(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="claude_code"))

    options = provider.plan(_request(params={"effort": "low"}))

    assert options["effort"] == "low"


def test_codex_keeps_the_prompt_out_of_every_argument(monkeypatch):
    """A prompt is long and arbitrary, and on Windows the CLI on PATH is a
    `.cmd` shim whose arguments are re-parsed by `cmd.exe`. Same reason
    `graph.md` gives for handing a script to an interpreter on stdin."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="codex"))

    argv, stdin = provider.plan(_request(messages=[{"role": "user", "content": "hello $(rm -rf /)"}]))

    assert stdin == "hello $(rm -rf /)"
    assert not any("rm -rf" in part for part in argv)
    assert argv[:2] == ["exec", "--json"]


def test_codex_reads_nothing_of_the_readers_own_setup(monkeypatch):
    """`--ignore-user-config` and `--ignore-rules` are Codex's spelling of the
    rule Claude's `setting_sources: []` keeps."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="codex"))

    argv, _ = provider.plan(_request())

    assert "--ignore-user-config" in argv
    assert "--ignore-rules" in argv
    # A step with no tools has no business writing anything, whatever the model
    # decides it would like to do.
    assert argv[argv.index("--sandbox") + 1] == "read-only"


def test_codex_names_the_model_the_binding_chose(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="codex"))

    argv, _ = provider.plan(_request(model="gpt-5.3-codex"))

    assert argv[argv.index("--model") + 1] == "gpt-5.3-codex"


# -- a subscription charges nothing per call ------------------------------------


@pytest.mark.parametrize("kind", ["claude_code", "codex"])
def test_a_subscription_charges_nothing_for_a_call_and_says_so(monkeypatch, kind):
    """Zero, not the notional dollars the harness reports.

    `Usage.cost` is what the endpoint charged, and a subscription charges
    nothing per call -- exactly like the local model the docstring names. The
    notional figure is kept in `meta`, where it answers "what did this save
    me" without arming a spend limit against money nobody is billed.
    """
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type=kind))

    answer = provider.read(
        {
            "result": "hello",
            "usage": {"input_tokens": 11, "output_tokens": 3},
            "total_cost_usd": 0.42,
        }
    )

    assert answer.text == "hello"
    assert answer.usage.input_tokens == 11
    assert answer.usage.output_tokens == 3
    assert answer.usage.cost == 0.0
    assert answer.meta["would_have_cost"] == 0.42


def test_claude_code_counts_cached_input_in_the_prompt_total(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="claude_code"))

    answer = provider.read(
        {
            "result": "hello",
            "usage": {
                "input_tokens": 108,
                "output_tokens": 3,
                "cache_read_input_tokens": 2_502_763,
                "cache_creation_input_tokens": 5_000,
            },
        }
    )

    assert answer.usage.input_tokens == 2_507_871
    assert answer.usage.cache_read_tokens == 2_502_763
    assert answer.usage.cache_write_tokens == 5_000


def test_codex_input_already_includes_its_cached_share(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="codex"))

    answer = provider.read(
        {
            "result": "hello",
            "usage": {
                "input_tokens": 10_000,
                "output_tokens": 3,
                "cache_read_input_tokens": 8_000,
            },
        }
    )

    assert answer.usage.input_tokens == 10_000
    assert answer.usage.cache_read_tokens == 8_000


@pytest.mark.parametrize("kind", ["claude_code", "codex"])
def test_a_harness_that_reports_no_usage_is_not_invented_for(monkeypatch, kind):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type=kind))

    answer = provider.read({"result": "hello"})

    assert answer.usage.input_tokens == 0
    assert answer.usage.cost == 0.0
    assert "would_have_cost" not in answer.meta


# -- nothing is resolved before it is needed ------------------------------------


@pytest.mark.parametrize("kind", ["claude_code", "codex"])
def test_building_one_needs_neither_cli_nor_sdk_installed(kind):
    """CI runs Windows and Ubuntu with neither of these on the machine, and
    `poieo check` has to be able to load a binding that names one and report
    what is missing -- which it cannot do if constructing it already failed."""
    provider = build_provider("subscription", ProviderSpec(type=kind))

    assert provider.name == "subscription"


# -- a setting that would go nowhere --------------------------------------------


@pytest.mark.parametrize("kind", ["claude_code", "codex"])
def test_a_generation_setting_a_harness_cannot_take_is_refused(monkeypatch, kind):
    """Every other provider forwards what it does not recognise, because an
    endpoint may know a parameter this code has not heard of. A harness is not
    an endpoint -- its options are a fixed set -- so an unknown one goes
    nowhere, and `max_tokens: 16000` sitting in every example binding would
    read as configured while doing nothing."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type=kind))

    with pytest.raises(ProviderError) as raised:
        provider.plan(_request(params={"max_tokens": 16000, "temperature": 0.2}))

    message = str(raised.value)
    assert "max_tokens" in message and "temperature" in message


def test_claude_code_still_takes_the_settings_it_can_honour(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="claude_code"))

    options = provider.plan(_request(params={"effort": "max", "max_thinking_tokens": 4096}))

    assert options["effort"] == "max"
    assert options["max_thinking_tokens"] == 4096


def test_a_model_id_that_could_not_be_an_argument_is_refused(monkeypatch):
    """The prompt goes on stdin and never near a command line, but a model id
    is an argument and arrives from a file a person types in -- and on Windows
    the CLI on PATH is a `.CMD` whose arguments `cmd.exe` reads again."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="codex"))

    with pytest.raises(ProviderError) as raised:
        provider.plan(_request(model='gpt-5 & echo "oops"'))

    assert "model" in str(raised.value)


# -- hands: each harness fenced the way its vendor supports ---------------------


async def _ran(call):  # pragma: no cover - a stand-in, never reached in these tests
    return "done", False


def _lent(**kwargs) -> Hands:
    fields = {"run": _ran, "workdir": "/work", "max_turns": 12, "toolsets": ("files", "shell")}
    fields.update(kwargs)
    return Hands(**fields)


def test_claude_code_hands_its_own_tools_over_and_keeps_the_built_ins_off(monkeypatch):
    """poieo's fence does not move: the harness gets poieo's tools and only
    those, so every call still goes through the executor -- and through the
    container, when the task asked for one."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="claude_code"))

    options = provider.plan(_request(tools=[HANDS], hands=_lent()))

    # Still empty. A built-in Write would reach the disk without passing the
    # seam, which is the whole thing this arrangement exists to prevent.
    assert options["tools"] == []
    assert options["allowed_tools"] == ["mcp__poieo__write_file"]
    assert options["cwd"] == "/work"
    # The node's own ceiling, or an unattended harness has none at all.
    assert options["max_turns"] == 12


def test_claude_code_runs_a_boxed_step_because_the_box_is_still_poieos(monkeypatch):
    """The container is around the *executor*, and the executor is what the
    harness is calling. Nothing about that changes when the caller is Claude."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="claude_code"))

    options = provider.plan(_request(tools=[HANDS], hands=_lent(boxed=True)))

    assert options["allowed_tools"] == ["mcp__poieo__write_file"]


def test_codex_refuses_a_step_that_asked_for_a_container(monkeypatch):
    """Codex brings its own fence and cannot be put inside poieo's. A fence
    that is asked for and not honoured is worse than one that was never
    offered, because nobody knows which half is holding."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="codex"))

    with pytest.raises(ProviderError) as raised:
        provider.plan(_request(tools=[HANDS], hands=_lent(boxed=True), role="builder"))

    message = str(raised.value)
    # Names the key a person would edit, which is `isolation:` -- not the
    # word this code happens to use for the idea.
    assert "isolation" in message
    assert "builder" in message


def test_codex_refuses_a_toolset_it_would_have_to_widen(monkeypatch):
    """`tools: [files]` means read and write but no shell. Codex decides its
    own tool surface, so it cannot offer that -- and handing over more than was
    asked for is the one thing a toolset list exists to stop."""
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="codex"))

    with pytest.raises(ProviderError) as raised:
        provider.plan(_request(tools=[HANDS], hands=_lent(toolsets=("files",))))

    assert "files" in str(raised.value)


def test_codex_works_in_the_nodes_folder_and_may_write_there(monkeypatch):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="codex"))

    argv, _ = provider.plan(_request(tools=[HANDS], hands=_lent()))

    assert argv[argv.index("--sandbox") + 1] == "workspace-write"
    assert argv[argv.index("--cd") + 1] == "/work"


def test_a_step_with_tools_and_no_way_to_run_them_is_still_refused(monkeypatch):
    """A provider that never learned to lend its hands would otherwise send a
    harness a list of tools it cannot reach, and get an answer about them."""
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    provider = build_provider("subscription", ProviderSpec(type="claude_code"))

    with pytest.raises(ProviderError):
        provider.plan(_request(tools=[HANDS], role="builder"))
