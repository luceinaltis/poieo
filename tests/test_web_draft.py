"""A model drafts a task card from a conversation, for the board's form.

The new-task panel lets a person describe the work in their own words. The
daemon puts that conversation to a model, together with what the project has
-- its folders spelled as a card spells them, and the tasks it already runs --
and hands back the reply and, when the model proposed one, a card the form can
fill itself from. Nothing is written: the card still goes through the form and
its one save, and the folder stays the person's choice.

Design: docs/web.md
"""

import yaml
from conftest import card
from starlette.testclient import TestClient

from poieo.daemon import Daemon, load_config
from poieo.errors import ProviderError
from poieo.providers import LLMResponse, Usage
from poieo.providers.mock import MockProvider
from poieo.store import NullStore
from poieo.web import create_app

_CARD = (
    '{"name": "nightly test fix", "folder": "../src", '
    '"prompt": "Run the tests. Fix one failure.", "schedule": "0 2 * * *"}'
)
_REPLY = f"Here is a card for that.\n\n```poieo-task\n{_CARD}\n```\n"


def _binding(responses, roles=None):
    return yaml.safe_dump(
        {
            "name": "mock",
            "providers": {"fake": {"type": "mock", "options": {"responses": responses}}},
            "default": {"provider": "fake", "model": "m1"},
            **({"roles": roles} if roles else {}),
        }
    )


def _client(tmp_path, *, responses=None, roles=None):
    (tmp_path / "models.yaml").write_text(
        _binding({"task_writer": _REPLY} if responses is None else responses, roles), encoding="utf-8"
    )
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "work").mkdir(exist_ok=True)
    card(tmp_path / "cards", "keep-tidy", "folder: ../work\nprompt: tidy\nevery: 1h\n")
    marker = tmp_path / "poieo.yaml"
    marker.write_text("name: board\ntasks: cards\nbinding: models.yaml\n", encoding="utf-8")
    return TestClient(create_app(Daemon(load_config(marker), store=NullStore())))


def _ask(client, *turns, project="board"):
    messages = [{"role": "assistant" if i % 2 else "user", "content": text} for i, text in enumerate(turns)]
    return client.post(f"/api/projects/{project}/tasks/draft", json={"messages": messages})


def _said(monkeypatch, *, text=_REPLY, fail=False):
    """Capture what reaches the model, answering with `text` or refusing."""
    heard = []

    async def complete(self, request):
        heard.append(request)
        if fail:
            raise ProviderError("the endpoint is down", provider=self.name)
        return LLMResponse(text=text, model=request.model, usage=Usage(input_tokens=10, output_tokens=5))

    monkeypatch.setattr(MockProvider, "complete", complete)
    return heard


def test_a_reply_carries_its_card_and_the_fence_is_not_in_the_prose(tmp_path):
    """The prose is for the person and the card is for the form, so the
    fenced block the model was asked to write is taken out of the one and
    handed over as the other."""
    answer = _ask(_client(tmp_path), "every night run the tests in src and fix one failure")

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["reply"] == "Here is a card for that."
    assert body["draft"] == {
        "name": "nightly test fix",
        "folder": "../src",
        "prompt": "Run the tests. Fix one failure.",
        "schedule": "0 2 * * *",
    }
    assert body["model"] == "fake/m1"


def test_a_card_written_as_yaml_inside_the_fence_is_read_too(tmp_path):
    reply = "Try this.\n\n```poieo-task\nname: tidy docs\nfolder: ..\nprompt: |\n  Tidy the docs.\nschedule: 2h\n```\n"
    body = _ask(_client(tmp_path, responses={"task_writer": reply}), "tidy the docs").json()

    assert body["reply"] == "Try this."
    assert body["draft"] == {"name": "tidy docs", "folder": "..", "prompt": "Tidy the docs.", "schedule": "2h"}


def test_a_reply_with_no_card_is_prose_and_nothing_to_fill(tmp_path):
    body = _ask(_client(tmp_path, responses={"task_writer": "Which folder should it work in?"}), "fix things").json()

    assert body["reply"] == "Which folder should it work in?"
    assert body["draft"] is None


def test_a_folder_outside_the_project_is_left_for_the_person_to_choose(tmp_path):
    """The folder is the one thing the model's hands will touch, and a card
    made from the board may only name a folder inside its project. A draft
    naming anything else arrives with the folder blank and the rest kept, so
    the form fills what it can and the person still picks the place."""
    outside = _CARD.replace("../src", "../../elsewhere")
    body = _ask(_client(tmp_path, responses={"task_writer": f"```poieo-task\n{outside}\n```"}), "fix").json()
    assert body["draft"]["folder"] == ""
    assert body["draft"]["prompt"] == "Run the tests. Fix one failure."

    missing = _CARD.replace("../src", "../nowhere")
    body = _ask(_client(tmp_path, responses={"task_writer": f"```poieo-task\n{missing}\n```"}), "fix").json()
    assert body["draft"]["folder"] == ""


