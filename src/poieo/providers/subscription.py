"""Backends that spend a subscription instead of an API key.

Every other provider here buys tokens. These two rent a coding harness that is
already logged in -- Claude Code and Codex -- and let it answer on the plan the
user is already paying for. Two vendors in one file for the reason
``local.py`` holds two: they are one idea with two spellings.

The idea is *a harness driven headlessly*, and the two vendors disagree about
how much of themselves they will lend:

- **Claude Code** ships a Python library and lets a host turn every built-in
  tool off and supply its own, in-process. So poieo can keep its own tools, its
  own executor seam and its container -- which is what the next slice does.
- **Codex** is the other way round by design. Its non-interactive mode cannot
  approve someone else's tool calls at all, and the only flag that gets past
  that switches the sandbox off with it. Its vendor's own answer is to call
  Codex *as* a tool and hand it a sandbox mode, so Codex brings its own fence.

Neither of those is a workaround; each is the supported way in. This file is
the half they share.

Design: docs/binding.md
"""

from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from ..errors import ProviderError
from .base import Hands, LLMRequest, LLMResponse, Provider, ToolCall, Usage

# The name poieo's own tools are offered under. A harness spells an MCP tool
# `mcp__{server}__{tool}`, so the prefix is what an allow-list has to match.
_POIEO_SERVER = "poieo"
_POIEO_TOOL_PREFIX = f"mcp__{_POIEO_SERVER}__"


class _Subscription(Provider):
    """What both harnesses owe, whatever they are underneath."""

    #: The variable whose presence would silently move the bill.
    key_variable = ""
    #: What a person runs to fix that, in their own words.
    login_command = ""

    def _refuse_a_key(self) -> None:
        """A set key wins over the subscription login, and cannot be unset.

        Both harnesses inherit the environment they are started in and merge
        anything the caller adds *on top* -- so a variable can be overwritten
        but never removed, and an empty key still holds its place in the
        precedence order and authenticates as empty. That leaves two options
        and they are not close: refuse here, or quietly bill somebody's API
        account for work they thought their subscription covered. A wrong bill
        is discovered at the end of the month, which is the same reason
        ``anthropic_provider`` refuses a ``through:`` it does not recognise.

        Checked per call rather than once, because a daemon outlives the shell
        that started it and the environment is read, not remembered.
        """
        if os.environ.get(self.key_variable) is not None:
            raise ProviderError(
                f"provider '{self.name}' runs on a subscription, but ${self.key_variable} is set "
                f"and every one of these harnesses prefers a key over the login -- so this run "
                f"would go on the API bill instead. Unset ${self.key_variable} for the daemon's "
                f"environment. An empty value is not enough; the variable has to be gone",
                provider=self.name,
            )

    def _check_hands(self, request: LLMRequest) -> None:
        """Whether this harness can serve the step's tools, and say so if not.

        Named after the step rather than the provider: a graph has several and
        only some of them carry tools, so "which one" is the whole of what the
        reader needs to act.

        A node with tools always arrives with `Hands` -- the runtime lends
        them whenever it built an executor -- so a request that has tools and
        none is a caller that has not been taught to, and answering it would
        mean telling a harness about tools it cannot reach.
        """
        if not request.tools:
            return
        step = request.role or "this step"
        if request.hands is None:
            raise ProviderError(
                f"'{step}' asks for tools, but nothing was lent to run them, so provider "
                f"'{self.name}' has only their names. This is a caller that has not been "
                f"taught to lend its hands, not a graph that is wrong",
                provider=self.name,
            )
        self._check_fence(step, request.hands)

    def _check_fence(self, step: str, hands: Hands) -> None:
        """Whether the fence the task asked for is one this harness can hold.

        Nothing by default: a harness that runs poieo's own tools inherits
        poieo's fence and has nothing to check.
        """

    def _refuse_unusable(self, leftover: dict[str, Any]) -> None:
        """Generation settings a harness does not take are refused, not dropped.

        Every other provider here forwards what it does not recognise, because
        an endpoint may know a parameter this code has not heard of. A harness
        is not an endpoint: its options are a fixed set, so an unknown one goes
        nowhere. Dropping it silently would make `max_tokens: 16000` -- which
        is in every example binding -- read as configured while doing nothing,
        which is the mistake ``graph.py`` refuses model keys on a router to
        avoid. The harness decides its own ceilings; the message has to say so,
        because "why is it ignoring my setting" is otherwise unanswerable.
        """
        if leftover:
            named = ", ".join(sorted(leftover))
            raise ProviderError(
                f"provider '{self.name}' does not take {named}: a harness decides its own "
                f"ceilings and cannot be told otherwise. Drop them from the binding for this "
                f"provider, or bind this role to an endpoint that takes them",
                provider=self.name,
            )

    def read(self, result: dict[str, Any]) -> LLMResponse:
        """One harness's finished answer, as the runtime reads answers.

        **A subscription charges nothing for a call**, so `cost` is zero rather
        than the figure the harness reports: `Usage.cost` is what the endpoint
        charged, and zero is what its own docstring calls "a local model that
        really costs nothing". The notional dollars are worth keeping and are
        kept in `meta`, where they answer *what did this save me* without
        arming a spend limit against money nobody is billed.
        """
        usage = result.get("usage") or {}
        meta: dict[str, Any] = {}
        notional = result.get("total_cost_usd")
        if notional is not None:
            meta["would_have_cost"] = notional
        if result.get("session_id"):
            meta["session_id"] = result["session_id"]
        return LLMResponse(
            text=result.get("result") or "",
            model=result.get("model") or "",
            usage=Usage(
                input_tokens=int(usage.get("input_tokens") or 0),
                output_tokens=int(usage.get("output_tokens") or 0),
                cache_read_tokens=int(usage.get("cache_read_input_tokens") or 0),
                cache_write_tokens=int(usage.get("cache_creation_input_tokens") or 0),
                reasoning_tokens=int(usage.get("reasoning_tokens") or 0),
                cost=0.0,
            ),
            stop_reason=result.get("stop_reason"),
            meta=meta,
        )

    async def context_for(self, model: str) -> int | None:
        """Nothing to ask. A harness does its own context management."""
        return None


