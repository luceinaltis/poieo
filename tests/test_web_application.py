"""The task form stores the same application permission the runner enforces."""

import pytest
import yaml
from test_web_create_card import _client, _make
from test_workspace import git


@pytest.mark.parametrize("missing_project", [False, True])
@pytest.mark.parametrize(
    "action,key,status", [("accept", "through_run_id", "applied"), ("discard", "from_run_id", "discarded")]
)
async def test_legacy_changes_remain_decidable_and_their_history_is_updated(
    tmp_path, missing_project, action, key, status
):
    import httpx
    from test_task_application import CHECK_MADE, policy_config, run_once

    from poieo.web.server import create_app

    _, config = policy_config(tmp_path, {"mode": "review", "checks": [CHECK_MADE]})
    daemon, result = await run_once(config)
    row = daemon.store.summary(result.run_id)
    row["project"] = None
    if missing_project:
        row.pop("project")
    daemon.store.record_summary(row)
    # A board started later must reconstruct history from the legacy row.
    daemon.runners[0].results.clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(daemon)), base_url="http://localhost"
    ) as client:
        reply = await client.post(f"/api/tasks/{config.display_name}/chores/{action}", json={key: result.run_id})
    assert reply.status_code == 200, reply.text
    recorded = daemon.store.summary(result.run_id)
    assert recorded["application"]["status"] == status
    assert recorded["project"] == config.display_name


async def test_the_applied_diff_includes_the_verified_repair(tmp_path):
    import httpx
    from test_task_application import CHECK_MADE, policy_config, run_once

    from poieo.web.server import create_app

    responses = """          - tool_calls:
              - {name: write_file, arguments: {path: made.txt, content: old}}
          - wrote made.txt
          - tool_calls:
              - {name: write_file, arguments: {path: made.txt, content: hi}}
          - '{"decision":"ready","summary":"Fixed made.txt"}'
"""
    _, config = policy_config(tmp_path, {"mode": "auto", "checks": [CHECK_MADE]}, responses=responses)
    daemon, result = await run_once(config)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=create_app(daemon)), base_url="http://localhost"
    ) as client:
        reply = await client.get(f"/api/runs/{result.run_id}/diff")
    assert reply.json()["head"] == result.application["after"]
    assert "+hi" in reply.json()["patch"]


def test_creation_preserves_the_users_automatic_application_settings(tmp_path):
    client, cards = _client(tmp_path)
    git(tmp_path / "work", "init")
    policy = {"mode": "auto", "paths": ["src"], "checks": ["python -m pytest"], "timeout": 60}
    response = _make(client, {"name": "tidy", "folder": "../work", "prompt": "tidy", "apply": policy})
    assert response.status_code == 200, response.text
    assert yaml.safe_load((cards / "tidy.yaml").read_text())["apply"] == policy


def test_creation_cannot_enable_automatic_application_without_checks(tmp_path):
    client, cards = _client(tmp_path)
    response = _make(client, {"name": "tidy", "folder": "../work", "prompt": "tidy", "apply": {"mode": "auto"}})
    assert response.status_code == 400
    assert not (cards / "tidy.yaml").exists()


def test_creation_cannot_enable_automatic_application_without_a_private_copy(tmp_path):
    client, cards = _client(tmp_path)
    response = _make(
        client,
        {
            "name": "tidy",
            "folder": "../work",
            "prompt": "tidy",
            "apply": {"mode": "auto", "checks": ["python -m pytest"]},
        },
    )
    assert response.status_code == 400
    assert not (cards / "tidy.yaml").exists()


def test_editing_the_prompt_keeps_the_existing_application_permission(tmp_path):
    client, cards = _client(tmp_path)
    git(tmp_path / "work", "init")
    path = cards / "already.yaml"
    data = yaml.safe_load(path.read_text())
    policy = {"mode": "auto", "paths": ["src"], "checks": ["python -m pytest"]}
    data["apply"] = policy
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    url = "/api/projects/board/tasks/already"
    current = client.get(url).json()
    assert current["plain"]
    assert current["apply"]["mode"] == "auto"
    response = client.put(url, json={"name": "Already", "folder": "../work", "prompt": "new direction"})
    assert response.status_code == 200, response.text
    assert yaml.safe_load(path.read_text())["apply"] == policy


def test_multiline_verification_keeps_the_card_in_the_file_editor(tmp_path):
    client, cards = _client(tmp_path)
    path = cards / "already.yaml"
    data = yaml.safe_load(path.read_text())
    data["apply"] = {"mode": "review", "checks": ["python - <<'PY'\nassert 1 == 1\nPY"]}
    path.write_text(yaml.safe_dump(data))
    assert client.get("/api/projects/board/tasks/already").json()["plain"] is False


def test_switching_application_mode_is_live_without_rewriting_other_settings(tmp_path):
    client, cards = _client(tmp_path)
    git(tmp_path / "work", "init")
    response = client.put(
        "/api/projects/board/tasks/already",
        json={
            "name": "Already",
            "folder": "../work",
            "prompt": "hi",
            "apply": {"mode": "auto", "checks": ["python -m pytest"]},
        },
    )
    assert response.status_code == 200, response.text
    assert response.json()["live"]
    assert yaml.safe_load((cards / "already.yaml").read_text())["apply"]["mode"] == "auto"
