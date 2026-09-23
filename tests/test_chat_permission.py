"""What the chat may do, chosen from the chat: four settings, one card.

`read` looks and touches nothing. `ask` may edit and run commands, and asks
before each. `edits` makes edits without asking and asks before a command.
`all` asks about nothing. The board writes the choice into the chat card's
`tools` and `ask_before`; the next run reads it, and the listing says which
the card on disk holds.
"""

import httpx
import pytest
import yaml
from conftest import card, down, up
from test_web_create_card import _MOCK

from poieo.daemon import Daemon, load_config
from poieo.store import NullStore
from poieo.web import create_app

pytestmark = pytest.mark.usefixtures("daemon_lifecycle")


class _Board:
    """A running daemon with a chat card and a plain one, and a client for its board."""

    def __init__(self, tmp_path):
        (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
        (tmp_path / "work").mkdir(exist_ok=True)
        card(tmp_path / "cards", "chat", "folder: ../work\nchat: true\nprompt: Help.\ntools: [read]\n")
        card(tmp_path / "cards", "chores", "folder: ../work\nprompt: Tidy.\ntrigger: {type: manual}\n")
        path = tmp_path / "poieo.yaml"
        path.write_text("name: board\nbinding: b.yaml\ntasks: cards\n", encoding="utf-8")
        self.cards = tmp_path / "cards"
        self.daemon = Daemon(load_config(path), store=NullStore())

    async def __aenter__(self):
        self.serve = await up(self.daemon)
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(self.daemon)), base_url="http://poieo"
        )
        return self

    async def __aexit__(self, *exc):
        await self.client.aclose()
        await down(self.daemon, self.serve)

    async def rows(self):
        return {row["name"]: row for row in (await self.client.get("/api/tasks")).json()["tasks"]}


@pytest.mark.parametrize(
    ("mode", "tools", "asks"),
    [
        ("read", ["read"], []),
        ("ask", ["files", "shell"], ["edits", "commands"]),
        ("edits", ["files", "shell"], ["commands"]),
        ("all", ["files", "shell"], []),
    ],
)
async def test_each_setting_is_written_into_the_chat_card(tmp_path, mode, tools, asks):
    async with _Board(tmp_path) as board:
        answer = await board.client.post("/api/tasks/board/chat/permission", json={"mode": mode})

        assert answer.status_code == 200, answer.text
        assert answer.json() == {"permission": mode}
        written = yaml.safe_load((board.cards / "chat.yaml").read_text(encoding="utf-8"))
        assert written["tools"] == tools
        assert written.get("ask_before", []) == asks
        # Everything else on the card is as it was.
        assert written["prompt"] == "Help." and written["chat"] is True
        assert (await board.rows())["chat"]["permission"] == mode


async def test_the_listing_says_which_setting_a_chat_card_holds_and_nothing_for_other_tasks(tmp_path):
    async with _Board(tmp_path) as board:
        rows = await board.rows()

    assert rows["chat"]["permission"] == "read"
    assert rows["chores"]["permission"] is None


async def test_only_a_chat_card_is_set_this_way_and_only_to_a_known_setting(tmp_path):
    async with _Board(tmp_path) as board:
        post = board.client.post
        assert (await post("/api/tasks/board/chores/permission", json={"mode": "all"})).status_code == 409
        assert (await post("/api/tasks/board/chat/permission", json={"mode": "everything"})).status_code == 400
        assert (await post("/api/tasks/board/chat/permission", json=[])).status_code == 400


@pytest.mark.parametrize(
    ("stem", "text"),
    [
        (
            "chat.yaml",
            "name: chat\nfolder: ../work\nchat: true\nprompt: Help.  # kept short on purpose\ntools: [read]\n",
        ),
        ("chat.json", '{"name": "chat", "folder": "../work", "chat": true, "prompt": "Help.", "tools": ["read"]}'),
    ],
)
async def test_a_card_the_picker_cannot_rewrite_whole_is_left_as_it_is(tmp_path, stem, text):
    """A comment lives in the bytes, not the parse, and a JSON card is not YAML:
    rebuilt, either would lose something or stop loading. Said, and not done."""
    async with _Board(tmp_path) as board:
        await down(board.daemon, board.serve)
        (board.cards / "chat.yaml").unlink()
        (board.cards / stem).write_text(text, encoding="utf-8")
        board.daemon = Daemon(load_config(tmp_path / "poieo.yaml"), store=NullStore())
        board.serve = await up(board.daemon)
        board.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=create_app(board.daemon)), base_url="http://poieo"
        )

        answer = await board.client.post("/api/tasks/board/chat/permission", json={"mode": "all"})

        assert answer.status_code == 409
        assert "by hand" in answer.json()["error"]
        assert (board.cards / stem).read_text(encoding="utf-8") == text
