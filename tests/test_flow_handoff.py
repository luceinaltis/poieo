"""A flow's `then:` block: the wiring, what must be true of it, and the handoff.

Two halves, in that order. Above the divider is what a config has to get right
before the daemon will start at all; below it is what actually happens when a
run ends -- which flow wakes, what it is told, and what is refused.

Design: docs/daemon.md
"""

import asyncio

import pytest

from poieo.daemon import Daemon, load_config, load_flows
from poieo.daemon.service import MAX_CHAIN
from poieo.errors import SpecError
from poieo.store import NullStore

_GRAPH = """\
name: quick
entry: a
nodes:
  - {id: a, type: agent, role: r, prompt: hi}
"""

_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "done"}}}
default: {provider: fake, model: m}
"""


def _config(tmp_path, flows: str, extra: str = ""):
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    path = tmp_path / "poieo.yaml"
    path.write_text(f"binding: b.yaml\n{extra}flows:\n{flows}", encoding="utf-8")
    return path


_PAIR = """\
  - name: sender
    graph: g.yaml
    then:
      - when: "run.change"
        to: receiver
        label: changed
  - name: receiver
    graph: g.yaml
    trigger: {type: manual}
"""


def test_a_then_block_carries_the_routers_own_fields(tmp_path):
    config = load_config(_config(tmp_path, _PAIR))
    sender = config.flows[0]

    assert len(sender.then) == 1
    branch = sender.then[0]
    assert (branch.when, branch.to, branch.label) == ("run.change", "receiver", "changed")


def test_a_flow_that_says_nothing_hands_off_to_nobody(tmp_path):
    config = load_config(_config(tmp_path, _PAIR))

    # Not None: every flow answers the same question, and the receiver's answer
    # is "nothing", which is the common case and must not need a special path.
    assert config.flows[1].then == []


def test_handing_off_to_a_flow_that_is_not_there_fails_at_load(tmp_path):
    flows = _PAIR.replace("to: receiver", "to: reciever")  # the typo is the point

    with pytest.raises(SpecError) as caught:
        load_config(_config(tmp_path, flows))

    said = str(caught.value)
    assert "reciever" in said and "sender" in said


def test_a_flow_cannot_hand_off_to_itself(tmp_path):
    flows = _PAIR.replace("to: receiver", "to: sender")

    with pytest.raises(SpecError, match="itself"):
        load_config(_config(tmp_path, flows))


def test_a_condition_that_does_not_compile_fails_at_load(tmp_path):
    flows = _PAIR.replace('when: "run.change"', 'when: "run.change and and"')

    with pytest.raises(SpecError) as caught:
        load_config(_config(tmp_path, flows))

    # Branch's own validator, doing the work it already does for routers --
    # which is the whole reason the block reuses it rather than redeclaring it.
    assert "run.change and and" in str(caught.value)


def test_a_branch_may_deliberately_stop(tmp_path):
    """`to: null` is the router's own null: matched, and no further."""
    flows = _PAIR.replace("to: receiver", "to: null")

    config = load_config(_config(tmp_path, flows))

    assert config.flows[0].then[0].to is None


def test_a_cycle_warns_and_still_loads(tmp_path, caplog):
    flows = _PAIR + """\
    then:
      - when: "True"
        to: sender
"""

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        config = load_config(_config(tmp_path, flows))

    said = " ".join(caplog.messages)
    assert "sender" in said and "receiver" in said
    # A feedback loop is legitimate -- the depth counter is what makes it safe.
    assert len(config.flows) == 2


def test_a_loop_triggered_sender_warns(tmp_path, caplog):
    flows = _PAIR.replace(
        "  - name: sender\n    graph: g.yaml\n",
        "  - name: sender\n    graph: g.yaml\n    trigger: {type: loop}\n",
    )

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        load_config(_config(tmp_path, flows))

    said = " ".join(caplog.messages)
    assert "loop" in said and "sender" in said


