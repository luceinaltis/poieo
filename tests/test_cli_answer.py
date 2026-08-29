"""`poieo answer` and `poieo asking`: the terminal's half of a confirm node.

Both talk to a running daemon, because a question is state that daemon holds.
The tests stub the HTTP call rather than standing a daemon up: what is under
test here is the address, the payload, and what the user is told.
"""

import json
import httpx
import pytest
from typer.testing import CliRunner

from conftest import card
from poieo.cli import app

runner = CliRunner()


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A project to stand in, so the CLI knows which board to ask."""
    (tmp_path / "g.yaml").write_text(
        "name: q\nentry: a\nnodes:\n  - {id: a, type: agent, prompt: hi}\n",
        encoding="utf-8",
    )
    (tmp_path / "b.yaml").write_text(
        "name: mock\nproviders:\n  fake: {type: mock}\n"
        "default: {provider: fake, model: m}\n",
        encoding="utf-8",
    )
    card(tmp_path / "cards", "land", "graph: ../g.yaml\ntrigger: {type: manual}\n")
    (tmp_path / "poieo.yaml").write_text(
        "name: board\nbinding: b.yaml\ntasks: cards\n", encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _served(handler):
    """Point the CLI's HTTP calls at a handler instead of a socket.

    The base url matters: the commands ask for a path, and it is this that
    turns one into the address a real daemon answers on."""
    return httpx.Client(
        transport=httpx.MockTransport(handler), base_url="http://127.0.0.1:8484"
    )


def test_answering_posts_the_choice_to_the_task(project, monkeypatch):
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json={"status": "answered", "answer": "land"})

    monkeypatch.setattr("poieo.cli._board", lambda port: _served(handler))
    result = runner.invoke(app, ["answer", "land", "land"])

    assert result.exit_code == 0
    assert seen["url"].endswith("/api/tasks/board/land/answer")
    assert seen["body"] == {"choice": "land"}


def test_a_refused_choice_shows_the_ones_that_were_offered(project, monkeypatch):
    def handler(request):
        return httpx.Response(
            400, json={"error": "'merge' was not offered", "choices": ["land", "hold"]}
        )

    monkeypatch.setattr("poieo.cli._board", lambda port: _served(handler))
    result = runner.invoke(app, ["answer", "land", "merge"])

    assert result.exit_code != 0
    # errors go to stderr
    assert "land" in result.stderr and "hold" in result.stderr


def test_no_daemon_says_so_rather_than_a_stack_trace(project, monkeypatch):
    def handler(request):
        raise httpx.ConnectError("nothing listening")

    monkeypatch.setattr("poieo.cli._board", lambda port: _served(handler))
    result = runner.invoke(app, ["answer", "land", "land"])

    assert result.exit_code != 0
    assert "poieo daemon" in result.stderr


def test_asking_lists_what_is_waiting(project, monkeypatch):
    def handler(request):
        return httpx.Response(
            200,
            json={
                "tasks": [
                    {"name": "land", "project": "board",
                     "asking": {"run_id": "r9", "question": "Land it?",
                                "choices": ["land", "hold"]}},
                    {"name": "quiet", "project": "board", "asking": None},
                ]
            },
        )

    monkeypatch.setattr("poieo.cli._board", lambda port: _served(handler))
    result = runner.invoke(app, ["asking"])

    assert result.exit_code == 0
    assert "Land it?" in result.stdout
    assert "land/hold" in result.stdout
    assert "quiet" not in result.stdout


def test_asking_with_nothing_waiting_says_so(project, monkeypatch):
    def handler(request):
        return httpx.Response(200, json={"tasks": [{"name": "land", "asking": None}]})

    monkeypatch.setattr("poieo.cli._board", lambda port: _served(handler))
    result = runner.invoke(app, ["asking"])

    assert result.exit_code == 0
    assert "nothing" in result.stdout.lower()