def test_a_schedule_the_card_could_not_take_is_dropped_rather_than_refused(tmp_path):
    odd = _CARD.replace("0 2 * * *", "whenever")
    body = _ask(_client(tmp_path, responses={"task_writer": f"```poieo-task\n{odd}\n```"}), "fix").json()

    assert body["draft"]["schedule"] == ""
    assert body["draft"]["name"] == "nightly test fix"


def test_a_card_without_a_name_or_a_prompt_is_not_a_draft(tmp_path):
    nameless = '```poieo-task\n{"folder": "..", "prompt": "x"}\n```'
    assert _ask(_client(tmp_path, responses={"task_writer": nameless}), "fix").json()["draft"] is None

    broken = "```poieo-task\n{not json: [\n```"
    body = _ask(_client(tmp_path, responses={"task_writer": broken}), "fix").json()
    assert body["draft"] is None
    # The fence stays in the prose when it could not be read, so the person
    # sees what the model wrote rather than nothing.
    assert "not json" in body["reply"]


def test_the_model_is_told_the_folders_and_the_tasks_this_project_has(tmp_path, monkeypatch):
    """What the model hears: the folders a card may name, spelled as the card
    spells them, the tasks already on the board, and the whole conversation
    in order under the drafting role."""
    heard = _said(monkeypatch)
    client = _client(tmp_path)

    assert _ask(client, "fix the tests", "Which folder?", "src").status_code == 200
    request = heard[0]
    assert request.role == "task_writer"
    assert ".." in request.system and "../src" in request.system and "../work" in request.system
    assert "keep-tidy" in request.system and "every 1h" in request.system
    assert [m["role"] for m in request.messages] == ["user", "assistant", "user"]
    assert [m["content"] for m in request.messages] == ["fix the tests", "Which folder?", "src"]


def test_the_task_writer_role_falls_through_to_the_project_default(tmp_path):
    """Unlike the memory board's roles, this one may resolve through
    `default`: a person typed the message and pressed the button, and the
    answer names the model that replied. Naming `task_writer` in the models
    file moves the conversation to another model without touching tasks."""
    fallback = _client(tmp_path, responses={"*": "Tell me more."})
    body = _ask(fallback, "help").json()
    assert body["reply"] == "Tell me more." and body["model"] == "fake/m1"

    named = _client(
        tmp_path,
        responses={"task_writer": "From the writer."},
        roles={"task_writer": {"provider": "fake", "model": "m2"}},
    )
    body = _ask(named, "help").json()
    assert body["reply"] == "From the writer." and body["model"] == "fake/m2"


def test_a_conversation_is_a_bounded_list_of_turns_ending_with_the_person(tmp_path):
    client = _client(tmp_path)
    draft = "/api/projects/board/tasks/draft"

    assert client.post(draft, json={"messages": []}).status_code == 400
    assert client.post(draft, json={"messages": "hello"}).status_code == 400
    assert client.post(draft, json={"messages": [{"role": "user"}]}).status_code == 400
    assert client.post(draft, json={"messages": [{"role": "system", "content": "x"}]}).status_code == 400
    assert client.post(draft, json={"messages": [{"role": "user", "content": " "}]}).status_code == 400
    assert _ask(client, "fix", "Which folder?").status_code == 400
    assert _ask(client, "x" * 4001).status_code == 400
    assert _ask(client, *(["a", "b"] * 20 + ["a"])).status_code == 400
    assert _ask(client, *(["a", "b"] * 14 + ["a"])).status_code == 200
    assert "error" in client.post(draft, json={"messages": []}).json()


def test_a_model_that_cannot_answer_is_said_so_without_a_crash(tmp_path, monkeypatch):
    _said(monkeypatch, fail=True)
    answer = _ask(_client(tmp_path), "fix")

    assert answer.status_code == 503
    assert "answer" in answer.json()["error"]


def test_drafting_writes_nothing_and_names_only_this_project(tmp_path):
    client = _client(tmp_path)
    assert _ask(client, "fix", project="elsewhere").status_code == 404

    assert _ask(client, "fix").status_code == 200
    assert sorted(p.name for p in (tmp_path / "cards").iterdir()) == ["keep-tidy.yaml"]