def test_handing_off_to_a_disabled_flow_warns_rather_than_fails(tmp_path, caplog):
    """`enabled: false` is the durable off switch, not a typo."""
    flows = _PAIR.replace(
        "  - name: receiver\n    graph: g.yaml\n",
        "  - name: receiver\n    graph: g.yaml\n    enabled: false\n",
    )

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        config = load_config(_config(tmp_path, flows))

    assert "receiver" in " ".join(caplog.messages)
    assert len(config.flows) == 2


def test_a_task_backed_flow_is_a_target_like_any_other(tmp_path):
    """Task cards become flows after the config validates, so the check that
    a target exists cannot live in the config's own validator."""
    cards = tmp_path / "cards"
    cards.mkdir()
    (cards / "tidy.yaml").write_text(
        "name: tidy up\nfolder: .\nprompt: tidy\n", encoding="utf-8"
    )
    flows = """\
  - name: sender
    graph: g.yaml
    then:
      - when: "True"
        to: tidy
"""

    config = load_config(_config(tmp_path, flows, extra="tasks: cards\n"))

    assert {flow.name for flow in config.flows} == {"sender", "tidy"}


# -- the handoff itself -----------------------------------------------------

_SLOW_MOCK = """\
name: slow
providers:
  fake: {type: mock, options: {latency: 0.3, responses: {"*": "done"}}}
default: {provider: fake, model: m}
"""


