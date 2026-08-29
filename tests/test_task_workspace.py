"""A task with a workdir works in a private copy and lands one change.

These run the real daemon against a real repository. The thing worth proving
is a negative -- that the user's own checkout is exactly as they left it -- and
that only holds if git is actually involved.
"""

import asyncio

from test_workspace import git, head, make_repo

from conftest import card
from poieo.daemon import Daemon, load_config
from poieo.store import RunStore

BINDING = """
name: mock
providers:
  fake:
    type: mock
    options:
      responses:
        worker:
{responses}
default: {{provider: fake, model: mock-model}}
"""

WRITES_A_FILE = """          - tool_calls:
              - {name: write_file, arguments: {path: made.txt, content: "hi"}}
          - "wrote made.txt"
"""

WRITES_NOTHING = """          - "nothing needed doing"
"""

NEVER_STOPS = """          - tool_calls:
              - {name: write_file, arguments: {path: made.txt, content: "hi"}}
"""

GRAPH = """
name: chore
entry: work
nodes:
  - id: work
    type: agent
    role: worker
    prompt: do it
    tools: [files, shell]
    max_turns: {max_turns}
    output: {{as: report}}
"""

LLM_GRAPH = """
name: chat
entry: say
nodes:
  - id: say
    type: agent
    role: worker
    prompt: hello
    output: {as: reply}
"""

CONFIG = """
version: 1
store: store
binding: b.yaml
tasks: cards
"""

JOB = """graph: ../g.yaml
{workdir}
trigger: {{type: loop, max_iterations: 1}}
"""


def build(tmp_path, *, responses=WRITES_A_FILE, graph=None, workdir=True, max_turns=10):
    repo = make_repo(tmp_path)
    (tmp_path / "b.yaml").write_text(BINDING.format(responses=responses), encoding="utf-8")
    (tmp_path / "g.yaml").write_text(
        graph if graph else GRAPH.format(max_turns=max_turns), encoding="utf-8"
    )
    card(
        tmp_path / "cards",
        "chores",
        JOB.format(workdir="folder: ../project" if workdir else ""),
    )
    (tmp_path / "d.yaml").write_text(CONFIG, encoding="utf-8")
    return repo, load_config(tmp_path / "d.yaml")


async def run_once(config):
    daemon = Daemon(config, store=RunStore(config.store_path()))
    results = await asyncio.wait_for(daemon.serve(install_signals=False), timeout=60)
    return daemon, results[0]


def events_of(config, run_id):
    return list(RunStore(config.store_path()).events(run_id))


async def test_run_works_in_the_private_copy_not_the_users_folder(tmp_path):
    repo, config = build(tmp_path)
    before = head(repo, "main")

    _, result = await run_once(config)

    assert result.status == "completed"
    # the user's checkout: untouched, unmoved, and the file is not in it
    assert not (repo / "made.txt").exists()
    assert head(repo, "main") == before
    assert git(repo, "status", "--porcelain", "--untracked-files=no").strip() == ""
    # the work is on the task's own branch
    assert git(repo, "show", "poieo/chores:made.txt").strip() == "hi"


async def test_summary_carries_the_change(tmp_path):
    repo, config = build(tmp_path)

    _, result = await run_once(config)

    change = result.summary()["change"]
    assert change["files"] == ["made.txt"]
    # the model's own last words, which the work list shows
    assert change["message"] == "wrote made.txt"
    assert change["insertions"] > 0
    assert change["head"] == head(repo, "poieo/chores")
    assert change["base"] != change["head"]


async def test_the_recorded_summary_carries_the_change(tmp_path):
    # The in-memory result is not what the review screen reads. The row in the
    # index is, and it is written by execute() -- which finishes before the
    # daemon has anything to say about the change.
    repo, config = build(tmp_path)

    _, result = await run_once(config)

    row = RunStore(config.store_path()).summary(result.run_id)
    assert row["change"]["head"] == head(repo, "poieo/chores")


async def test_a_run_is_recorded_once(tmp_path):
    _, config = build(tmp_path)

    _, result = await run_once(config)

    rows = RunStore(config.store_path()).list_runs(limit=50)
    assert [r["run_id"] for r in rows].count(result.run_id) == 1


async def test_run_change_event_is_emitted(tmp_path):
    _, config = build(tmp_path)

    _, result = await run_once(config)

    changes = [e for e in events_of(config, result.run_id) if e["type"] == "run_change"]
    assert len(changes) == 1
    assert changes[0]["data"]["head"] == result.change["head"]


async def test_no_change_is_not_a_failure(tmp_path):
    repo, config = build(tmp_path, responses=WRITES_NOTHING)
    before = head(repo, "main")

    _, result = await run_once(config)

    # A run that found nothing to do did its job. It is not an error, and there
    # is nothing to review.
    assert result.status == "completed"
    assert "change" not in result.summary()
    assert head(repo, "poieo/chores") == before


async def test_failed_run_does_not_advance_the_branch(tmp_path):
    repo, config = build(tmp_path, responses=NEVER_STOPS, max_turns=2)
    before = head(repo, "main")

    _, result = await run_once(config)

    assert result.status == "failed"
    assert head(repo, "poieo/chores") == before
    # the run is still on the record, and its half-done work is still reachable
    assert events_of(config, result.run_id)
    assert head(repo, f"refs/poieo/failed/{result.run_id}")


