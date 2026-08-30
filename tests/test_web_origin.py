"""What the page may ask the daemon, and what another site may not.

The daemon serves an API on a loopback port with no login on it, because the
person at the keyboard owns the machine and a password on your own laptop is
theatre. That reasoning holds for *reads*. It does not hold for a request the
browser sends on somebody else's behalf: any page the user happens to have open
can post to `http://127.0.0.1:8484` without asking, and the daemon would have
paused a task, accepted a branch, or written an endpoint into a binding file.

So the writes take one fence, and it is two questions about the same request:
the `Origin`, when there is one, is this page's own -- compared against the
request's `Host`, which a browser sends beside it -- and that `Host` is this
machine, without which the first question is one an attacker can answer by
pointing a domain of their own at `127.0.0.1`.

A caller that sends no `Origin` at all is a program, not a page. `curl`, the
CLI, and a script are all in that group, and a browser cannot be: it attaches
one to every cross-site write there is.

Design: docs/web.md
"""

import pytest
from starlette.routing import Route
from starlette.testclient import TestClient
from test_web_server import stub_daemon

from poieo.web.server import create_app

# The board's own address, as a browser reaching it would spell the pair.
HERE = {"origin": "http://127.0.0.1:8484", "host": "127.0.0.1:8484"}


def _app(tmp_path, **rest):
    return create_app(stub_daemon(tmp_path, project_name="board"), **rest)


def _client(tmp_path, **rest):
    return TestClient(_app(tmp_path, **rest))


def _writes(app) -> list[str]:
    """Every route this app registers that changes something.

    Read off the app rather than typed out, for the same reason the fence is one
    middleware rather than a line per handler: a list kept by hand is a list the
    next route added is missing from.
    """
    written = []
    for route in app.routes:
        methods = getattr(route, "methods", None) or set()
        if not isinstance(route, Route) or methods <= {"GET", "HEAD", "OPTIONS"}:
            continue
        written.append(route.path.replace("{project}", "board").replace("{task}", "f"))
    return written


def test_the_list_below_is_every_write_there_is(tmp_path):
    """The parametrised routes are spelled out so a reader can see them; this
    is what keeps the spelling honest."""
    assert sorted(_writes(_app(tmp_path))) == sorted(WRITES)


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


@pytest.mark.parametrize("route", WRITES)
def test_another_site_may_not_write_through_the_browser(tmp_path, route):
    """The page the user is reading is not the page they are logged into."""
    reply = _client(tmp_path).post(
        route,
        json={},
        headers={"origin": "https://elsewhere.example", "host": "127.0.0.1:8484"},
    )

    assert reply.status_code == 403
    assert "elsewhere.example" not in reply.text  # nothing echoed back


@pytest.mark.parametrize("route", WRITES)
def test_the_board_itself_is_not_refused(tmp_path, route):
    """The board sends its own origin on every write it makes, and that origin
    is this daemon. A fence that stopped it would be a fence nobody could keep.

    What the handler then answers is not this test's business -- on a stub with
    no task `f` and no binding on disk, two of them raise. Reaching a handler at
    all is the whole claim, and a 403 never does: it is answered by the
    middleware before routing.
    """
    client = TestClient(_app(tmp_path), raise_server_exceptions=False)

    reply = client.post(route, json={}, headers=HERE)

    assert reply.status_code != 403, reply.text
    assert "did not come from the board" not in reply.text


def test_every_spelling_of_this_machine_is_this_machine(tmp_path):
    """A reader may type `localhost` where the daemon bound `127.0.0.1`, and
    `--port` moves the number. Comparing the origin against the request's own
    `Host` gets all of that right with nothing to configure."""
    client = _client(tmp_path)
    for spelling in ("localhost:8484", "127.0.0.1:8484", "[::1]:8484", "127.0.0.2:9999"):
        reply = client.post(
            "/api/tasks/board/f/pause",
            json={},
            headers={"origin": f"http://{spelling}", "host": spelling},
        )
        assert reply.status_code == 404, spelling


def test_the_dev_server_proxy_is_this_machine_too(tmp_path):
    """`npm run dev` serves the page on 5173 and proxies `/api` to 8484. The
    proxy must forward the browser's own `Host` -- vite's string shorthand
    rewrites it, which is why `vite.config.ts` spells the option out."""
    reply = _client(tmp_path).post(
        "/api/tasks/board/f/pause",
        json={},
        headers={"origin": "http://localhost:5173", "host": "localhost:5173"},
    )

    assert reply.status_code == 404


def test_a_domain_pointed_at_this_machine_is_still_another_site(tmp_path):
    """DNS rebinding, which is *the* attack on a daemon like this one and the
    reason the origin matching the host is not enough on its own.

    Serve a page from `board.evil.tld:8484` with a one-second TTL, then repoint
    the A record at `127.0.0.1`. The loaded page keeps its origin, the request
    goes to this daemon, and the two agree with each other perfectly while
    naming somebody else's domain.
    """
    reply = _client(tmp_path).post(
        "/api/tasks/board/f/run",
        json={},
        headers={"origin": "http://board.evil.tld:8484", "host": "board.evil.tld:8484"},
    )

    assert reply.status_code == 403


def test_a_board_bound_somewhere_else_asks_only_the_first_question(tmp_path):
    """`--host 0.0.0.0` is reached by a LAN address or a machine name this
    cannot know, and the reader who passed it has already spent the assumption
    the second question rests on -- the daemon says so at warning level before
    the port is bound. Refusing them would be a fence they cannot get past."""
    reply = _client(tmp_path, loopback_only=False).post(
        "/api/tasks/board/f/pause",
        json={},
        headers={"origin": "http://gpu-box.lan:8484", "host": "gpu-box.lan:8484"},
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


def test_a_method_nobody_spells_in_capitals_is_still_a_write(tmp_path):
    """The scope carries whatever the wire said."""
    reply = _client(tmp_path).request(
        "post",
        "/api/tasks/board/f/pause",
        json={},
        headers={"origin": "https://elsewhere.example", "host": "127.0.0.1:8484"},
    )

    assert reply.status_code == 403


def test_reads_are_left_alone(tmp_path):
    """Nothing here has a side effect, and without CORS headers another site
    cannot read the answer anyway. Fencing them would break a dashboard
    somebody wrote and buy nothing."""
    reply = _client(tmp_path).get("/api/tasks", headers={"origin": "https://elsewhere.example"})

    assert reply.status_code == 200


def test_the_board_refuses_to_be_framed(tmp_path):
    """The other half, on the page rather than the request. A fence that stops
    another site *sending* a write does nothing about one that loads the board
    in an invisible frame over a decoy button -- there the click is the reader's
    own and every write it makes is honestly same-origin."""
    headers = _client(tmp_path).get("/").headers

    assert headers["content-security-policy"] == "frame-ancestors 'none'"
    assert headers["x-frame-options"] == "DENY"
