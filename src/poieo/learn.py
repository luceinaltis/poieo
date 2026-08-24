"""A pass that reads the run records and writes down what stays true.

The model proposes; the harness writes. That order is the whole safety
story: the distiller is the most dangerous writer in the system, so its
output goes through the same kind of narrow, validated door that stamps a
note's sender -- source ids come from the records actually shown, a slug
can never collide or escape the folder, and the only verbs are writing a
new entry and setting one aside. The page is never touched, nothing is
deleted, nothing is overwritten.

The bookmark -- the last record successfully read -- lives in the pass log
and moves only on success, so a failed pass rereads rather than skips.
Repeating is recoverable; losing is not.

Spec: docs/superpowers/specs/2026-08-24-learning-pass-design.md
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .binding import BindingSpec
from .memory import Fact, _facts_or_less, _page, memory_root
from .providers import ProviderPool
from .providers.base import LLMRequest

log = logging.getLogger("poieo.learn")

LEARNER_ROLE = "learner"
# Records per pass. What does not fit arrives next pass, and the bookmark
# only moves as far as what was shown -- the journal's batching rule.
PASS_CAP = 20
LOG_NAME = "learning.jsonl"

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


@dataclass(slots=True)
class Pass:
    """What one pass did -- also exactly what lands in the pass log."""

    at: str
    read: int
    upto: str | None
    kept: list[str] = field(default_factory=list)
    set_aside: list[str] = field(default_factory=list)
    dropped: list[str] = field(default_factory=list)
    error: str | None = None


async def learn(project_dir: Path, binding: BindingSpec, pool: ProviderPool) -> Pass | None:
    """One learning pass. None when the project keeps no memory (the folder
    stays the one opt-in, and a pass must never create it) or when there is
    nothing unread -- in which case no completion is even attempted."""
    project_dir = Path(project_dir)
    if not memory_root(project_dir).is_dir():
        return None
    records = _unread(project_dir, _bookmark(project_dir))
    if not records:
        log.debug("nothing new to learn from in %s", project_dir)
        return None

    facts = _facts_or_less(project_dir)
    result = Pass(
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        read=len(records),
        upto=records[-1].get("run_id"),
    )

    resolved = binding.resolve(LEARNER_ROLE)
    request = LLMRequest(
        model=resolved.model,
        messages=[{"role": "user", "content": _prompt(_page(project_dir), facts, records)}],
        system=None,
        params=dict(resolved.params),
        role=LEARNER_ROLE,
    )
    try:
        response = await pool.get(resolved.provider_name).complete(request)
        data = _parse(response.text)
    except Exception as exc:
        # One attempt per pass; the next pass is the retry, on the same
        # records. The record says it failed, never what the model said.
        result.error = f"{type(exc).__name__}: {exc}"
        result.upto = None
        _record(project_dir, result)
        return result

    _apply(project_dir, facts, records, data, result)
    _record(project_dir, result)
    return result


# -- what has not been read yet ----------------------------------------------


def _bookmark(project_dir: Path) -> str:
    """The last record a successful pass reached. Failed lines do not count."""
    path = project_dir / ".poieo" / LOG_NAME
    mark = ""
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                entry = json.loads(line)
            except json.JSONDecodeError:
                continue
            if entry.get("error") is None and entry.get("upto"):
                mark = max(mark, entry["upto"])
    return mark


def _unread(project_dir: Path, mark: str) -> list[dict[str, Any]]:
    root = project_dir / ".poieo" / "episodes"
    if not root.is_dir():
        return []
    records = []
    for path in sorted(root.glob("*.json")):
        if path.stem <= mark:
            continue
        try:
            records.append(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("could not read the record %s: %s", path, exc)
    return records[:PASS_CAP]


# -- the one completion ------------------------------------------------------


def _prompt(page: str | None, facts: list[Fact], records: list[dict[str, Any]]) -> str:
    lines = [
        "You keep the long memory of a project of scheduled tasks.",
        "Below are the project's standing rules, what it already knows, and",
        "records of recent work it has not yet learned from.",
        "",
        "Propose only what stays true beyond the run that taught it. Most",
        "runs teach nothing durable; an empty answer is the right answer",
        "most nights.",
        "",
    ]
    if page:
        lines += ["What this project always requires:", page, ""]
    if facts:
        lines.append("What it already knows:")
        lines += [f"- {fact.slug}: {' '.join(fact.body.split())}" for fact in facts]
        lines.append("")
    lines.append("Records not yet learned from, oldest first:")
    for record in records:
        summary = " ".join(str(record.get("summary", "")).split())
        lines.append(
            f"- {record.get('run_id')} · {record.get('task')} · "
            f"{record.get('status')} · {summary}"
        )
    lines += [
        "",
        "Answer with JSON only, no prose:",
        '{"entries": [{"slug": "kebab-case", "body": "one durable statement",',
        ' "scope": ["global"], "anchors": [], "from": ["record ids that taught it"],',
        ' "links": {"depends_on": [], "contradicts": []}}],',
        ' "set_aside": [{"entry": "slug that no longer holds", "because": "slug that replaces it"}]}',
    ]
    return "\n".join(lines)


def _parse(text: str) -> dict[str, Any]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if not match:
        raise ValueError("the answer holds no JSON object")
    data = json.loads(match.group(0))
    if not isinstance(data, dict):
        raise ValueError("the answer must be a JSON object")
    return data


# -- validating and applying a proposal --------------------------------------


def _apply(
    project_dir: Path,
    facts: list[Fact],
    records: list[dict[str, Any]],
    data: dict[str, Any],
    result: Pass,
) -> None:
    by_slug = {fact.slug: fact for fact in facts}
    shown = [r["run_id"] for r in records if r.get("run_id")]

    entries = data.get("entries") or []
    if not isinstance(entries, list):
        result.dropped.append("'entries' was not a list")
        entries = []

    accepted: list[dict[str, Any]] = []
    taken = set(by_slug)
    for raw in entries:
        problem = _vet_entry(raw, taken)
        if problem:
            result.dropped.append(problem)
            continue
        taken.add(raw["slug"])
        accepted.append(raw)

    # Links may name entries accepted this pass; dropping one for its own
    # links can strand another that pointed at it, so settle to a fixpoint
    # rather than leave a dangling claim for the next load to trip over.
    while True:
        ok = set(by_slug) | {raw["slug"] for raw in accepted}
        stranded = [raw for raw in accepted if _dangling(raw, ok)]
        if not stranded:
            break
        for raw in stranded:
            result.dropped.append(
                f"'{raw['slug']}': names '{_dangling(raw, ok)}', which does not exist"
            )
            accepted.remove(raw)

    for raw in accepted:
        _write_entry(project_dir, raw, shown)
        result.kept.append(raw["slug"])

    final = set(by_slug) | set(result.kept)
    asides = data.get("set_aside") or []
    if not isinstance(asides, list):
        result.dropped.append("'set_aside' was not a list")
        asides = []
    for raw in asides:
        entry = raw.get("entry") if isinstance(raw, dict) else None
        because = raw.get("because") if isinstance(raw, dict) else None
        if entry not in by_slug:
            result.dropped.append(f"set aside '{entry}': no such entry")
        elif by_slug[entry].matter.superseded_by is not None:
            result.dropped.append(f"set aside '{entry}': already set aside")
        elif because not in final or because == entry:
            result.dropped.append(f"set aside '{entry}': '{because}' cannot replace it")
        else:
            _set_aside(by_slug[entry].path, because)
            result.set_aside.append(entry)


def _vet_entry(raw: Any, taken: set[str]) -> str | None:
    """The reason this proposal is dropped, or None. The slug rules double
    as the fence: a slug that could escape the folder cannot pass them."""
    if not isinstance(raw, dict):
        return "an entry was not an object"
    slug = raw.get("slug")
    if not isinstance(slug, str) or not _SLUG.match(slug):
        return f"'{slug}': not a plain slug"
    if slug in taken:
        return f"'{slug}': already exists, and a pass never overwrites"
    body = raw.get("body")
    if not isinstance(body, str) or not body.strip():
        return f"'{slug}': an entry needs something to say"
    for key in ("scope", "anchors", "from"):
        value = raw.get(key)
        if value is not None and not (
            isinstance(value, list) and all(isinstance(item, str) for item in value)
        ):
            return f"'{slug}': '{key}' must be a list of strings"
    links = raw.get("links")
    if links is not None:
        if not isinstance(links, dict) or set(links) - {"depends_on", "contradicts"}:
            return f"'{slug}': unknown link kind"
        for value in links.values():
            if not (isinstance(value, list) and all(isinstance(item, str) for item in value)):
                return f"'{slug}': links must list slugs"
    return None


def _dangling(raw: dict[str, Any], ok: set[str]) -> str | None:
    links = raw.get("links") or {}
    for targets in links.values():
        for target in targets:
            if target not in ok:
                return target
    return None


def _write_entry(project_dir: Path, raw: dict[str, Any], shown: list[str]) -> None:
    # The harness stamps the source: whatever the model claimed is cut to
    # the records actually shown, and nothing surviving means all of them.
    source = [r for r in raw.get("from") or [] if r in shown] or list(shown)
    lines = [
        "---",
        f"scope: {json.dumps(raw.get('scope') or ['global'])}",
        f"anchors: {json.dumps(raw.get('anchors') or [])}",
        f"source: {json.dumps(source)}",
    ]
    links = raw.get("links") or {}
    for kind in ("depends_on", "contradicts"):
        if links.get(kind):
            if "links:" not in lines:
                lines.append("links:")
            lines.append(f"  {kind}: {json.dumps(links[kind])}")
    lines += ["---", raw["body"].strip(), ""]
    path = memory_root(project_dir) / "facts" / f"{raw['slug']}.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")


def _set_aside(path: Path, because: str) -> None:
    """One frontmatter line; the body stays byte for byte what its author
    wrote. Setting aside is the strongest thing a pass may do to an
    existing entry, and it is reversible in an editor or by git."""
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    closed = None
    if lines and lines[0].strip() == "---":
        for i in range(1, len(lines)):
            if lines[i].strip() == "---":
                closed = i
                break
    if closed is None:
        new = ["---", f"superseded_by: {because}", "---", *lines]
    else:
        head = [l for l in lines[1:closed] if not l.strip().startswith("superseded_by:")]
        new = ["---", *head, f"superseded_by: {because}", "---", *lines[closed + 1 :]]
    path.write_text("\n".join(new), encoding="utf-8")


def _record(project_dir: Path, result: Pass) -> None:
    path = project_dir / ".poieo" / LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