def _last_user_message(request: LLMRequest) -> str:
    """What this step is being asked, as one string.

    A harness keeps its own history, so a poieo node hands it the turn it has
    -- which for an agent node is exactly one, the rendered prompt.
    """
    for message in reversed(request.messages):
        if message.get("role") == "user":
            content = message.get("content")
            return content if isinstance(content, str) else json.dumps(content)
    return ""


class ClaudeCodeProvider(_Subscription):
    """Claude Code, through the official Agent SDK, on a Claude plan."""

    type = "claude_code"
    key_variable = "ANTHROPIC_API_KEY"
    login_command = "claude auth login"

    def plan(self, request: LLMRequest) -> dict[str, Any]:
        """The options this call would run under.

        Separated from running it because this is the part with an answer
        capable of being wrong, and it can then be read in a test without a
        CLI on the machine -- the same split ``anthropic_provider`` makes with
        ``_build_kwargs``.
        """
        self._refuse_a_key()
        self._check_hands(request)
        params = dict(request.params)
        options: dict[str, Any] = {
            # **No built-in tools at all.** Not a restriction on an agent: it
            # is what makes this a completion. An empty list empties Claude's
            # context of them, so there is nothing for it to reach for.
            "tools": [],
            "model": request.model,
            # One call when there is nothing to reach for; the node's own
            # ceiling when there is. An unattended harness looping without a
            # bound is exactly what `max_turns` exists to prevent.
            "max_turns": request.hands.max_turns if request.hands else 1,
            # Nothing of the reader's own checkout may decide what a poieo step
            # answers -- not their settings, not their MCP servers, not a
            # CLAUDE.md that happens to be above the folder the daemon started
            # in. A graph is meant to be portable across machines.
            "setting_sources": [],
            "strict_mcp_config": True,
            "mcp_servers": {},
        }
        if request.tools and request.hands is not None:
            # **poieo's tools, and only poieo's.** Every call goes back through
            # the executor the node built -- so the workdir confinement holds,
            # and a task that asked to be boxed is still working inside its
            # container. The built-ins stay off above for the same reason: a
            # built-in `Write` would reach the disk without passing the seam.
            #
            # Named without a prompt to approve them, because there is nobody
            # at the keyboard at 3am and the fence is already the executor's.
            options["allowed_tools"] = [f"{_POIEO_TOOL_PREFIX}{tool.name}" for tool in request.tools]
            options["cwd"] = request.hands.workdir
        if request.system:
            options["system_prompt"] = request.system
        if "effort" in params:
            options["effort"] = params.pop("effort")
        if "max_thinking_tokens" in params:
            options["max_thinking_tokens"] = params.pop("max_thinking_tokens")
        self._refuse_unusable(params)
        return options

    async def complete(self, request: LLMRequest) -> LLMResponse:
        options = self.plan(request)
        sdk = _agent_sdk(self.name)
        if request.tools and request.hands is not None:
            # The one part of the options that cannot be worked out without the
            # SDK on the machine, and so the one part `plan()` leaves out: the
            # server object itself. What it *contains* -- which tools, under
            # which names -- is decided up there, where a test can read it.
            options["mcp_servers"] = {_POIEO_SERVER: _lend(sdk, request.tools, request.hands)}
        result: dict[str, Any] = {}
        try:
            async for message in sdk.query(
                prompt=_last_user_message(request),
                options=sdk.ClaudeAgentOptions(**options),
            ):
                if isinstance(message, sdk.ResultMessage):
                    result = {
                        "result": message.result,
                        "usage": message.usage,
                        "total_cost_usd": message.total_cost_usd,
                        "stop_reason": message.stop_reason,
                        "session_id": message.session_id,
                        "model": request.model,
                        "is_error": message.is_error,
                        "errors": message.errors,
                    }
        except sdk.CLINotFoundError as exc:
            raise ProviderError(
                f"provider '{self.name}' needs the Claude Code CLI on this machine: {exc}",
                provider=self.name,
            ) from exc
        except sdk.ClaudeSDKError as exc:
            raise ProviderError(
                f"provider '{self.name}': {exc}. If this says the login has gone, run `{self.login_command}`",
                provider=self.name,
                retryable=True,
            ) from exc
        if not result:
            raise ProviderError(f"provider '{self.name}': the harness ended without a result", provider=self.name)
        if result.get("is_error"):
            raise ProviderError(
                f"provider '{self.name}': {'; '.join(result.get('errors') or ['the harness reported a failure'])}",
                provider=self.name,
                retryable=True,
            )
        return self.read(result)

    async def health(self) -> tuple[bool, str]:
        """Asked of the CLI's own login, which costs nothing to read.

        `poieo check` is where "you are not logged in" belongs -- a run that
        discovers it at 3am reports a model failure for what is a five-second
        fix, and the honest sentence is the one that names the fix.
        """
        if os.environ.get(self.key_variable) is not None:
            return False, f"${self.key_variable} is set, which would bill the API instead of the plan"
        answer, said = await _ask_json(["claude", "auth", "status"])
        if answer is None:
            return False, said
        if not answer.get("loggedIn"):
            return False, f"not logged in; run `{self.login_command}`"
        plan = answer.get("subscriptionType") or answer.get("authMethod") or "signed in"
        return True, f"Claude Code, on a {plan} plan"


