"""Where the board listens, and what it says when that is not this machine.

`poieo daemon` bound 127.0.0.1 and nothing else, which is right by default:
DESIGN.md says this is one person's machine and that there is no auth --
"no auth" is a decision resting on "nothing outside can reach it".

Reaching it from a phone means giving that up on purpose, so the flag exists
and the daemon says out loud what it costs. What is tested here is the saying,
because a fence you can open quietly is not one.

Design: docs/daemon.md
"""

from __future__ import annotations

import pytest
from conftest import card
from typer.testing import CliRunner

from poieo.cli import app
from poieo.daemon.service import web_exposure

runner = CliRunner()


@pytest.mark.parametrize("host", ["127.0.0.1", "localhost", "::1"])
def test_the_loopback_addresses_say_nothing(host: str):
    """The default is not a decision anybody made, so it does not warn."""
    assert web_exposure(host) is None


@pytest.mark.parametrize("host", ["0.0.0.0", "100.123.217.84", "192.168.1.5", "::"])
def test_anything_else_says_what_it_costs(host: str):
    """Every route the board serves is unauthenticated, and one of them makes
    a task that can run shell commands here. The sentence has to name that,
    not merely observe that the address changed."""
    said = web_exposure(host)
    assert said is not None
    assert "no password" in said.lower() or "anyone" in said.lower()
    assert host in said


def test_the_flag_reaches_the_server(tmp_path, monkeypatch):
    """A flag the daemon reads and then ignores is the worst of both."""
    seen: dict[str, object] = {}

    class _Stub:
        def __init__(self, configs, **kwargs):
            seen.update(kwargs)

        async def serve(self):
            return []

    monkeypatch.setattr("poieo.cli.Daemon", _Stub)
    (tmp_path / "b.yaml").write_text(
        'name: mock\nproviders: {fake: {type: mock, options: {responses: {"*": "x"}}}}\n'
        "default: {provider: fake, model: m}\n",
        encoding="utf-8",
    )
    card(tmp_path / "cards", "f", "folder: .\nprompt: hi\n")
    config = tmp_path / "poieo.yaml"
    config.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")

    result = runner.invoke(app, ["daemon", str(config), "--host", "0.0.0.0", "--once"])

    assert result.exit_code == 0, result.output
    assert seen.get("web_host") == "0.0.0.0"


def test_the_default_is_still_this_machine(tmp_path, monkeypatch):
    seen: dict[str, object] = {}

    class _Stub:
        def __init__(self, configs, **kwargs):
            seen.update(kwargs)

        async def serve(self):
            return []

    monkeypatch.setattr("poieo.cli.Daemon", _Stub)
    (tmp_path / "b.yaml").write_text(
        'name: mock\nproviders: {fake: {type: mock, options: {responses: {"*": "x"}}}}\n'
        "default: {provider: fake, model: m}\n",
        encoding="utf-8",
    )
    card(tmp_path / "cards", "f", "folder: .\nprompt: hi\n")
    config = tmp_path / "poieo.yaml"
    config.write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")

    result = runner.invoke(app, ["daemon", str(config), "--once"])

    assert result.exit_code == 0, result.output
    assert seen.get("web_host") == "127.0.0.1"
