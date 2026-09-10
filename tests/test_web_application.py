"""The task form stores the same application permission the runner enforces."""

import yaml
from test_web_create_card import _client, _make
from test_workspace import git


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