class CodexProvider(_Subscription):
    """Codex, through `codex exec`, on a ChatGPT plan."""

    type = "codex"
    key_variable = "OPENAI_API_KEY"
    login_command = "codex login"

    #: What `--sandbox workspace-write` amounts to in poieo's own words: read
    #: and write inside the folder, and run commands there.
    _SERVES = frozenset({"files", "shell"})

    def _check_fence(self, step: str, hands: Hands) -> None:
        """Codex brings its own fence, so poieo's has to be one it can hold.

        Both refusals here are the same rule: **a fence that was asked for and
        is not held is worse than one that was never offered**, because nobody
        knows which half is holding.
        """
        if hands.boxed:
            raise ProviderError(
                f"'{step}' asked to be fenced, and provider '{self.name}' cannot be put inside "
                f"poieo's container -- it runs its own sandbox on this machine instead. Drop "
                f"`isolation:` from this task, or bind this step to an endpoint with a key",
                provider=self.name,
            )
        asked = set(hands.toolsets)
        if asked != self._SERVES:
            wanted = ", ".join(sorted(asked)) or "none"
            raise ProviderError(
                f"'{step}' asks for {wanted}, and provider '{self.name}' decides its own tool "
                f"surface: it can serve exactly {', '.join(sorted(self._SERVES))} and cannot "
                f"narrow to less. Handing over more than a step asked for is what a toolset "
                f"list exists to prevent, so this is refused rather than widened",
                provider=self.name,
            )

    def plan(self, request: LLMRequest) -> tuple[list[str], str]:
        """The arguments and the standard input this call would run with.

        **The prompt is never an argument.** It is long and arbitrary, and on
        Windows the `codex` on PATH is a `.cmd` shim whose arguments are
        re-parsed by `cmd.exe` on the way past -- the same hazard `graph.md`
        hands a `script:` to an interpreter's stdin to avoid.
        """
        self._refuse_a_key()
        self._check_hands(request)
        # `codex exec` takes no generation settings at all, so anything the
        # binding sent would go nowhere. Said rather than dropped.
        self._refuse_unusable(dict(request.params))
        working = request.hands.workdir if request.hands else None
        argv = [
            "exec",
            "--json",
            # A step with no tools has nothing to write, whatever the model
            # would like to do about that. A step with them gets Codex's own
            # fence: its sandbox, held to the folder the node works in.
            "--sandbox",
            "workspace-write" if request.tools else "read-only",
            # Codex's spelling of the rule Claude's empty `setting_sources`
            # keeps: a poieo step reads none of the reader's own setup.
            "--ignore-user-config",
            "--ignore-rules",
            # A run is a step of a graph, not a conversation somebody will come
            # back to -- and the daemon has its own run log.
            "--ephemeral",
            # The folder a tool-less step sits in is nobody's repository, and
            # refusing to start there would be refusing over something this
            # step cannot use anyway.
            "--skip-git-repo-check",
            "--model",
            _plain(request.model, "model", self.name),
        ]
        if working:
            # Where the work happens. The node's workdir is a private copy of
            # the user's folder, so what Codex writes still arrives as one
            # change to accept or discard in the morning.
            argv += ["--cd", working]
        return argv, _last_user_message(request)

    async def complete(self, request: LLMRequest) -> LLMResponse:
        argv, prompt = self.plan(request)
        events, said = await _run_json_lines(["codex", *argv], prompt, self.spec.timeout)
        if events is None:
            raise ProviderError(
                f"provider '{self.name}': {said}. If this says the login has gone, run `{self.login_command}`",
                provider=self.name,
                retryable=True,
            )
        return self.read(_codex_result(events, request.model))

    async def health(self) -> tuple[bool, str]:
        if os.environ.get(self.key_variable) is not None:
            return False, f"${self.key_variable} is set, which would bill the API instead of the plan"
        answer, said = await _ask_text(["codex", "login", "status"])
        # **A Codex login goes stale after about a week idle**, which for a
        # daemon that runs unattended is a Tuesday rather than an edge case --
        # so this failure gets the sentence that fixes it rather than the one
        # the CLI happens to print. It says "Not logged in" on *stderr* and
        # exits 1, so the answer arrives as the reason there was no answer.
        for spoken in (answer, said):
            if spoken and "not logged in" in spoken.lower():
                return False, f"not logged in; run `{self.login_command}`"
        if answer is None:
            return False, said
        return True, f"Codex, {answer.strip().splitlines()[0]}"


