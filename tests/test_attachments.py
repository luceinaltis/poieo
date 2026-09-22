"""What a person attaches to a message: checked at the door, kept with the run,
and shown to the model beside what they said.

A picture goes to the model as a picture and a text file as its words; either
is kept under the run's record, so the board can show it again later.
"""

from __future__ import annotations

import base64

import httpx
import pytest
from conftest import card, down, until, up

from poieo.attachments import Attachment, attachment_blocks, checked_attachments
from poieo.daemon import Daemon, load_config
from poieo.errors import SpecError
from poieo.providers import ProviderPool
from poieo.runtime.executor import execute
from poieo.store import NullStore, RunStore
from poieo.web.server import create_app

pytestmark = pytest.mark.usefixtures("daemon_lifecycle")

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 24


def _b64(body: bytes) -> str:
    return base64.b64encode(body).decode("ascii")


def _png(name="shot.png"):
    return {"name": name, "media_type": "image/png", "data": _b64(PNG)}


def _text(name="notes.md", words="# notes\nhello"):
    return {"name": name, "media_type": "text/markdown", "data": _b64(words.encode("utf-8"))}


def test_a_picture_and_a_text_file_are_taken():
    taken = checked_attachments([_png(), _text()])

    assert taken == [
        Attachment("shot.png", "image/png", PNG),
        Attachment("notes.md", "text/markdown", b"# notes\nhello"),
    ]


@pytest.mark.parametrize(
    ("raw", "why"),
    [
        ({"not": "a list"}, "a list"),
        ([_png(f"{i}.png") for i in range(5)], "at most 4"),
        ([{"name": "a.zip", "media_type": "application/zip", "data": _b64(b"PK")}], "pictures and text"),
        ([{"name": "a.png", "media_type": "image/png", "data": "%%% not base64"}], "base64"),
        ([{"name": "a.png", "media_type": "image/png", "data": _b64(b"words, not a picture")}], "not a image/png"),
        ([{"name": "a.txt", "media_type": "text/plain", "data": _b64(b"\xff\xfe\x00bad")}], "UTF-8"),
        ([_png("../escape.png")], "name"),
        ([_png(".hidden.png")], "name"),
        ([_png("a\\b.png")], "name"),
        ([_png("same.png"), _png("same.png")], "twice"),
        ([_png("notes.png:hidden")], "name"),
        ([_png("shot.png.")], "name"),
        ([_png("shot.png ")], "name"),
        ([_png("CON.png")], "name"),
        ([_png("nul")], "name"),
    ],
)
def test_what_is_not_a_fit_attachment_is_refused_by_name(raw, why):
    with pytest.raises(SpecError, match=why):
        checked_attachments(raw)


def test_a_picture_too_large_to_send_is_refused(monkeypatch):
    import poieo.attachments as attachments

    monkeypatch.setattr(attachments, "IMAGE_CAP", 16)

    with pytest.raises(SpecError, match="too large"):
        checked_attachments([_png()])


def test_the_model_is_shown_a_picture_as_one_and_a_text_file_as_its_words():
    blocks = attachment_blocks(checked_attachments([_png(), _text()]))

    assert blocks == [
        {"type": "image", "media_type": "image/png", "data": _b64(PNG)},
        {"type": "text", "text": "Attached file notes.md:\n# notes\nhello"},
    ]


def test_a_store_keeps_an_attachment_under_the_run_and_nowhere_else(tmp_path):
    store = RunStore(tmp_path / "runs")
    store.keep_file("r1", "shot.png", PNG)

    assert store.kept_file("r1", "shot.png") == PNG
    assert store.kept_file("r1", "other.png") is None
    assert store.kept_file("r1", "../r1/shot.png") is None
    assert store.kept_file("../runs", "shot.png") is None
    assert store.kept_file("r1", "shot.png:hidden") is None

    NullStore().keep_file("r1", "shot.png", PNG)
    assert NullStore().kept_file("r1", "shot.png") is None


async def test_the_first_step_is_shown_the_attachments_with_the_prompt(tmp_path):
    from test_runtime import agent_graph, mock_binding

    graph = agent_graph(tmp_path, tools=[])
    binding = mock_binding({"worker": ["seen"]})
    async with ProviderPool(binding) as pool:
        await execute(graph, binding, pool, NullStore(), attachments=checked_attachments([_png()]))
        provider = pool.get("fake")

    [asked] = provider.calls[0].messages
    assert asked["content"][0] == {"type": "text", "text": "do it"}
    assert asked["content"][1]["type"] == "image"


