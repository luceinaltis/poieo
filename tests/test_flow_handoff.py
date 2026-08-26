"""A flow's `then:` block -- the wiring, and what has to be true of it at load.

This is the first slice of the handoff design: the block parses, a mistyped one
refuses to start, and a suspicious one says so. Nothing hands off yet.

Spec: docs/specs/2026-08-26-flow-handoff-design.md
"""

import pytest

from poieo.daemon import load_config
from poieo.errors import SpecError

_GRAPH = """\
name: quick
entry: a
nodes:
  - {id: a, type: llm, role: r, prompt: hi}
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
      - when: "true"
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
      - when: "true"
        to: tidy
"""

    config = load_config(_config(tmp_path, flows, extra="tasks: cards\n"))

    assert {flow.name for flow in config.flows} == {"sender", "tidy"}
