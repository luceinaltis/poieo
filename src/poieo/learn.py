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

Spec: docs/specs/2026-08-24-learning-pass-design.md
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .binding import BindingSpec
from .memory import (
    CONSTITUTION,
    Fact,
    doubts,
    episodes_dir,
    load_fact,
    memory_root,
    read_page,
    readable_facts,
    used_in,
)
from .providers import ProviderPool
from .providers.base import LLMRequest
from .store import json_records

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
    # One line the pass may suggest for the page. Recorded, shown, and
    # never applied by anything but a person's editor.
    page: str | None = None
    to_attic: list[str] = field(default_factory=list)
    let_go: list[str] = field(default_factory=list)


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

    facts = readable_facts(project_dir)
    doubtful = doubts(project_dir, facts)
    result = Pass(
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
        read=len(records),
        upto=records[-1].get("run_id"),
    )

    resolved = binding.resolve(LEARNER_ROLE)
    request = LLMRequest(
        model=resolved.model,
        messages=[
            {
                "role": "user",
                "content": _prompt(read_page(project_dir), facts, records, doubtful),
            }
        ],
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

    suggestion = data.get("page")
    if isinstance(suggestion, str) and suggestion.strip():
        result.page = " ".join(suggestion.split())[:300]

    _apply(project_dir, facts, records, data, result)
    # Strengthening rides the same success that moves the bookmark, so a
    # failed pass earns nothing and the reread earns exactly once.
    _strengthen(project_dir, facts, records)
    result.to_attic = _to_attic(project_dir, facts)
    result.let_go = _let_go(project_dir)
    _record(project_dir, result)
    return result


# -- what has not been read yet ----------------------------------------------


def _passes(project_dir: Path) -> Iterator[dict[str, Any]]:
    """Every pass this project has recorded, oldest first.

    Two readers want this -- the bookmark and the page suggestion -- and each
    used to open and decode the log itself. They had already drifted: one
    guarded against a line holding something other than a mapping and the
    other did not.
    """
    path = Path(project_dir) / ".poieo" / LOG_NAME
    if not path.is_file():
        return
    yield from json_records(path.read_text(encoding="utf-8").splitlines())


def _succeeded(project_dir: Path) -> Iterator[dict[str, Any]]:
    """The passes that finished. A failed one is not a thing to build on."""
    return (entry for entry in _passes(project_dir) if entry.get("error") is None)


def _bookmark(project_dir: Path) -> str:
    """The last record a successful pass reached. Failed lines do not count."""
    reached = [entry["upto"] for entry in _succeeded(project_dir) if entry.get("upto")]
    return max(reached, default="")


def _unread(project_dir: Path, mark: str) -> list[dict[str, Any]]:
    root = episodes_dir(project_dir)
    if not root.is_dir():
        return []
    records = []
    for path in sorted(root.glob("*.json")):
        if path.stem <= mark:
            continue
        try:
            record = json.loads(path.read_text(encoding="utf-8"))
            # The filename is the run id of record; a record that forgot its
            # own must not leave the bookmark unable to move past it.
            record.setdefault("run_id", path.stem)
            records.append(record)
        except (OSError, json.JSONDecodeError) as exc:
            log.warning("could not read the record %s: %s", path, exc)
    return records[:PASS_CAP]


# -- the one completion ------------------------------------------------------


def _prompt(
    page: str | None,
    facts: list[Fact],
    records: list[dict[str, Any]],
    doubtful: list[tuple[str, str]] | None = None,
) -> str:
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
    if doubtful:
        lines.append("Worth a second look (confirm silently, or retire with set_aside):")
        lines += [f"- {reason}" for _, reason in doubtful]
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
        'Optionally add "page": one line suggesting a change to the standing',
        "rules above; a person decides whether it lands.",
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
        _write_entry(project_dir, raw, shown, result)
        result.kept.append(raw["slug"])

    final = set(by_slug) | set(result.kept)
    asides = data.get("set_aside") or []
    if not isinstance(asides, list):
        result.dropped.append("'set_aside' was not a list")
        asides = []
    # by_slug is a snapshot from before the pass, so what this loop has
    # already done must be tracked here: without it one answer could set
    # the same entry aside twice, or two entries could retire each other
    # and both silently vanish.
    asided: set[str] = set()
    for raw in asides:
        entry = raw.get("entry") if isinstance(raw, dict) else None
        because = raw.get("because") if isinstance(raw, dict) else None
        if entry not in by_slug:
            result.dropped.append(f"set aside '{entry}': no such entry")
        elif entry in asided or by_slug[entry].matter.superseded_by is not None:
            result.dropped.append(f"set aside '{entry}': already set aside")
        elif because not in final or because == entry or because in asided:
            result.dropped.append(f"set aside '{entry}': '{because}' cannot replace it")
        else:
            _set_aside(by_slug[entry].path, because)
            asided.add(entry)
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


def _write_entry(
    project_dir: Path, raw: dict[str, Any], shown: list[str], result: Pass
) -> None:
    from . import blob

    # The harness stamps the source: whatever the model claimed is cut to
    # the records actually shown, and nothing surviving means all of them.
    source = [r for r in raw.get("from") or [] if r in shown] or list(shown)

    # Seal what the entry was written against: each anchored file, as it
    # is tonight, kept under its digest. Less sealing never blocks the
    # entry -- a keepsake is a copy, not a meaning.
    sealed: dict[str, str] = {}
    for anchor in raw.get("anchors") or []:
        part = anchor.split("::", 1)[0]
        target = Path(project_dir) / part
        if not target.is_file():
            continue
        name = blob.keep(project_dir, target)
        if name is not None:
            sealed[part] = name
        else:
            result.dropped.append(f"'{raw['slug']}': did not keep {part}")

    lines = [
        "---",
        f"scope: {json.dumps(raw.get('scope') or ['global'])}",
        f"anchors: {json.dumps(raw.get('anchors') or [])}",
        f"source: {json.dumps(source)}",
    ]
    if sealed:
        lines.append(f"sealed: {json.dumps(sealed)}")
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


def _strengthen(
    project_dir: Path, facts: list[Fact], records: list[dict[str, Any]]
) -> None:
    """Three factors or nothing: both entries cited in the run's own output,
    the run completed, and a declared connection between them. Co-presence
    alone earns nothing -- reinforcing what retrieval already picks is how
    a memory talks itself into a rut."""
    from .strength import wear

    by_slug = {fact.slug: fact for fact in facts}
    pairs: list[tuple[str, str]] = []
    for record in records:
        if record.get("status") != "completed":
            continue
        shown = [slug for slug in record.get("shown") or [] if slug in by_slug]
        if len(shown) < 2:
            continue
        cited = [slug for slug in shown if used_in(by_slug[slug], record)]
        for i, one in enumerate(cited):
            for other in cited[i + 1 :]:
                if _followable(by_slug[one], by_slug[other]):
                    pairs.append((one, other))
    if pairs:
        wear(project_dir, pairs)


def _followable(one: Fact, other: Fact) -> bool:
    """A connection retrieval would walk: mentions either way, leans-on
    either side. Never disagrees -- and a disagreement is a veto, not one
    vote among the connections, or "this disputes [[x]]" would wear the
    disputed pair in through its own mention."""
    if (
        other.slug in one.matter.links.contradicts
        or one.slug in other.matter.links.contradicts
    ):
        return False
    return (
        other.slug in one.mentions
        or one.slug in other.mentions
        or other.slug in one.matter.links.depends_on
        or one.slug in other.matter.links.depends_on
    )


# Set aside this long, and named by nothing typed, an entry steps out of
# the way. The clock is the file's mtime -- the set-aside edit wound it.
ATTIC_AFTER_DAYS = 90.0


def _to_attic(project_dir: Path, facts: list[Fact]) -> list[str]:
    """The gentlest verb the pass has: a whole-file move to memory/attic/,
    content untouched, reversible by moving it back. Typed references hold
    an entry in place however old -- moving a named entry would break the
    load-time cross-check -- and the attic never overwrites either."""
    referenced: set[str] = set()
    for fact in facts:
        referenced |= set(fact.matter.links.depends_on)
        referenced |= set(fact.matter.links.contradicts)
        if fact.matter.superseded_by is not None:
            referenced.add(fact.matter.superseded_by)

    now = datetime.now(timezone.utc).timestamp()
    moved: list[str] = []
    for fact in facts:
        if fact.matter.superseded_by is None or fact.slug in referenced:
            continue
        try:
            if (now - fact.path.stat().st_mtime) / 86400 < ATTIC_AFTER_DAYS:
                continue
            attic = memory_root(project_dir) / "attic"
            attic.mkdir(exist_ok=True)
            target = attic / fact.path.name
            if target.exists():
                log.warning(
                    "the attic already holds %s; leaving it in place", fact.path.name
                )
                continue
            fact.path.rename(target)
            moved.append(fact.slug)
        except OSError as exc:
            log.warning("could not move %s to the attic: %s", fact.path.name, exc)
    return moved


def _let_go(project_dir: Path) -> list[str]:
    """The one true deletion, legal because a keepsake is a copy: runtime
    bytes named by nothing in facts/ or the attic, past the grace. The
    meaning a keepsake backed is either alive and keeps its name, or moved
    to the attic with its name intact -- so an unnamed keepsake backs
    nothing."""
    from . import blob

    store = Path(project_dir) / ".poieo" / blob.STORE
    if not store.is_dir():
        return []

    referenced: set[str] = set()
    for folder in ("facts", "attic"):
        root = memory_root(project_dir) / folder
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.md")):
            try:
                referenced |= set(load_fact(path).matter.sealed.values())
            except Exception:
                # An unreadable entry protects nothing it does not name --
                # but collection must not fail over it either.
                continue

    now = datetime.now(timezone.utc).timestamp()
    gone: list[str] = []
    for path in sorted(store.iterdir()):
        if len(path.name) != 64 or path.name in referenced:
            continue
        try:
            if (now - path.stat().st_mtime) / 86400 < ATTIC_AFTER_DAYS:
                continue
            path.unlink()
            gone.append(path.name)
        except OSError as exc:
            log.warning("could not let go of %s: %s", path.name, exc)
    return gone


def last_suggestion(project_dir: Path) -> str | None:
    """What the most recent successful pass suggested for the page --
    nothing if it suggested nothing, however loud an older pass was, and
    nothing once the page has been edited since: the clearing gesture is
    the same as everywhere -- look, then touch."""
    latest: dict[str, Any] = {}
    for entry in _succeeded(project_dir):
        latest = entry
    suggestion = latest.get("page")
    if not isinstance(suggestion, str) or not suggestion:
        return None
    page_path = memory_root(project_dir) / CONSTITUTION
    try:
        if page_path.is_file():
            edited = datetime.fromtimestamp(page_path.stat().st_mtime, timezone.utc)
            if edited > datetime.fromisoformat(str(latest.get("at", ""))):
                return None
    except (OSError, ValueError):
        pass  # an unreadable clock keeps the suggestion; showing beats hiding
    return suggestion


def _record(project_dir: Path, result: Pass) -> None:
    path = project_dir / ".poieo" / LOG_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(asdict(result), ensure_ascii=False) + "\n")
