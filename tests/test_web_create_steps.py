"""Tasks written as steps use the normal graph, loader, and runtime."""

import copy
import os
from pathlib import Path

import pytest
import yaml
from test_web_create_card import _client, _make

from poieo.binding import load_binding
from poieo.card import load_card, load_cards
from poieo.graph import load_graph
from poieo.providers import ProviderPool
from poieo.runtime.executor import execute
from poieo.store import NullStore


def graph():
    return {
        "name": "review",
        "entry": "read",
        "nodes": [
            {"id": "read", "type": "agent", "prompt": "inspect", "output": {"as": "result"}, "next": "choose"},
            {
                "id": "choose",
                "type": "router",
                "branches": [{"when": 'result == "done"', "to": "finish"}],
                "default": None,
            },
            {"id": "finish", "type": "agent", "prompt": "Summarize {{ result }}"},
        ],
    }


def make_steps(client, steps=None, **extra):
    return _make(client, {"name": "review", "folder": "../work", "graph": steps or graph(), **extra})


@pytest.mark.parametrize("enabled", [True, False])
def test_steps_create_one_task_and_a_neighboring_graph(tmp_path, enabled):
    client, cards = _client(tmp_path)
    answer = make_steps(client, enabled=enabled)

    assert answer.status_code == 200, answer.text
    card = load_card(cards / "review.yaml")
    assert card.graph == "review.graph.yaml"
    assert card.folder == "../work" and card.enabled is enabled
    assert card.prompt is None
    assert load_graph(card.resolve(card.graph)).nodes[1].branches[0].to == "finish"
    assert len(load_cards(cards)) == 2  # existing task plus the new task, not its graph


async def test_a_saved_condition_selects_the_step_in_an_actual_run(tmp_path):
    client, cards = _client(tmp_path)
    answer = make_steps(client, enabled=False)
    assert answer.status_code == 200, answer.text
    binding = load_binding(tmp_path / "b.yaml")
    async with ProviderPool(binding) as pool:
        result = await execute(load_graph(cards / "review.graph.yaml"), binding, pool, NullStore())
    assert result.status == "completed", result.error
    assert result.path == ["read", "choose", "finish"]


@pytest.mark.parametrize(
    "change",
    [
        {"entry": "missing"},
        {"nodes": []},
        {"nodes": [{"id": "read", "type": "agent", "prompt": ""}]},
        {"nodes": [{"id": "read", "type": "agent", "prompt": "{{ result + }}"}]},
        {"nodes": [{"id": "read", "type": "agent", "prompt": "x", "next": "missing"}]},
        {"nodes": [{"id": "read", "type": "router", "branches": [{"when": "result =="}]}]},
        {"unknown": True},
    ],
)
def test_invalid_steps_write_neither_file(tmp_path, change):
    client, cards = _client(tmp_path)
    answer = make_steps(client, {**graph(), **change})
    assert answer.status_code == 400, answer.text
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml"]


@pytest.mark.parametrize("value", ["outside.yaml", [], 4, True])
def test_steps_must_be_a_graph_document_not_a_path(tmp_path, value):
    client, cards = _client(tmp_path)
    answer = _make(client, {"name": "review", "folder": "../work", "graph": value})
    assert answer.status_code == 400, answer.text
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml"]


def test_a_task_cannot_silently_choose_between_prompt_and_steps(tmp_path):
    client, cards = _client(tmp_path)
    answer = make_steps(client, prompt="different work")
    assert answer.status_code == 400, answer.text
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml"]


def test_each_step_uses_the_explicit_task_folder(tmp_path):
    client, cards = _client(tmp_path)
    steps = graph()
    steps["nodes"][0]["workdir"] = str(tmp_path.parent)
    answer = make_steps(client, steps)
    assert answer.status_code == 400, answer.text
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml"]


@pytest.mark.parametrize("folder", ["", "../missing", "../../"])
def test_steps_keep_the_same_folder_boundary_as_a_prompt(tmp_path, folder):
    client, cards = _client(tmp_path)
    answer = make_steps(client, folder=folder)
    assert answer.status_code == 400, answer.text
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml"]


def test_existing_graphs_are_never_overwritten(tmp_path):
    client, cards = _client(tmp_path)
    existing = cards / "review.graph.yaml"
    existing.write_text("# someone else's graph\n" + yaml.safe_dump(graph()), encoding="utf-8")
    before = existing.read_bytes()
    answer = make_steps(client)
    assert answer.status_code == 409, answer.text
    assert existing.read_bytes() == before
    assert not (cards / "review.yaml").exists()


def test_a_second_save_preserves_both_original_files(tmp_path):
    client, cards = _client(tmp_path)
    assert make_steps(client).status_code == 200
    before = {p.name: p.read_bytes() for p in cards.iterdir()}
    changed = copy.deepcopy(graph())
    changed["nodes"][0]["prompt"] = "different"
    assert make_steps(client, changed).status_code == 409
    assert {p.name: p.read_bytes() for p in cards.iterdir()} == before


def test_a_failed_card_publish_leaves_no_graph_or_scratch_file(tmp_path, monkeypatch):
    client, cards = _client(tmp_path)
    link = os.link

    def fail_card(source, target):
        if Path(target).name == "review.yaml":
            raise OSError("disk refused the card")
        return link(source, target)

    monkeypatch.setattr(os, "link", fail_card)
    answer = make_steps(client)
    assert answer.status_code == 400, answer.text
    assert sorted(p.name for p in cards.iterdir()) == ["already.yaml"]
