"""A task's `then:` block: the wiring, what must be true of it, and the handoff.

Two halves, in that order. Above the divider is what a config has to get right
before the daemon will start at all; below it is what actually happens when a
run ends -- which task wakes, what it is told, and what is refused.

Design: docs/daemon.md
"""

import asyncio

import pytest
from conftest import card

from poieo.daemon import Daemon, load_config, load_tasks
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


def _config(tmp_path, jobs: dict, extra: str = ""):
    """A card per job, keyed by the name it will answer to."""
    (tmp_path / "g.yaml").write_text(_GRAPH, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    for name, body in jobs.items():
        card(tmp_path / "cards", name, body)
    path = tmp_path / "poieo.yaml"
    path.write_text(f"binding: b.yaml\n{extra}tasks: cards\n", encoding="utf-8")
    return path


def _flow(config, name):
    """By name, never by position: cards are read in filename order."""
    return next(f for f in config.tasks if f.name == name)


_THEN = 'then:\n  - when: "run.change"\n    to: receiver\n    label: changed\n'


def _pair(then: str = _THEN, sender: str = "", receiver: str = "") -> dict:
    """Two cards wired sender -> receiver, with room to bend either one."""
    return {
        "sender": f"graph: ../g.yaml\n{sender}{then}",
        "receiver": f"graph: ../g.yaml\ntrigger: {{type: manual}}\n{receiver}",
    }


def test_a_then_block_carries_the_routers_own_fields(tmp_path):
    config = load_config(_config(tmp_path, _pair()))
    sender = _flow(config, "sender")

    assert len(sender.then) == 1
    branch = sender.then[0]
    assert (branch.when, branch.to, branch.label) == ("run.change", "receiver", "changed")


def test_a_flow_that_says_nothing_hands_off_to_nobody(tmp_path):
    config = load_config(_config(tmp_path, _pair()))

    # Not None: every task answers the same question, and the receiver's answer
    # is "nothing", which is the common case and must not need a special path.
    assert _flow(config, "receiver").then == []


def test_handing_off_to_a_flow_that_is_not_there_fails_at_load(tmp_path):
    jobs = _pair(_THEN.replace("to: receiver", "to: reciever"))  # the typo is the point

    with pytest.raises(SpecError) as caught:
        load_config(_config(tmp_path, jobs))

    said = str(caught.value)
    assert "reciever" in said and "sender" in said


def test_a_flow_cannot_hand_off_to_itself(tmp_path):
    jobs = _pair(_THEN.replace("to: receiver", "to: sender"))

    with pytest.raises(SpecError, match="itself"):
        load_config(_config(tmp_path, jobs))


def test_a_condition_that_does_not_compile_fails_at_load(tmp_path):
    jobs = _pair(_THEN.replace('when: "run.change"', 'when: "run.change and and"'))

    with pytest.raises(SpecError) as caught:
        load_config(_config(tmp_path, jobs))

    # Branch's own validator, doing the work it already does for routers --
    # which is the whole reason the block reuses it rather than redeclaring it.
    assert "run.change and and" in str(caught.value)


def test_a_branch_may_deliberately_stop(tmp_path):
    """`to: null` is the router's own null: matched, and no further."""
    jobs = _pair(_THEN.replace("to: receiver", "to: null"))

    config = load_config(_config(tmp_path, jobs))

    assert _flow(config, "sender").then[0].to is None


def test_a_cycle_warns_and_still_loads(tmp_path, caplog):
    jobs = _pair(receiver='then:\n  - when: "True"\n    to: sender\n')

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        config = load_config(_config(tmp_path, jobs))

    said = " ".join(caplog.messages)
    assert "sender" in said and "receiver" in said
    # A feedback loop is legitimate -- the depth counter is what makes it safe.
    assert len(config.tasks) == 2


def test_a_loop_triggered_sender_warns(tmp_path, caplog):
    jobs = _pair(sender="trigger: {type: loop}\n")

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        load_config(_config(tmp_path, jobs))

    said = " ".join(caplog.messages)
    assert "loop" in said and "sender" in said


def test_handing_off_to_a_disabled_flow_warns_rather_than_fails(tmp_path, caplog):
    """`enabled: false` is the durable off switch, not a typo."""
    jobs = _pair(receiver="enabled: false\n")

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        config = load_config(_config(tmp_path, jobs))

    assert "receiver" in " ".join(caplog.messages)
    assert len(config.tasks) == 2


def test_a_prompt_shaped_card_is_a_target_like_any_other(tmp_path):
    """Cards become tasks only after the config validates, so the check that a
    target exists cannot live in the config's own validator."""
    jobs = {
        "sender": 'graph: ../g.yaml\nthen:\n  - when: "True"\n    to: tidy\n',
        "tidy": "folder: .\nprompt: tidy\n",
    }

    config = load_config(_config(tmp_path, jobs))

    assert {task.name for task in config.tasks} == {"sender", "tidy"}


# -- the handoff itself -----------------------------------------------------

_SLOW_MOCK = """\
name: slow
providers:
  fake: {type: mock, options: {latency: 0.3, responses: {"*": "done"}}}
default: {provider: fake, model: m}
"""


def _wired(
    tmp_path,
    then_block: str,
    *,
    takes: str = "hi",
    slow: bool = False,
    sender_graph: str = _GRAPH,
):
    """Two manual tasks -- `sender` wired to `receiver` by the given block.

    Manual on both sides so nothing fires on its own: every run in these tests
    is either a kick or a handoff, which is what makes them assertable.
    """
    (tmp_path / "g.yaml").write_text(sender_graph, encoding="utf-8")
    (tmp_path / "t.yaml").write_text(
        f'name: taking\nentry: t\nnodes:\n  - {{id: t, type: agent, role: taker, prompt: "{takes}"}}\n',
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "slow.yaml").write_text(_SLOW_MOCK, encoding="utf-8")
    card(
        tmp_path / "cards",
        "sender",
        f"graph: ../g.yaml\ntrigger: {{type: manual}}\n{then_block}",
    )
    card(
        tmp_path / "cards",
        "receiver",
        "graph: ../t.yaml\ntrigger: {type: manual}\n"
        + ("binding: ../slow.yaml\n" if slow else ""),
    )
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
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
    """Every request the mocks saw, whichever binding a task used."""
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


# A node whose output answers to a name of its own -- which is what almost
# every graph does to the value its `then:` is about.
_ALIASED = """\
name: quick
entry: a
nodes:
  - {id: a, type: agent, role: r, prompt: hi, output: {as: verdict}}
"""


async def test_a_then_block_reads_an_output_by_the_name_the_graph_gave_it(tmp_path):
    """The alias a router reads inside the run, read by `then:` outside it.

    `outputs` is keyed by node id, so an output aliased `verdict` on a node
    called `a` was `verdict` everywhere inside the graph and reachable by no
    spelling at all once the run had ended -- and it is the value a handoff is
    most often about. The condition below is exactly what a router one level
    down would have been given.
    """
    block = _TO_RECEIVER.replace("run.status == 'completed'", "verdict == 'done'")
    daemon = Daemon(
        load_config(_wired(tmp_path, block, sender_graph=_ALIASED)), store=NullStore()
    )
    task = await _up(daemon)
    receiver = _named(daemon, "receiver")

    assert _named(daemon, "sender").run_now() is True
    await _until(lambda: len(receiver.results) == 1, "the handoff to land")
    await _down(daemon, task)


async def test_an_alias_cannot_shadow_the_run_it_describes(tmp_path):
    """The same `setdefault` rule a graph's own scope follows, one level up.

    A graph may name an output anything, `run` included, and a `then:` whose
    `run.status` had quietly become a node's completion text would be the
    quietest possible bug -- the block is skipped on an unreadable condition,
    so it would simply never fire again.
    """
    shadow = _ALIASED.replace("as: verdict", "as: run")
    daemon = Daemon(
        load_config(_wired(tmp_path, _TO_RECEIVER, sender_graph=shadow)),
        store=NullStore(),
    )
    task = await _up(daemon)
    receiver = _named(daemon, "receiver")

    # `run.status == 'completed'` still reads the run, not the string "done".
    assert _named(daemon, "sender").run_now() is True
    await _until(lambda: len(receiver.results) == 1, "the handoff to land")
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
    """Waking a task without telling it why is half a feature."""
    config = load_config(
        _wired(tmp_path, _TO_RECEIVER, takes="came from {{ input.sender.task }}")
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
    """Two tasks pointing at each other is legitimate; forever is not."""
    path = _wired(tmp_path, _TO_RECEIVER)
    back = tmp_path / "cards" / "receiver.yaml"
    back.write_text(
        back.read_text(encoding="utf-8")
        + 'then:\n  - when: "True"\n    to: sender\n',
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
    card(tmp_path / "cards", "f", "graph: ../g.yaml\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        load_tasks(load_config(path))

    said = " ".join(caplog.messages)
    assert "classifer" in said and "big" in said


def test_a_binding_that_declares_no_roles_is_not_asked(tmp_path, caplog):
    """"One model for everything" is what every mock binding says, and every
    role legitimately falls through it. Warning there would be noise on the
    one setup that is meant to answer anything at all."""
    with caplog.at_level("WARNING", logger="poieo.daemon"):
        load_tasks(load_config(_config(tmp_path, _pair())))

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
    card(tmp_path / "cards", "f", "graph: ../g.yaml\n")
    path = tmp_path / "poieo.yaml"
    path.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        load_tasks(load_config(path))

    assert "does not declare" not in " ".join(caplog.messages)


async def test_a_card_can_hand_off_on_what_the_run_spent(tmp_path):
    """The same guard one level up. A chain is bounded by MAX_CHAIN hops, which
    says nothing about what those hops cost -- and a card that spends its way
    through the night hands the next one a bill, not a reason to stop."""
    block = _TO_RECEIVER.replace(
        "run.status == 'completed'", "run.usage.output_tokens < 1000"
    )
    daemon = Daemon(load_config(_wired(tmp_path, block)), store=NullStore())
    task = await _up(daemon)
    receiver = _named(daemon, "receiver")

    assert _named(daemon, "sender").run_now() is True
    await _until(lambda: len(receiver.results) == 1, "the handoff to land")

    await _down(daemon, task)


async def test_a_card_that_spent_too_much_wakes_nobody(tmp_path, caplog):
    """The threshold is read, not assumed.

    The log matters as much as the count here: an unreadable condition is also
    treated as no match, so "nobody was woken" on its own cannot tell a guard
    that held from a name the scope never had.
    """
    block = _TO_RECEIVER.replace(
        "run.status == 'completed'", "run.usage.output_tokens > 1000"
    )
    daemon = Daemon(load_config(_wired(tmp_path, block)), store=NullStore())
    task = await _up(daemon)
    sender, receiver = _named(daemon, "sender"), _named(daemon, "receiver")

    with caplog.at_level("WARNING", logger="poieo.daemon"):
        sender.run_now()
        await _until(lambda: len(sender.results) == 1, "the sender's run")
        await asyncio.sleep(0.2)  # long enough for a handoff to have arrived

    assert len(receiver.results) == 0
    assert caplog.messages == []
    await _down(daemon, task)


_ASKING = """\
name: quick
entry: a
nodes:
  - {id: a, type: agent, role: r, prompt: hi, next: ask}
  - id: ask
    type: confirm
    prompt: "Land it?"
    choices: [land, hold]
"""

_ON_ANSWER = """\
then:
  - when: "run.answer == 'land'"
    to: receiver
    label: approved
"""


def _asking_pair(tmp_path):
    """A sender whose graph ends by asking, wired to fire only on `land`."""
    path = _wired(tmp_path, _ON_ANSWER)
    (tmp_path / "g.yaml").write_text(_ASKING, encoding="utf-8")
    return path


async def test_a_run_waiting_on_a_person_hands_off_to_nobody(tmp_path, caplog):
    """The whole point. `then:` is deferred, not skipped -- nothing downstream
    moves until somebody says so."""
    daemon = Daemon(load_config(_asking_pair(tmp_path)), store=NullStore())
    task = await _up(daemon)
    sender, receiver = _named(daemon, "sender"), _named(daemon, "receiver")

    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")
    await asyncio.sleep(0.2)  # long enough for a handoff to have arrived

    assert len(receiver.results) == 0
    assert "no 'usage' here" not in caplog.text
    assert sender.results[0].status == "asking"
    assert sender.results[0].asked["question"] == "Land it?"
    assert len(receiver.results) == 0
    # Deferred, and not merely unreadable: a `then:` that raised on the missing
    # name would also wake nobody, and would be the wrong reason.
    assert "no 'answer' here" not in caplog.text
    await _down(daemon, task)


async def test_answering_lets_the_chain_carry_on(tmp_path):
    daemon = Daemon(load_config(_asking_pair(tmp_path)), store=NullStore())
    task = await _up(daemon)
    sender, receiver = _named(daemon, "sender"), _named(daemon, "receiver")

    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")

    assert sender.answer("land") is True
    await _until(lambda: len(receiver.results) == 1, "the handoff to land")

    assert sender.results[0].answer == "land"
    await _down(daemon, task)


async def test_the_other_answer_wakes_nobody(tmp_path):
    """A decision, not a formality: `hold` is an answer and it stops here."""
    daemon = Daemon(load_config(_asking_pair(tmp_path)), store=NullStore())
    task = await _up(daemon)
    sender, receiver = _named(daemon, "sender"), _named(daemon, "receiver")

    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")

    assert sender.answer("hold") is True
    await asyncio.sleep(0.2)

    assert len(receiver.results) == 0
    await _down(daemon, task)


async def test_an_answer_that_was_not_offered_is_refused(tmp_path):
    """Only what the node offered. Anything else is somebody guessing, which
    is the reading this node exists to replace."""
    daemon = Daemon(load_config(_asking_pair(tmp_path)), store=NullStore())
    task = await _up(daemon)
    sender = _named(daemon, "sender")

    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")

    assert sender.answer("merge") is False
    assert sender.results[0].status == "asking"
    await _down(daemon, task)


async def test_answering_a_task_that_asked_nothing_is_refused(tmp_path):
    daemon = Daemon(load_config(_wired(tmp_path, _TO_RECEIVER)), store=NullStore())
    task = await _up(daemon)

    assert _named(daemon, "sender").answer("land") is False
    await _down(daemon, task)


async def test_unanswered_questions_are_not_failures(tmp_path):
    """A card that asks every night must not pause itself for asking. Nothing
    failed: it ran, and it is waiting."""
    from poieo.daemon.service import PAUSE_AFTER

    daemon = Daemon(load_config(_asking_pair(tmp_path)), store=NullStore())
    task = await _up(daemon)
    sender = _named(daemon, "sender")

    for n in range(PAUSE_AFTER + 1):
        sender.run_now()
        await _until(lambda: len(sender.results) == n + 1, f"run {n + 1}")

    assert sender.holding is False
    await _down(daemon, task)


async def test_an_answer_is_written_down(tmp_path):
    """The answer rewrites the run's record -- from `asking` to `completed` --
    so something has to say why. A record that changed with no event behind it
    is the one thing this project's log is for."""
    from poieo.store import RunStore

    store = RunStore(tmp_path / "runs")
    daemon = Daemon(load_config(_asking_pair(tmp_path)), store=store)
    task = await _up(daemon)
    sender = _named(daemon, "sender")

    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")
    sender.answer("land")

    kinds = [e["type"] for e in store.events(sender.results[0].run_id)]
    assert "run_asking" in kinds
    assert "run_answered" in kinds
    answered = next(e for e in store.events(sender.results[0].run_id)
                    if e["type"] == "run_answered")
    assert answered["data"]["answer"] == "land"
    await _down(daemon, task)


async def test_a_question_survives_the_daemon(tmp_path):
    """A question is worth nothing if a restart eats it. The card would have to
    be run again to ask it, and the run that raised it is already gone."""
    config = _asking_pair(tmp_path)

    first = Daemon(load_config(config), store=NullStore())
    task = await _up(first)
    sender = _named(first, "sender")
    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")
    asked_run = sender.results[0].run_id
    await _down(first, task)

    second = Daemon(load_config(config), store=NullStore())
    task = await _up(second)
    restored = _named(second, "sender").asking()

    assert restored is not None
    assert restored.run_id == asked_run
    assert restored.asked["question"] == "Land it?"
    await _down(second, task)


async def test_an_answer_after_a_restart_still_carries_the_chain_on(tmp_path):
    """Restored well enough to be acted on, not merely displayed: the branch
    reads the run's outputs, so a husk with the right run_id is not enough."""
    config = _asking_pair(tmp_path)

    first = Daemon(load_config(config), store=NullStore())
    task = await _up(first)
    sender = _named(first, "sender")
    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")
    await _down(first, task)

    second = Daemon(load_config(config), store=NullStore())
    task = await _up(second)
    receiver = _named(second, "receiver")

    assert _named(second, "sender").answer("land") is True
    await _until(lambda: len(receiver.results) == 1, "the handoff to land")
    await _down(second, task)


async def test_an_answered_question_is_not_asked_again(tmp_path):
    """Answering clears it. Otherwise every restart re-opens a decision that
    was already made -- and the chain it fires would run twice."""
    config = _asking_pair(tmp_path)

    first = Daemon(load_config(config), store=NullStore())
    task = await _up(first)
    sender = _named(first, "sender")
    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")
    sender.answer("hold")
    await _down(first, task)

    second = Daemon(load_config(config), store=NullStore())
    task = await _up(second)

    assert _named(second, "sender").asking() is None
    await _down(second, task)


async def test_answering_updates_what_the_board_will_show(tmp_path):
    """The run list is read from the index. Left alone it would show a run as
    waiting on somebody for good, after they had already decided."""
    from poieo.store import RunStore

    store = RunStore(tmp_path / "runs")
    daemon = Daemon(load_config(_asking_pair(tmp_path)), store=store)
    task = await _up(daemon)
    sender = _named(daemon, "sender")

    sender.run_now()
    await _until(lambda: len(sender.results) == 1, "the sender's run")
    assert store.summary(sender.results[0].run_id)["status"] == "asking"

    sender.answer("land")

    listed = [row for row in store.list_runs() if row["task"] == "sender"]
    assert len(listed) == 1
    assert listed[0]["status"] == "completed"
    await _down(daemon, task)