def _wired(tmp_path, then_block: str, *, takes: str = "hi", slow: bool = False):
    """Two manual flows -- `sender` wired to `receiver` by the given block.

    Manual on both sides so nothing fires on its own: every run in these tests
    is either a kick or a handoff, which is what makes them assertable.
    """
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "t.yaml").write_text(
        f'name: taking\nentry: t\nnodes:\n  - {{id: t, type: agent, role: taker, prompt: "{takes}"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "slow.yaml").write_text(_SLOW_MOCK, encoding="utf-8")
    path = tmp_path / "poieo.yaml"
    path.write_text(
        "binding: b.yaml\nflows:\n"
        "  - name: sender\n    graph: g.yaml\n    trigger: {type: manual}\n"
        f"{then_block}"
        "  - name: receiver\n    graph: t.yaml\n    trigger: {type: manual}\n"
        + ("    binding: slow.yaml\n" if slow else ""),
        encoding="utf-8",
    )
    return path


_TO_RECEIVER = """\
    then:
      - when: "run.status == 'completed'"
        to: receiver
        label: done
"""


async def _up(daemon):
    task = asyncio.create_task(daemon.serve(install_signals=False))
    while not daemon.runners:
        await asyncio.sleep(0.01)
    return task


async def _until(predicate, what="the condition", timeout=5.0):
    deadline = asyncio.get_running_loop().time() + timeout
    while not predicate():
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


async def _down(daemon, task):
    daemon.stop()
    return await asyncio.wait_for(task, timeout=10)


def _named(daemon, name):
    return next(r for r in daemon.runners if r.name == name)


def _calls(daemon):
    """Every request the mocks saw, whichever binding a flow used."""
    return [
        call
        for pool in daemon.pools.values()
        for provider in pool.instantiated().values()
        for call in getattr(provider, "calls", [])
    ]


async def test_a_matching_branch_starts_the_other_flow(tmp_path):
    daemon = Daemon(load_config(_wired(tmp_path, _TO_RECEIVER)), store=NullStore())
    task = await _up(daemon)
    receiver = _named(daemon, "receiver")

    assert _named(daemon, "sender").run_now() is True
    await _until(lambda: len(receiver.results) == 1, "the handoff to land")

    assert receiver.results[0].status == "completed"
    await _down(daemon, task)


async def test_a_branch_that_does_not_match_wakes_nobody(tmp_path):
    block = _TO_RECEIVER.replace("run.status == 'completed'", "run.status == 'failed'")
    daemon = Daemon(load_config(_wired(tmp_path, block)), store=NullStore())
    task = await _up(daemon)
    sender, receiver = _named(daemon, "sender"), _named(daemon, "receiver")

    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")
    await asyncio.sleep(0.2)  # long enough for a handoff to have arrived

    assert len(receiver.results) == 0
    await _down(daemon, task)


async def test_only_the_first_match_fires(tmp_path):
    """A `then:` block routes like a router: one arm, not every true one."""
    block = """\
    then:
      - when: "True"
        to: null
        label: stop
      - when: "True"
        to: receiver
        label: never
"""
    daemon = Daemon(load_config(_wired(tmp_path, block)), store=NullStore())
    task = await _up(daemon)
    sender, receiver = _named(daemon, "sender"), _named(daemon, "receiver")

    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")
    await asyncio.sleep(0.2)

    assert len(receiver.results) == 0
    await _down(daemon, task)


async def test_the_next_run_reads_what_the_last_one_did(tmp_path):
    """Waking a flow without telling it why is half a feature."""
    config = load_config(
        _wired(tmp_path, _TO_RECEIVER, takes="came from {{ input.sender.flow }}")
    )
    daemon = Daemon(config, store=NullStore())
    task = await _up(daemon)
    receiver = _named(daemon, "receiver")

    _named(daemon, "sender").run_now()
    await _until(lambda: len(receiver.results) == 1, "the handoff to land")

    # A prompt naming `input.from` cannot render without it, so completing is
    # already proof it arrived; the mock's record says it arrived filled in.
    assert receiver.results[0].status == "completed"
    asked = [c for c in _calls(daemon) if c.role == "taker"]
    assert "came from sender" in asked[0].messages[0]["content"]
    await _down(daemon, task)


async def test_the_handed_off_run_records_what_fired_it(tmp_path):
    """A run whose trigger says `manual` when a handoff started it is a lie."""
    daemon = Daemon(load_config(_wired(tmp_path, _TO_RECEIVER)), store=NullStore())
    task = await _up(daemon)
    receiver = _named(daemon, "receiver")

    _named(daemon, "sender").run_now()
    await _until(lambda: len(receiver.results) == 1, "the handoff to land")

    assert "sender" in receiver.results[0].trigger
    await _down(daemon, task)


async def test_a_handoff_arriving_mid_run_waits_and_the_newest_wins(tmp_path, caplog):
    """The interval trigger's rule, one level up: skip the middle, keep the last."""
    config = load_config(_wired(tmp_path, _TO_RECEIVER, slow=True))
    daemon = Daemon(config, store=NullStore())
    task = await _up(daemon)
    sender, receiver = _named(daemon, "sender"), _named(daemon, "receiver")

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        for _ in range(3):
            sender.run_now()
            await _until(
                lambda n=len(sender.results): len(sender.results) > n, "a sender run"
            )
        # First runs, second parks, third displaces the second.
        await _until(lambda: len(receiver.results) == 2, "both handoffs", timeout=8)
        await asyncio.sleep(0.4)

    assert len(receiver.results) == 2
    assert "dropped" in " ".join(caplog.messages)
    await _down(daemon, task)


async def test_a_paused_target_is_not_woken(tmp_path, caplog):
    """A handoff is not a reason to override a hold someone put on."""
    daemon = Daemon(load_config(_wired(tmp_path, _TO_RECEIVER)), store=NullStore())
    task = await _up(daemon)
    sender, receiver = _named(daemon, "sender"), _named(daemon, "receiver")
    receiver.pause()

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        sender.run_now()
        await _until(lambda: len(sender.results) == 1, "the sender's run")
        await asyncio.sleep(0.2)

    assert len(receiver.results) == 0
    assert "paused" in " ".join(caplog.messages)
    await _down(daemon, task)


async def test_a_chain_stops_at_the_depth_limit(tmp_path, caplog):
    """Two flows pointing at each other is legitimate; forever is not."""
    block = _TO_RECEIVER
    path = _wired(tmp_path, block)
    path.write_text(
        path.read_text(encoding="utf-8")
        + '    then:\n      - when: "True"\n        to: sender\n',
        encoding="utf-8",
    )
    daemon = Daemon(load_config(path), store=NullStore())
    task = await _up(daemon)
    sender, receiver = _named(daemon, "sender"), _named(daemon, "receiver")

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        sender.run_now()
        await _until(
            lambda: "chain" in " ".join(caplog.messages), "the chain to be cut", timeout=8
        )
        await asyncio.sleep(0.3)

    total = len(sender.results) + len(receiver.results)
    assert total <= MAX_CHAIN + 1  # the kick, then at most MAX_CHAIN handoffs
    await _down(daemon, task)


async def test_a_condition_that_cannot_be_read_skips_its_branch(tmp_path, caplog):
    """The sender has already finished and landed its change; there is nothing
    left to fail. So the branch is skipped and the next one is tried."""
    block = """\
    then:
      - when: "run.nonesuch == 1"
        to: null
        label: broken
      - when: "True"
        to: receiver
        label: fallback
"""
    daemon = Daemon(load_config(_wired(tmp_path, block)), store=NullStore())
    task = await _up(daemon)
    receiver = _named(daemon, "receiver")

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        _named(daemon, "sender").run_now()
        await _until(lambda: len(receiver.results) == 1, "the fallback branch")

    assert "nonesuch" in " ".join(caplog.messages)
    await _down(daemon, task)


# -- a role nobody declared -------------------------------------------------


def test_a_role_the_binding_never_heard_of_says_so_at_load(tmp_path, caplog):
    """One letter between the cheapest model in the file and the dearest.

    `resolve` falls back to `default` for any role at all, so a typo has always
    run -- on the big model, every night, unattended, with nothing said.
    """
    graph = (
        "name: quick\nentry: a\nnodes:\n"
        "  - {id: a, type: agent, role: classifer, prompt: hi}\n"
    )
    binding = (
        "name: mock\nproviders:\n"
        '  fake: {type: mock, options: {responses: {"*": "done"}}}\n'
        "default: {provider: fake, model: big}\n"
        "roles:\n  classifier: {model: small}\n"
    )
    (tmp_path / "g.yaml").write_text(graph, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(binding, encoding="utf-8")
    path = tmp_path / "poieo.yaml"
    path.write_text(
        "binding: b.yaml\nflows:\n  - name: f\n    graph: g.yaml\n", encoding="utf-8"
    )

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        load_flows(load_config(path))

    said = " ".join(caplog.messages)
    assert "classifer" in said and "big" in said


def test_a_binding_that_declares_no_roles_is_not_asked(tmp_path, caplog):
    """"One model for everything" is what every mock binding says, and every
    role legitimately falls through it. Warning there would be noise on the
    one setup that is meant to answer anything at all."""
    with caplog.at_level("WARNING", logger="poieo.daemon"):
        load_flows(load_config(_config(tmp_path, _PAIR)))

    assert "does not declare" not in " ".join(caplog.messages)



def test_a_node_that_names_no_role_asks_for_the_default_on_purpose(tmp_path, caplog):
    """`default_role` reaching the binding's default is the arrangement
    working, so it must not read as a typo even where roles are declared."""
    (tmp_path / "g.yaml").write_text(
        "name: quick\nentry: a\nnodes:\n  - {id: a, type: agent, prompt: hi}\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        'name: mock\nproviders:\n  fake: {type: mock, options: {responses: {"*": "x"}}}\n'
        "default: {provider: fake, model: big}\nroles:\n  classifier: {model: small}\n",
        encoding="utf-8",
    )
    path = tmp_path / "poieo.yaml"
    path.write_text(
        "binding: b.yaml\nflows:\n  - name: f\n    graph: g.yaml\n", encoding="utf-8"
    )

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        load_flows(load_config(path))

    assert "does not declare" not in " ".join(caplog.messages)
