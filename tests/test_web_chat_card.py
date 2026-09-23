"""The board writes the project's chat card the first time the chat is used.

One per project: the conversations are its runs, grouped by thread. It starts
able only to look -- the `read` toolset -- and the chat's permission picker
widens it from there.
"""

import yaml
from test_web_create_card import _client, _make


def test_the_chat_card_is_written_to_look_and_not_touch(tmp_path):
    client, cards = _client(tmp_path)

    answer = _make(client, {"name": "chat", "folder": "../work", "prompt": "Help.", "chat": True})

    assert answer.status_code == 200, answer.text
    written = yaml.safe_load((cards / "chat.yaml").read_text(encoding="utf-8"))
    assert written["chat"] is True
    assert written["tools"] == ["read"]
    assert "every" not in written and "at" not in written


def test_the_chat_card_works_on_the_whole_project(tmp_path):
    client, cards = _client(tmp_path)

    assert _make(client, {"name": "chat", "prompt": "Help.", "chat": True}).status_code == 200

    written = yaml.safe_load((cards / "chat.yaml").read_text(encoding="utf-8"))
    assert (cards / written["folder"]).resolve() == tmp_path.resolve()


def test_a_project_has_one_chat_card(tmp_path):
    client, _ = _client(tmp_path)
    assert _make(client, {"name": "chat", "folder": "../work", "prompt": "Help.", "chat": True}).status_code == 200
    client.get("/api/tasks")  # the daemon notices the card

    again = _make(client, {"name": "talk", "folder": "../work", "prompt": "Help.", "chat": True})

    assert again.status_code == 409
    assert "already has a chat" in again.json()["error"]


def test_a_chat_card_is_not_scheduled_or_connected(tmp_path):
    client, _ = _client(tmp_path)

    scheduled = _make(client, {"name": "chat", "folder": "../work", "prompt": "Help.", "chat": True, "schedule": "1h"})
    connected = _make(
        client, {"name": "chat", "folder": "../work", "prompt": "Help.", "chat": True, "then": [{"to": "already"}]}
    )

    assert scheduled.status_code == 400
    assert connected.status_code == 400
