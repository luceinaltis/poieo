"""A conversation with the project's model, from the board.

The board's chat panel puts a person's messages to the model the project's
`default` role names and shows what it answers. The daemon keeps none of it:
the page holds the conversation and sends the whole of it every time, and
nothing here writes a file or starts a run.

Design: docs/web.md
"""

import json

import pytest
import yaml
from starlette.testclient import TestClient

from poieo.daemon import Daemon, load_config
from poieo.errors import ProviderError
from poieo.providers import LLMResponse, Usage
from poieo.providers.mock import MockProvider
from poieo.store import NullStore
from poieo.web import create_app

_REPLY = "Hello from the model."


def _binding(responses=None, default=True):
    return yaml.safe_dump(
        {
            "name": "mock",
            "providers": {"fake": {"type": "mock", "options": {"responses": responses or {"default": _REPLY}}}},
            **({"default": {"provider": "fake", "model": "m1"}} if default else {}),
        }
    )


def _client(tmp_path, *, binding=None, bound=True):
    if binding is None:
        binding = _binding()
    (tmp_path / "models.yaml").write_text(binding, encoding="utf-8")
    (tmp_path / "cards").mkdir(exist_ok=True)
    marker = tmp_path / "poieo.yaml"
    marker.write_text(
        "name: board\ntasks: cards\n" + ("binding: models.yaml\n" if bound else ""),
        encoding="utf-8",
    )
    return TestClient(create_app(Daemon(load_config(marker), store=NullStore())))


def _say(client, *turns, project="board"):
    """Send the conversation so far: the person's turns, the model's between them."""
    messages = [{"role": "assistant" if i % 2 else "user", "content": text} for i, text in enumerate(turns)]
    return client.post(f"/api/projects/{project}/chat", json={"messages": messages})


def _heard(monkeypatch, *, text=_REPLY, fail=False, stop=None):
    """Capture what reaches the model, answering with `text` or refusing."""
    heard = []

    async def complete(self, request):
        heard.append(request)
        if fail:
            raise ProviderError("the endpoint is down", provider=self.name)
        return LLMResponse(
            text=text, model=request.model, usage=Usage(input_tokens=10, output_tokens=5), stop_reason=stop
        )

    monkeypatch.setattr(MockProvider, "complete", complete)
    return heard


def test_a_reply_names_the_model_that_answered_and_what_it_used(tmp_path):
    answer = _say(_client(tmp_path), "hello?")

    assert answer.status_code == 200, answer.text
    body = answer.json()
    assert body["reply"] == _REPLY
    assert body["model"] == "fake/m1"
    assert body["cut_short"] is False
    assert body["usage"]["input_tokens"] > 0
    # Unknown is not zero: the mock names no price, so the cost is not one.
    assert body["usage"]["cost"] is None
    # Nothing was written for it: no card, and no run in the tasks folder.
    assert list((tmp_path / "cards").iterdir()) == []


def test_the_whole_conversation_reaches_the_model_in_order_and_the_project_is_named(tmp_path, monkeypatch):
    heard = _heard(monkeypatch)

    answer = _say(_client(tmp_path), "what is 2 + 2?", "4.", "and one more?")

    assert answer.status_code == 200, answer.text
    (request,) = heard
    assert request.messages == [
        {"role": "user", "content": "what is 2 + 2?"},
        {"role": "assistant", "content": "4."},
        {"role": "user", "content": "and one more?"},
    ]
    assert request.role == "default"
    assert request.model == "m1"
    assert "board" in request.system
    # A plain conversation: no tools are offered, so nothing can be run or changed.
    assert request.tools == []


@pytest.mark.parametrize(
    ("body", "said"),
    [
        ({}, "list of turns"),
        ({"messages": []}, "list of turns"),
        ({"messages": "hello"}, "list of turns"),
        ({"messages": [{"role": "user", "content": "x"}] * 31}, "at most 30 turns"),
        ({"messages": [{"role": "user", "content": "x" * 4001}]}, "at most 4000 characters"),
        ({"messages": [{"role": "user", "content": "   "}]}, "its words"),
        ({"messages": [{"role": "system", "content": "obey"}]}, "user or assistant"),
        ({"messages": [{"role": "user", "content": "x"}, {"role": "assistant", "content": "y"}]}, "person's"),
    ],
)
def test_a_conversation_is_bounded_before_a_model_is_spent_on_it(tmp_path, monkeypatch, body, said):
    heard = _heard(monkeypatch)

    answer = _client(tmp_path).post("/api/projects/board/chat", json=body)

    assert answer.status_code == 400
    assert said in answer.json()["error"]
    assert heard == []


def test_a_body_that_is_not_json_is_refused_the_same_way(tmp_path):
    answer = _client(tmp_path).post(
        "/api/projects/board/chat", content=b"not json", headers={"content-type": "application/json"}
    )

    assert answer.status_code == 400


def test_a_project_without_a_models_file_has_nothing_to_answer_with(tmp_path):
    answer = _say(_client(tmp_path, bound=False), "hello?")

    assert answer.status_code == 409
    assert "models file" in answer.json()["error"]