# -- reaching the two harnesses -------------------------------------------------


def _agent_sdk(name: str) -> Any:
    """The Claude Agent SDK, imported when it is first needed.

    Late, and never at construction: `poieo check` exists to say *what is
    missing*, and it cannot say it about a provider that could not be built.
    The package is an extra rather than a dependency, because it brings a whole
    coding agent with it and most bindings here never name one.
    """
    try:
        import claude_agent_sdk
    except ImportError as exc:  # pragma: no cover - exercised by hand
        raise ProviderError(
            f"provider '{name}' needs the Claude Agent SDK: pip install 'poieo[claude-code]'",
            provider=name,
        ) from exc
    return claude_agent_sdk


def _binary(name: str) -> str | None:
    """Where this CLI actually is, or None.

    Resolved rather than named, because on Windows the thing on PATH is
    `claude.CMD` and exec does not add the extension for you -- so passing the
    bare name finds nothing on the one platform CI runs the Python suite on.
    """
    import shutil

    return shutil.which(name)


# What may appear in a value poieo turns into a command-line argument. The
# shim on Windows is a `.CMD`, so arguments are re-parsed by `cmd.exe` on the
# way past -- and a model id arrives from a binding file, which is a place a
# person types things. The prompt never comes near here; it goes on stdin.
_SAFE_ARGUMENT = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._:/@-")


def _plain(value: str, what: str, provider: str) -> str:
    if value and not set(value) <= _SAFE_ARGUMENT:
        raise ProviderError(
            f"provider '{provider}': {what} '{value}' has characters that cannot be passed "
            f"to a command safely; a model id is letters, digits and `.:_/@-`",
            provider=provider,
        )
    return value


