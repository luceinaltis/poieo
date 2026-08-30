"""What the page may ask the daemon, and what another site may not.

The daemon serves an API on a loopback port with no login on it, because the
person at the keyboard owns the machine and a password on your own laptop is
theatre. That reasoning holds for *reads*. It does not hold for a request the
browser sends on somebody else's behalf: any page the user happens to have open
can post to `http://127.0.0.1:8484` without asking, and the daemon would have
paused a task, accepted a branch, or written an endpoint into a binding file.

So the writes take one fence -- **an `Origin`, if the caller sent one, has to be
this daemon's own.** Compared against the request's own `Host`, which is every
spelling of this machine at once and needs no configuring: a browser sends both,
and they agree exactly when the page came from here.

A caller that sends no `Origin` at all is a program, not a page. `curl`, the
CLI, and a script are all in that group, and a browser cannot be: it attaches
one to every cross-site write there is.

Design: docs/web.md
"""

import pytest
from starlette.testclient import TestClient
from test_web_server import stub_daemon

from poieo.web.server import create_app

# Every route that changes something, in the five kinds web.md counts them in.
WRITES = [
    "/api/tasks/board/f/pause",
    "/api/tasks/board/f/resume",
    "/api/tasks/board/f/run",
    "/api/tasks/board/f/answer",
    "/api/tasks/board/f/accept",
    "/api/tasks/board/f/discard",
    "/api/projects/board/models/use",
    "/api/projects/board/models/add",
    "/api/projects/board/tasks",
]


def _client(tmp_path):
    return TestClient(create_app(stub_daemon(tmp_path, project_name="board")))


@pytest.mark.parametrize("route", WRITES)
def test_another_site_may_not_write_through_the_browser(tmp_path, route):
    """The page the user is reading is not the page they are logged into."""
    reply = _client(tmp_path).post(route, json={}, headers={"origin": "https://elsewhere.example"})

    assert reply.status_code == 403
    assert "elsewhere.example" not in reply.text  # nothing echoed back


def test_the_board_itself_is_not_refused(tmp_path):
    """The board sends its own origin on every write it makes, and that origin
    is this daemon. A fence that stopped it would be a fence nobody could keep."""
    client = _client(tmp_path)
    reply = client.post(
        "/api/tasks/board/f/pause",
        json={},
        headers={"origin": "http://testserver", "host": "testserver"},
    )

    # 404: there is no task `f` on this stub. What matters is that it reached
    # the route at all, which a 403 would mean it had not.
    assert reply.status_code == 404


def test_every_spelling_of_this_machine_is_this_machine(tmp_path):
    """`--host` moves the address and a reader may type `localhost` where the
    daemon bound `127.0.0.1`. Comparing the origin against the request's own
    `Host` gets all of that right without anything to configure."""
    client = _client(tmp_path)
    for spelling in ("localhost:8484", "127.0.0.1:8484", "[::1]:8484", "gpu-box:8484"):
        reply = client.post(
            "/api/tasks/board/f/pause",
            json={},
            headers={"origin": f"http://{spelling}", "host": spelling},
        )
        assert reply.status_code == 404, spelling


def test_the_dev_server_proxy_is_this_machine_too(tmp_path):
    """`npm run dev` serves the page on 5173 and proxies `/api` to 8484. The
    proxy forwards the browser's own `Host` (it must not rewrite it -- see the
    note in vite.config.ts), so the pair still agrees and the dev loop keeps
    working."""
    reply = _client(tmp_path).post(
        "/api/tasks/board/f/pause",
        json={},
        headers={"origin": "http://localhost:5173", "host": "localhost:5173"},
    )

    assert reply.status_code == 404


def test_a_caller_that_sends_no_origin_is_a_program(tmp_path):
    """`curl`, the CLI, a script. A browser cannot be in this group: it attaches
    an origin to every cross-site write there is."""
    assert _client(tmp_path).post("/api/tasks/board/f/pause", json={}).status_code == 404


def test_a_sandboxed_page_saying_null_is_not_this_one(tmp_path):
    """An iframe with no origin of its own sends the literal `null`. It is not
    this daemon, and reading it as "no origin" would be the hole reopened."""
    reply = _client(tmp_path).post("/api/tasks/board/f/pause", json={}, headers={"origin": "null"})

    assert reply.status_code == 403


def test_reads_are_left_alone(tmp_path):
    """Nothing here has a side effect, and without CORS headers another site
    cannot read the answer anyway. Fencing them would break a dashboard
    somebody wrote and buy nothing."""
    reply = _client(tmp_path).get("/api/tasks", headers={"origin": "https://elsewhere.example"})

    assert reply.status_code == 200