async def test_flow_without_workdir_is_untouched(tmp_path):
    _, config = build(tmp_path, graph=LLM_GRAPH, workdir=False)

    _, result = await run_once(config)

    assert result.status == "completed"
    assert result.change is None
    assert "change" not in result.summary()
    assert not (config.store_path() / "worktrees").exists()


async def test_a_broken_repository_does_not_stop_the_flow(tmp_path):
    repo, config = build(tmp_path)
    # Renamed rather than deleted: git's object files are read-only, and on
    # Windows rmtree trips over that. Either way it stops being a repository.
    (repo / ".git").rename(repo / ".git-gone")

    _, result = await run_once(config)

    # No review is possible, but 3am is no time to stop working.
    assert result.status == "completed"
    assert result.change is None
    # And it says so where somebody would look. #188 gave the *commit* failure
    # a voice; a repository that could not be opened at all had the same
    # consequence -- no change, so no handoff, ever -- and none.
    said = [e for e in events_of(config, result.run_id) if e["type"] == "run_change_failed"]
    assert said, "a run that could not be tracked has to say so"


async def test_a_worktree_that_could_not_be_prepared_says_so(tmp_path, monkeypatch):
    """The other silent branch, and the one seen in the wild.

    A repository present and usable enough to answer `available`, and then
    refusing to make a worktree -- a missing object, a broken index. Watched
    against a real one: `error: Could not read fd0489dc...`, three tasks in a
    row, and the board showed three healthy runs that changed nothing.
    """
    from poieo import workspace as workspace_module

    def refuse(*args, **kwargs):
        raise workspace_module.WorkspaceError("Could not read fd0489dc")

    repo, config = build(tmp_path)
    monkeypatch.setattr(workspace_module.Workspace, "prepare", refuse)

    _, result = await run_once(config)

    assert result.status == "completed"
    assert result.change is None
    said = [e for e in events_of(config, result.run_id) if e["type"] == "run_change_failed"]
    assert said and "fd0489dc" in said[0]["data"]["error"]


async def test_a_change_that_could_not_be_recorded_is_visible(tmp_path, monkeypatch):
    """A run whose work was never recorded looks exactly like one that had
    nothing to do, and the difference decides whether anything happens next.

    `then:` conditions are written against `run.change` -- the example's build
    hands off on `run.change and 'GREEN' in ...` -- so a task whose commits
    keep failing will pass its own gate and never hand over, forever, while
    the board shows a healthy green run. Watched in the wild against a
    repository with a missing object: `error: Could not read fd0489dc...`.
    """
    from poieo import workspace as workspace_module

    def refuse(*args, **kwargs):
        raise workspace_module.WorkspaceError("Could not read fd0489dc")

    repo, config = build(tmp_path)
    monkeypatch.setattr(workspace_module.Workspace, "commit", refuse)

    _, result = await run_once(config)

    # The work still ran, and 3am is no time to stop -- but it has to say so.
    assert result.status == "completed"
    assert result.change is None
    said = [e for e in events_of(config, result.run_id) if e["type"] == "run_change_failed"]
    assert said, "a change that could not be recorded has to reach the run's own log"
    assert "fd0489dc" in said[0]["data"]["error"]


CARD = """
name: chores
graph: ../g.yaml
folder: ../project
every: loop
"""

CARD_CONFIG = """
version: 1
store: store
binding: b.yaml
tasks: cards
"""


async def test_a_card_works_in_a_private_copy_like_any_other_job(tmp_path):
    """The card is the surface the product tells people to use, and it was the
    one the private copy did not reach.

    A card's `folder:` reached the generated node and stopped there, so the
    model wrote into the user's own checkout and there was nothing to accept
    or discard in the morning. The whole safety story, missing from the only
    file most people will ever write.
    """
    repo = make_repo(tmp_path)
    before = head(repo)
    (tmp_path / "b.yaml").write_text(
        BINDING.format(responses=WRITES_A_FILE), encoding="utf-8"
    )
    (tmp_path / "g.yaml").write_text(GRAPH.format(max_turns=10), encoding="utf-8")
    (tmp_path / "cards").mkdir()
    (tmp_path / "cards" / "chores.yaml").write_text(CARD, encoding="utf-8")
    (tmp_path / "d.yaml").write_text(CARD_CONFIG, encoding="utf-8")

    config = load_config(tmp_path / "d.yaml")
    daemon = Daemon(config, store=RunStore(config.store_path()))
    serving = asyncio.create_task(daemon.serve(install_signals=False))
    while not daemon.runners:
        await asyncio.sleep(0.01)
    deadline = asyncio.get_running_loop().time() + 30
    while not daemon.runners[0].results:
        if asyncio.get_running_loop().time() > deadline:
            raise AssertionError("timed out waiting for the card's first run")
        await asyncio.sleep(0.02)
    result = daemon.runners[0].results[0]
    daemon.stop()
    await asyncio.wait_for(serving, timeout=30)

    assert daemon.runners[0].workspace is not None
    # The user's own checkout is exactly as they left it, and the work is a
    # change waiting to be read.
    assert head(repo) == before
    assert not (repo / "made.txt").exists()
    assert result.change is not None and "made.txt" in result.change["files"]