async def _capture(argv: list[str], stdin: str | None, timeout: float) -> tuple[int, str, str]:
    """Run a command and collect what it said.

    The shape `tools/shell.py` already uses, for the reason it gives: a
    subprocess that outlives its welcome is killed rather than left holding the
    daemon's event loop.
    """
    process = await asyncio.create_subprocess_exec(
        *argv,
        stdin=asyncio.subprocess.PIPE if stdin is not None else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        out, err = await asyncio.wait_for(
            process.communicate(stdin.encode("utf-8") if stdin is not None else None), timeout
        )
    except asyncio.TimeoutError:
        process.kill()
        await process.communicate()
        raise
    return process.returncode or 0, out.decode("utf-8", "replace"), err.decode("utf-8", "replace")


async def _ask_text(argv: list[str]) -> tuple[str | None, str]:
    """A cheap question put to a CLI, or the reason it could not be asked."""
    found = _binary(argv[0])
    if found is None:
        return None, f"`{argv[0]}` is not on this machine"
    try:
        code, out, err = await _capture([found, *argv[1:]], None, 20.0)
    except FileNotFoundError:
        return None, f"`{argv[0]}` is not on this machine"
    except Exception as exc:  # noqa: BLE001 - a health check never raises
        return None, f"could not ask `{argv[0]}`: {exc}"
    if code != 0 and not out.strip():
        return None, (err.strip() or f"`{' '.join(argv)}` exited {code}")
    return out, ""


async def _ask_json(argv: list[str]) -> tuple[dict[str, Any] | None, str]:
    out, said = await _ask_text(argv)
    if out is None:
        return None, said
    try:
        return json.loads(out), ""
    except json.JSONDecodeError:
        return None, f"`{' '.join(argv)}` did not answer in JSON"


async def _run_json_lines(argv: list[str], stdin: str, timeout: float) -> tuple[list[dict[str, Any]] | None, str]:
    """One `codex exec --json` run, as the events it printed."""
    found = _binary(argv[0])
    if found is None:
        return None, f"`{argv[0]}` is not on this machine"
    try:
        code, out, err = await _capture([found, *argv[1:]], stdin, timeout)
    except FileNotFoundError:
        return None, f"`{argv[0]}` is not on this machine"
    except Exception as exc:  # noqa: BLE001 - reported, never raised through
        return None, f"could not run `{argv[0]}`: {exc}"
    events: list[dict[str, Any]] = []
    for line in out.splitlines():
        line = line.strip()
        if not line.startswith("{"):
            continue
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            # A harness may print something friendly among its events. That is
            # not a reason to lose the run.
            continue
    if code != 0 and not events:
        return None, (err.strip() or f"codex exited {code}")
    return events, ""


def _codex_result(events: list[dict[str, Any]], model: str) -> dict[str, Any]:
    """Codex's event stream, as one finished answer.

    The **last** agent message, not the first: a turn may say something on the
    way to saying the thing, and what a node's `output:` reads is where the
    step ended up.
    """
    text = ""
    usage: dict[str, Any] = {}
    failed: str | None = None
    for event in events:
        kind = event.get("type")
        if kind == "item.completed" and (event.get("item") or {}).get("type") == "agent_message":
            text = (event["item"].get("text") or "").strip()
        elif kind == "turn.completed":
            raw = event.get("usage") or {}
            usage = {
                "input_tokens": raw.get("input_tokens"),
                "output_tokens": raw.get("output_tokens"),
                # Codex reports what it read from cache; poieo's `Usage` calls
                # the same number `cache_read_tokens`.
                "cache_read_input_tokens": raw.get("cached_input_tokens"),
                "reasoning_tokens": raw.get("reasoning_output_tokens"),
            }
        elif kind in {"turn.failed", "error"}:
            failed = str(event.get("error") or event.get("message") or kind)
    if failed and not text:
        raise ProviderError(f"codex: {failed}", retryable=True)
    return {"result": text, "usage": usage, "model": model}


def _lend(sdk: Any, tools: list[Any], hands: Hands) -> Any:
    """poieo's own tools, offered to Claude Code as an in-process MCP server.

    **This is what keeps the fence where it was.** The harness never gets a
    built-in file or shell tool -- `plan()` empties them -- and every call it
    makes lands in `hands.run`, which is the node's executor. So the workdir
    confinement holds, a task that asked to be boxed is still working inside
    its container, and every call is still counted and written to the run log.

    In-process, so there is no second process to start, no port, and nothing
    to leave behind if the run dies. The server object cannot be built without
    the SDK, which is the only reason this is not decided in `plan()` with
    everything else.
    """

    def _bridge(spec: Any) -> Any:
        async def handler(arguments: dict[str, Any]) -> dict[str, Any]:
            text, failed = await hands.run(ToolCall(id="", name=spec.name, arguments=arguments))
            # `is_error` rather than a raised exception, because a tool that
            # failed is something the model should read and work around --
            # which is the rule the node's own loop already follows.
            return {"content": [{"type": "text", "text": text}], "is_error": failed}

        # The schema poieo already wrote for this tool, handed over as it is.
        # Rewriting it into the decorator's shorthand would be a second
        # description of one thing, and the two would drift.
        return sdk.tool(spec.name, spec.description, spec.input_schema)(handler)

    return sdk.create_sdk_mcp_server(
        name=_POIEO_SERVER,
        version="1.0.0",
        tools=[_bridge(spec) for spec in tools],
    )