_MOCK = """\
name: mock
providers:
  fake: {type: mock, options: {responses: {"*": "seen it"}}}
default: {provider: fake, model: m}
"""


async def test_attachments_ride_the_run_now_and_are_kept_with_the_run(tmp_path):
    (tmp_path / "work").mkdir()
    card(
        tmp_path / "cards", "f", "folder: ../work\nprompt: '{{ input.message }}'\ntools: []\ntrigger: {type: manual}\n"
    )
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "poieo.yaml").write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    daemon = Daemon(load_config(tmp_path / "poieo.yaml"), store=RunStore(tmp_path / "runs"))
    serve = await up(daemon)
    runner = daemon.runners[0]

    try:
        transport = httpx.ASGITransport(app=create_app(daemon))
        async with httpx.AsyncClient(transport=transport, base_url="http://poieo") as client:
            project = daemon.config.display_name
            body = {"message": "what is this?", "thread": "t-1", "attachments": [_png(), _text()]}
            assert (await client.post(f"/api/tasks/{project}/f/run", json=body)).status_code == 200
            await until(lambda: len(runner.results) == 1, "the run with attachments")

            summary = runner.results[0].summary()
            assert summary["attachments"] == ["shot.png", "notes.md"]
            run_id = summary["run_id"]

            kept = await client.get(f"/api/runs/{run_id}/files/shot.png")
            assert kept.status_code == 200
            assert kept.content == PNG
            assert kept.headers["content-type"] == "image/png"
            assert (await client.get(f"/api/runs/{run_id}/files/missing.png")).status_code == 404
            assert (await client.get(f"/api/runs/{run_id}/files/..%2F..%2Fpoieo.yaml")).status_code == 404

            refused = await client.post(f"/api/tasks/{project}/f/run", json={"message": "hi", "attachments": [{}]})
            assert refused.status_code == 400
    finally:
        await down(daemon, serve)


async def test_a_picture_the_model_looked_at_is_kept_for_the_board_to_show(tmp_path):
    from test_runtime import agent_graph, mock_binding

    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "shot.png").write_bytes(PNG)
    store = RunStore(tmp_path / "runs")
    graph = agent_graph(tmp_path / "work", tools=["read"])
    binding = mock_binding(
        {"worker": [{"tool_calls": [{"name": "view_image", "arguments": {"path": "shot.png"}}]}, "a square"]}
    )
    async with ProviderPool(binding) as pool:
        result = await execute(graph, binding, pool, store)

    [call] = [e for e in store.events(result.run_id) if e["type"] == "node_tool_call"]
    preview = call["data"]["preview"]
    assert preview.endswith("shot.png")
    assert store.kept_file(result.run_id, preview) == PNG


async def test_a_file_that_cannot_be_kept_costs_the_keeping_not_the_task(tmp_path):
    (tmp_path / "work").mkdir()
    card(tmp_path / "cards", "f", "folder: ../work\nprompt: go\ntools: []\ntrigger: {type: manual}\n")
    (tmp_path / "b.yaml").write_text(_MOCK, encoding="utf-8")
    (tmp_path / "poieo.yaml").write_text("binding: b.yaml\ntasks: cards\n", encoding="utf-8")
    store = RunStore(tmp_path / "runs")

    def full(*args):
        raise OSError("no space left on device")

    store.keep_file = full
    daemon = Daemon(load_config(tmp_path / "poieo.yaml"), store=store)
    serve = await up(daemon)
    runner = daemon.runners[0]
    try:
        transport = httpx.ASGITransport(app=create_app(daemon))
        async with httpx.AsyncClient(transport=transport, base_url="http://poieo") as client:
            project = daemon.config.display_name
            await client.post(f"/api/tasks/{project}/f/run", json={"message": "look", "attachments": [_png()]})
            await until(lambda: len(runner.results) == 1, "the run whose file could not be kept")
            assert runner.results[0].status == "completed"

            await client.post(f"/api/tasks/{project}/f/run", json={"message": "again"})
            await until(lambda: len(runner.results) == 2, "the next run, from a task still standing")
    finally:
        await down(daemon, serve)
