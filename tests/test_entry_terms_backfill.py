"""Entries written before there were terms are given them by the learning
schedule -- bare ones only, with everything else they say left exactly as it
was, and never as something a run waits for."""

import json

from test_learn import _binding

from poieo.learn import refresh_entry_terms
from poieo.memory import entry_named, frontmatter, history_of, start_memory, write_entry
from poieo.providers import ProviderPool


def _project(tmp_path):
    project = tmp_path / "tasks"
    project.mkdir(parents=True, exist_ok=True)
    (project / "poieo.yaml").write_text("version: 1\n", encoding="utf-8")
    start_memory(project)
    return project


async def test_bare_entries_get_terms_and_nothing_else_about_them_moves(tmp_path):
    project = _project(tmp_path)
    write_entry(
        project,
        "cap",
        "The api rejects batches over 50; keep [[feeds-order]] in mind.",
        frontmatter({"scope": ["importer"], "anchors": ["notebook"], "source": ["r1"]}),
    )
    write_entry(project, "already", "Rotate the nginx logs with copytruncate.", terms="logrotate nginx webserver")

    binding = _binding([json.dumps({"1": "feed api batch upload import bulk send ingest"})])
    async with ProviderPool(binding) as pool:
        assert await refresh_entry_terms(project, binding, pool) == ["cap"]

    cap = entry_named(project, "cap")
    assert cap.terms == "feed api batch upload import bulk send ingest"
    assert cap.body == "The api rejects batches over 50; keep [[feeds-order]] in mind."
    assert cap.matter.scope == ["importer"] and cap.matter.anchors == ["notebook"] and cap.matter.source == ["r1"]
    assert cap.mentions == ["feeds-order"]
    assert entry_named(project, "already").terms == "logrotate nginx webserver"
    # The one door was used, and the history says who and what.
    line = history_of(project, "cap")[0]
    assert (line["writer"], line["did"]) == ("pass", "wrote")
    assert line["after"]["terms"] == "feed api batch upload import bulk send ingest"


async def test_nothing_bare_means_nothing_asked(tmp_path):
    project = _project(tmp_path)
    write_entry(project, "already", "Rotate the nginx logs with copytruncate.", terms="logrotate nginx")
    binding = _binding(["never called"])
    async with ProviderPool(binding) as pool:
        assert await refresh_entry_terms(project, binding, pool) == []


async def test_a_pass_that_cannot_answer_leaves_the_entries_bare(tmp_path):
    project = _project(tmp_path)
    write_entry(project, "cap", "The api rejects batches over 50.")
    binding = _binding(["this is not json"])
    async with ProviderPool(binding) as pool:
        assert await refresh_entry_terms(project, binding, pool) == []
    assert entry_named(project, "cap").terms == ""
    assert len(history_of(project, "cap")) == 1  # nothing was rewritten