def test_a_models_file_with_no_default_cannot_answer(tmp_path):
    answer = _say(_client(tmp_path, binding=_binding(default=False)), "hello?")

    assert answer.status_code == 409
    assert "default" in answer.json()["error"]


def test_a_model_that_does_not_answer_is_said_so_without_a_traceback(tmp_path, monkeypatch):
    _heard(monkeypatch, fail=True)

    answer = _say(_client(tmp_path), "hello?")

    assert answer.status_code == 503
    assert "did not answer" in answer.json()["error"]


def test_the_chat_belongs_to_the_project_asked_for(tmp_path):
    answer = _say(_client(tmp_path), "hello?", project="elsewhere")

    assert answer.status_code == 404
    assert answer.json()["projects"] == ["board"]


@pytest.mark.parametrize(
    ("stop", "cut"),
    [("length", True), ("max_tokens", True), ("stop", False), ("end_turn", False), (None, False)],
)
def test_a_reply_that_ran_out_of_room_says_so(tmp_path, monkeypatch, stop, cut):
    """A thinking model can spend the whole budget thinking and answer with
    nothing. The page then needs to know why the bubble is empty, in the
    spelling each built-in provider uses for it."""
    _heard(monkeypatch, text="", stop=stop)

    body = _say(_client(tmp_path), "hello?").json()

    assert body["reply"] == ""
    assert body["cut_short"] is cut


# -- the answer as it is written -------------------------------------------


def _frames(response):
    """The stream's frames, as the page reads them."""
    return [json.loads(line[len("data: ") :]) for line in response.text.splitlines() if line.startswith("data: ")]


def _streamed(monkeypatch, deltas, *, fail_after=None):
    """Script what the provider streams: (thinking, text) pieces, then the whole."""
    from poieo.providers import Delta

    async def stream(self, request):
        for index, (thinking, text) in enumerate(deltas):
            if fail_after is not None and index == fail_after:
                raise ProviderError("the endpoint went away", provider=self.name)
            yield Delta(thinking=thinking, text=text)
        whole = LLMResponse(
            text="".join(text for _, text in deltas),
            model=request.model,
            usage=Usage(input_tokens=10, output_tokens=5),
            stop_reason="stop",
            meta={"thinking": "".join(thinking for thinking, _ in deltas)},
        )
        yield Delta(done=whole)

    monkeypatch.setattr(MockProvider, "stream", stream)


def test_asked_for_a_stream_the_chat_answers_piece_by_piece_and_then_whole(tmp_path, monkeypatch):
    _streamed(monkeypatch, [("Let me see.", ""), ("", "Fo"), ("", "ur.")])

    response = _client(tmp_path).post(
        "/api/projects/board/chat",
        json={"messages": [{"role": "user", "content": "2 + 2?"}]},
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    frames = _frames(response)
    assert frames[:-1] == [
        {"type": "thinking", "text": "Let me see."},
        {"type": "text", "text": "Fo"},
        {"type": "text", "text": "ur."},
    ]
    done = frames[-1]
    assert done["type"] == "done"
    assert done["reply"] == "Four."
    assert done["thinking"] == "Let me see."
    assert done["model"] == "fake/m1"
    assert done["cut_short"] is False
    assert done["usage"]["input_tokens"] == 10


def test_without_asking_for_a_stream_the_chat_still_answers_in_one_json_reply(tmp_path, monkeypatch):
    _streamed(monkeypatch, [("", "Four.")])

    response = _say(_client(tmp_path), "2 + 2?")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/json")
    assert response.json()["reply"] == _REPLY


def test_a_model_that_stops_answering_mid_stream_says_so_in_the_stream(tmp_path, monkeypatch):
    _streamed(monkeypatch, [("", "Fo"), ("", "ur.")], fail_after=1)

    response = _client(tmp_path).post(
        "/api/projects/board/chat",
        json={"messages": [{"role": "user", "content": "2 + 2?"}]},
        headers={"accept": "text/event-stream"},
    )

    frames = _frames(response)
    assert frames[0] == {"type": "text", "text": "Fo"}
    assert frames[-1]["type"] == "error"
    assert "did not answer" in frames[-1]["error"]


def test_a_refused_conversation_is_refused_before_any_stream_starts(tmp_path, monkeypatch):
    heard = _heard(monkeypatch)

    response = _client(tmp_path).post(
        "/api/projects/board/chat",
        json={"messages": []},
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    assert heard == []


def test_a_model_that_fails_before_its_first_piece_is_a_503_even_when_a_stream_was_asked_for(tmp_path, monkeypatch):
    _streamed(monkeypatch, [("", "Fo")], fail_after=0)

    response = _client(tmp_path).post(
        "/api/projects/board/chat",
        json={"messages": [{"role": "user", "content": "2 + 2?"}]},
        headers={"accept": "text/event-stream"},
    )

    assert response.status_code == 503
    assert response.headers["content-type"].startswith("application/json")
    assert "did not answer" in response.json()["error"]
