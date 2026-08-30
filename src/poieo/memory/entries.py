"""Where the memory is kept, and the shape of what is in it.

One SQLite database per project, at ``memory/longterm.sqlite3``. It is not a
cache: it is the memory. Nothing else holds a second copy, which is why every
write goes through one door here and leaves a line in the history behind it.

What *is* derived lives beside the truth in the same file and may be rebuilt at
any time: the lookup table over pieces. A **piece** is the unit retrieval
matches on. Today an entry has exactly one, and the split exists so a long
entry can have several later without moving the schema underneath everything.

Design: docs/memory.md
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from pydantic import BaseModel, ConfigDict, Field

from ..errors import SpecError, describe_invalid
from ..layout import layout_for
from .index import drop_lookup as _drop_lookup
from .index import ensure_lookup

log = logging.getLogger("poieo.memory")

# Bumped whenever the shape changes. The database is the only copy now, so a
# change means *move the rows forward* -- never "throw it away and rebuild",
# which is what the old derived index could afford.
#   2: pieces carry the shape they are matched by, so the lookup and the
#      scoring after it agree about what a word is.
SCHEMA_VERSION = 2

# Advisory budget (~3k tokens) for the always-present page: the page is the
# user's to trim, and refusing to run over it would make the memory a way to
# break the daemon.
PAGE_BUDGET = 12_000

# One shared "the" must not make an entry relevant to everything.
_GLUE = frozenset(
    "a an and are as at be but by for from if in is it no not of on or so "
    "that the this to was were will with you".split()
)

# Who wrote. Two, and a third costs a reason: a person at the keyboard, and
# the learning pass. The history is only worth reading if this stays short.
WRITERS = ("person", "pass")


def _shape(word: str) -> str:
    """One word, reduced to the form it shares with its close relatives.

    Plurals, and nothing else. That is the failure this was written for -- a
    card saying "feeds" against an entry saying "feed" -- and every rule here
    earns its place by joining a real pair. Verb endings were tried and taken
    back out: stripping "ed" and "ing" pairs "refused" with "refusing" but not
    with "refuse", because the base keeps a silent "e", so half the family
    still misses and the rest of the vocabulary grows shapes like "runn" that
    match nothing. A real stemmer solves that by cutting to the root --
    "generalization" to "gener" -- which pays off over thousands of documents
    and costs precision over tens, where one wrong match is a whole wrong
    entry in a prompt.

    Both sides of every comparison come through here, so a shape only has to be
    *consistent*, never linguistically right: "series" becoming "sery" costs
    nothing, because the word it is compared against becomes "sery" too. Only
    two outcomes actually harm anything, and both are refused below -- a stem so
    short it collides with unrelated words, and a stem that lands on a word the
    glue list throws away, which would delete the word rather than widen it.
    """
    if len(word) < 5 or not word.isalpha():
        return word
    for suffix, keep in (
        ("sses", "ss"),  # classes -> class, and never address -> addres
        ("ies", "y"),  # retries -> retry
        ("ches", "ch"),  # batches -> batch
        ("shes", "sh"),
        ("xes", "x"),
        ("zes", "z"),
        ("s", ""),  # feeds -> feed, notes -> note, sizes -> size
    ):
        if not word.endswith(suffix) or word.endswith("ss") or word.endswith("us"):
            continue
        stem = word[: -len(suffix)] + keep
        # Four letters is where a stem stops being a word and starts being a
        # prefix that anything could share.
        if len(stem) >= 4 and stem not in _GLUE:
            return stem
    return word


def words(text: str) -> set[str]:
    """An entry's distinctive words, each reduced to its shape.

    The vocabulary both recall and the accounting judge by, so they cannot
    disagree about what an entry says -- which is why the shaping happens here,
    once, rather than on either side of that pair.
    """
    return {_shape(word) for word in re.findall(r"[a-z0-9_]+", text.lower())} - _GLUE


class _Links(BaseModel):
    """The typed claims an entry may make. A kind of connection exists only
    while a mechanism consumes it, so these two are all there are."""

    model_config = ConfigDict(extra="forbid")

    # What this entry needs to stay true. Followed forward at recall;
    # a lean on a set-aside entry earns a second-look line in the report.
    depends_on: list[str] = Field(default_factory=list)
    # A standing question for a person. Listed in the report, never followed.
    contradicts: list[str] = Field(default_factory=list)


class _Frontmatter(BaseModel):
    """What a learned entry may say about itself. Anything else is a typo."""

    model_config = ConfigDict(extra="forbid")

    # A filter over one store, never a wall: task slugs, path prefixes,
    # or the word that means everyone.
    scope: list[str] = Field(default_factory=lambda: ["global"])
    # "path" or "path::symbol" -- no line numbers, they rot fastest.
    anchors: list[str] = Field(default_factory=list)
    # Run ids of the episodes that taught it. Empty means a person did.
    source: list[str] = Field(default_factory=list)
    # Event time only; the history says when every line was written.
    valid_from: date | None = None
    # Set this instead of deleting: the row stays, recall moves on.
    superseded_by: str | None = None
    links: _Links = Field(default_factory=_Links)
    # Anchor path -> digest of the content the entry was written against.
    # The bytes live under memory/cache/blobs/, never here.
    sealed: dict[str, str] = Field(default_factory=dict)


class Entry(BaseModel):
    """One learned entry: a slug, a body, and what it says about itself."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    slug: str
    body: str
    matter: _Frontmatter
    # When the entry itself last changed. Doubt compares an anchor's file
    # against this, which is what makes "edit the entry after looking" clear
    # the flag -- it took the place of the file's mtime.
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    # [[names]] in the body: untyped, free to dangle -- a mention of an
    # entry that does not exist yet marks something worth writing.
    mentions: list[str] = Field(default_factory=list)


SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def keeps_memory(project_dir: Path) -> bool:
    """Whether this project keeps a long memory. The file is the whole opt-in.

    Nothing creates it on the way past: journals arrive on their own the first
    time a task runs, and a signal that switches itself on is not consent.
    """
    return layout_for(project_dir).longterm().is_file()


# -- the database ------------------------------------------------------------

_SCHEMA = """
CREATE TABLE meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE entries(
    slug          TEXT PRIMARY KEY,
    body          TEXT NOT NULL,
    scope         TEXT NOT NULL,
    anchors       TEXT NOT NULL,
    source        TEXT NOT NULL,
    valid_from    TEXT,
    superseded_by TEXT,
    depends_on    TEXT NOT NULL,
    contradicts   TEXT NOT NULL,
    sealed        TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

-- What retrieval matches on. One per entry today; the column is here so a
-- long entry can be several later without the schema moving. `shape` is the
-- same words reduced by `words()` -- derived, and the only thing the lookup
-- ever reads, so it cannot disagree with the scoring that follows it.
CREATE TABLE pieces(
    id    INTEGER PRIMARY KEY,
    slug  TEXT NOT NULL REFERENCES entries(slug) ON DELETE CASCADE,
    ord   INTEGER NOT NULL,
    text  TEXT NOT NULL,
    shape TEXT NOT NULL,
    UNIQUE(slug, ord)
);

-- Who names whom, so a neighbour can be fetched instead of found by reading
-- everything. Derived from the entry, written with it, indexed both ways
-- because association follows mentions backwards as well as forwards.
CREATE TABLE links(
    slug   TEXT NOT NULL REFERENCES entries(slug) ON DELETE CASCADE,
    kind   TEXT NOT NULL,
    target TEXT NOT NULL,
    PRIMARY KEY (slug, kind, target)
);
CREATE INDEX links_by_target ON links(target, kind);

-- The one page every run reads. At most one row, enforced.
CREATE TABLE page(
    only       INTEGER PRIMARY KEY CHECK (only = 1),
    text       TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- Every write leaves one line. This is what git used to do for free.
CREATE TABLE history(
    id     INTEGER PRIMARY KEY,
    at     TEXT NOT NULL,
    writer TEXT NOT NULL,
    did    TEXT NOT NULL,
    slug   TEXT,
    before TEXT,
    after  TEXT
);
CREATE INDEX history_by_slug ON history(slug, id);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


@contextmanager
def open_memory(project_dir: Path, create: bool = False) -> Iterator[sqlite3.Connection]:
    """The project's memory, opened and migrated forward.

    A connection per use, keyed by nothing: the daemon holds several projects
    at once, and one shared handle is how one project's memory would reach
    another's prompt.
    """
    path = layout_for(project_dir).longterm()
    if not create and not path.is_file():
        raise SpecError(f"{path}: this project keeps no long memory")
    path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(path, timeout=10)
    try:
        con.row_factory = sqlite3.Row
        con.execute("PRAGMA foreign_keys = ON")
        _migrate(con, path)
        # Derived, and built here rather than in the schema: a database made on
        # a Python without FTS5 gains the lookup the first time it is opened on
        # one that has it.
        ensure_lookup(con)
        yield con
        con.commit()
    finally:
        con.close()


def start_memory(project_dir: Path) -> Path:
    """Begin keeping a long memory here. The one place the file is created."""
    with open_memory(project_dir, create=True):
        pass
    return layout_for(project_dir).longterm()


def _version(con: sqlite3.Connection) -> int:
    try:
        row = con.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    except sqlite3.Error:
        return 0
    return int(row[0]) if row else 0


def _migrate(con: sqlite3.Connection, path: Path) -> None:
    """Forward only, and never by discarding. Each step moves the rows it owns
    and raises the version; a database from the future is refused rather than
    guessed at, because guessing wrong here loses the only copy."""
    was = _version(con)
    if was == SCHEMA_VERSION:
        return
    if was > SCHEMA_VERSION:
        raise SpecError(
            f"{path}: this memory was written by a newer poieo "
            f"(shape {was}, this one understands {SCHEMA_VERSION}); upgrade rather than downgrade"
        )
    if was == 0:
        con.executescript(_SCHEMA)
    # Steps land here in order, each guarded by the version it moves past.
    if 0 < was < 2:
        # The lookup used to read an entry's own words; it reads their shapes
        # now. The words are still there -- only what is matched on changed --
        # so this fills the new column and drops the table built on the old one.
        con.execute("ALTER TABLE pieces ADD COLUMN shape TEXT NOT NULL DEFAULT ''")
        for piece_id, text in con.execute("SELECT id, text FROM pieces").fetchall():
            con.execute("UPDATE pieces SET shape = ? WHERE id = ?", (_shaped(text), piece_id))
        _drop_lookup(con)
    con.execute(
        "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (str(SCHEMA_VERSION),),
    )
    con.commit()


# -- reading -----------------------------------------------------------------


def _mentions(body: str) -> list[str]:
    return list(dict.fromkeys(m.strip() for m in re.findall(r"\[\[([^\[\]]+)\]\]", body)))


def entry_of(row: sqlite3.Row) -> Entry:
    matter = _Frontmatter(
        scope=json.loads(row["scope"]),
        anchors=json.loads(row["anchors"]),
        source=json.loads(row["source"]),
        valid_from=date.fromisoformat(row["valid_from"]) if row["valid_from"] else None,
        superseded_by=row["superseded_by"],
        links=_Links(
            depends_on=json.loads(row["depends_on"]),
            contradicts=json.loads(row["contradicts"]),
        ),
        sealed=json.loads(row["sealed"]),
    )
    return Entry(
        slug=row["slug"],
        body=row["body"],
        matter=matter,
        updated_at=datetime.fromisoformat(row["updated_at"]),
        mentions=_mentions(row["body"]),
    )


def readable_entries(project_dir: Path) -> list[Entry]:
    """Every entry, in a stable order.

    Trouble reading the memory costs the run its memory, never the run: a task
    with less in mind beats no task at all.
    """
    if not keeps_memory(project_dir):
        return []
    try:
        with open_memory(project_dir) as con:
            rows = con.execute("SELECT * FROM entries ORDER BY slug").fetchall()
    except (sqlite3.Error, SpecError, OSError) as exc:
        log.warning("could not read this project's memory (%s); running without it", exc)
        return []
    return [entry_of(row) for row in rows]


def entry_named(project_dir: Path, slug: str) -> Entry | None:
    """One entry, or None. The board and the terminal both ask this."""
    if not keeps_memory(project_dir):
        return None
    with open_memory(project_dir) as con:
        row = con.execute("SELECT * FROM entries WHERE slug = ?", (slug,)).fetchone()
    return entry_of(row) if row else None


def read_page(project_dir: Path) -> str | None:
    """The always-present page as text, or None when the project keeps none."""
    if not keeps_memory(project_dir):
        return None
    try:
        with open_memory(project_dir) as con:
            row = con.execute("SELECT text FROM page WHERE only = 1").fetchone()
    except (sqlite3.Error, SpecError, OSError) as exc:
        # Forgetting beats failing: the run proceeds with less in mind.
        log.warning("could not read the memory page: %s", exc)
        return None
    # Markdown comments are notes to the page's editor, not to the model,
    # and the page is the most expensive room in the prompt.
    text = re.sub(r"<!--.*?-->", "", row["text"] if row else "", flags=re.DOTALL).strip()
    if not text:
        return None
    if len(text) > PAGE_BUDGET:
        log.warning(
            "this project's memory page runs %d characters against a budget of %d; "
            "trim it -- every run of every task reads it whole",
            len(text),
            PAGE_BUDGET,
        )
    return text


def history_of(project_dir: Path, slug: str | None = None, limit: int = 50) -> list[dict[str, Any]]:
    """What was written here, newest first. ``slug`` narrows to one entry."""
    if not keeps_memory(project_dir):
        return []
    with open_memory(project_dir) as con:
        if slug is None:
            rows = con.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        else:
            rows = con.execute(
                "SELECT * FROM history WHERE slug = ? ORDER BY id DESC LIMIT ?", (slug, limit)
            ).fetchall()
    return [
        {
            "at": row["at"],
            "writer": row["writer"],
            "did": row["did"],
            "slug": row["slug"],
            "before": json.loads(row["before"]) if row["before"] else None,
            "after": json.loads(row["after"]) if row["after"] else None,
        }
        for row in rows
    ]


# -- writing -----------------------------------------------------------------


def _record(con: sqlite3.Connection, writer: str, did: str, slug: str | None, before: Any, after: Any) -> None:
    con.execute(
        "INSERT INTO history(at, writer, did, slug, before, after) VALUES(?,?,?,?,?,?)",
        (
            _now(),
            writer,
            did,
            slug,
            json.dumps(before, ensure_ascii=False) if before is not None else None,
            json.dumps(after, ensure_ascii=False) if after is not None else None,
        ),
    )


def _shaped(text: str) -> str:
    """A piece as the lookup sees it: its words, each reduced to its shape."""
    return " ".join(sorted(words(text)))


def _pieces_of(body: str) -> list[str]:
    """How an entry is cut for retrieval. One piece today -- an entry is one
    durable statement, and cutting it would be inventing a rule before there
    is anything to cut. The seam is here for when there is."""
    return [body]


def write_entry(
    project_dir: Path,
    slug: str,
    body: str,
    matter: _Frontmatter | None = None,
    *,
    writer: str = "person",
) -> Entry:
    """Write one entry, and the line of history that says so.

    The only door in. A slug that could escape a folder is refused here rather
    than sanitised, which is the check the learning pass has always leaned on.
    """
    if writer not in WRITERS:
        raise ValueError(f"unknown writer '{writer}'")
    if not SLUG.match(slug):
        raise SpecError(f"'{slug}' is not a usable name: lowercase letters, digits and dashes")
    body = body.strip()
    if not body:
        raise SpecError(f"'{slug}': an entry needs something to say")
    matter = matter or _Frontmatter()

    with open_memory(project_dir, create=True) as con:
        row = con.execute("SELECT * FROM entries WHERE slug = ?", (slug,)).fetchone()
        before = {"body": row["body"]} if row else None
        now = _now()
        con.execute(
            "INSERT INTO entries(slug, body, scope, anchors, source, valid_from, superseded_by,"
            " depends_on, contradicts, sealed, updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(slug) DO UPDATE SET body=excluded.body, scope=excluded.scope,"
            " anchors=excluded.anchors, source=excluded.source, valid_from=excluded.valid_from,"
            " superseded_by=excluded.superseded_by, depends_on=excluded.depends_on,"
            " contradicts=excluded.contradicts, sealed=excluded.sealed, updated_at=excluded.updated_at",
            (
                slug,
                body,
                json.dumps(matter.scope),
                json.dumps(matter.anchors),
                json.dumps(matter.source),
                matter.valid_from.isoformat() if matter.valid_from else None,
                matter.superseded_by,
                json.dumps(matter.links.depends_on),
                json.dumps(matter.links.contradicts),
                json.dumps(matter.sealed),
                now,
            ),
        )
        con.execute("DELETE FROM pieces WHERE slug = ?", (slug,))
        con.executemany(
            "INSERT INTO pieces(slug, ord, text, shape) VALUES(?,?,?,?)",
            [(slug, i, text, _shaped(text)) for i, text in enumerate(_pieces_of(body))],
        )
        con.execute("DELETE FROM links WHERE slug = ?", (slug,))
        con.executemany(
            "INSERT OR IGNORE INTO links(slug, kind, target) VALUES(?,?,?)",
            [(slug, "mentions", t) for t in _mentions(body)]
            + [(slug, "depends_on", t) for t in matter.links.depends_on]
            + [(slug, "contradicts", t) for t in matter.links.contradicts],
        )
        _record(con, writer, "wrote", slug, before, {"body": body})

    return Entry(slug=slug, body=body, matter=matter, updated_at=datetime.fromisoformat(now), mentions=_mentions(body))


def set_aside(project_dir: Path, slug: str, because: str, *, writer: str = "person") -> None:
    """Mark an entry superseded. The body stays exactly what its author wrote:
    setting aside is the strongest thing a pass may do to an existing entry,
    and the history is what makes it reversible."""
    with open_memory(project_dir) as con:
        row = con.execute("SELECT superseded_by FROM entries WHERE slug = ?", (slug,)).fetchone()
        if row is None:
            raise SpecError(f"no entry called '{slug}'")
        con.execute(
            "UPDATE entries SET superseded_by = ?, updated_at = ? WHERE slug = ?",
            (because, _now(), slug),
        )
        _record(con, writer, "set aside", slug, {"superseded_by": row["superseded_by"]}, {"superseded_by": because})


def write_page(project_dir: Path, text: str, *, writer: str = "person") -> None:
    """Replace the one page every run reads."""
    with open_memory(project_dir, create=True) as con:
        row = con.execute("SELECT text FROM page WHERE only = 1").fetchone()
        con.execute(
            "INSERT INTO page(only, text, updated_at) VALUES(1, ?, ?) "
            "ON CONFLICT(only) DO UPDATE SET text = excluded.text, updated_at = excluded.updated_at",
            (text, _now()),
        )
        _record(con, writer, "page", None, {"text": row["text"]} if row else None, {"text": text})


def page_written_at(project_dir: Path) -> datetime | None:
    """When the page last changed, for "has this been looked at since"."""
    if not keeps_memory(project_dir):
        return None
    with open_memory(project_dir) as con:
        row = con.execute("SELECT updated_at FROM page WHERE only = 1").fetchone()
    return datetime.fromisoformat(row["updated_at"]) if row else None


# -- load-time checks --------------------------------------------------------


def check_memory(project_dir: Path) -> None:
    """Fail at launch, not at 3am: a typed claim naming nothing must surface
    where `poieo validate` and the daemon's load can see it.

    Prose ``[[mentions]]`` are deliberately free to dangle, since one naming an
    entry that does not exist marks something worth writing.
    """
    if not keeps_memory(project_dir):
        return
    entries = readable_entries(project_dir)
    known = {entry.slug for entry in entries}
    for entry in entries:
        claims = [("depends_on", target) for target in entry.matter.links.depends_on] + [
            ("contradicts", target) for target in entry.matter.links.contradicts
        ]
        if entry.matter.superseded_by is not None:
            claims.append(("superseded_by", entry.matter.superseded_by))
        for kind, target in claims:
            if target not in known:
                raise SpecError(f"memory entry '{entry.slug}': {kind} names '{target}', and no such entry exists")
        anchored = {anchor.split("::", 1)[0] for anchor in entry.matter.anchors}
        for path in entry.matter.sealed:
            if path not in anchored:
                raise SpecError(f"memory entry '{entry.slug}': sealed names '{path}', which is not an anchor here")


def frontmatter(raw: dict[str, Any]) -> _Frontmatter:
    """Validate what a writer says about an entry. Anything unrecognised is a
    typo, not a field poieo silently ignores."""
    try:
        return _Frontmatter.model_validate(raw)
    except Exception as exc:
        raise SpecError(f"invalid memory entry: {describe_invalid(exc, tuple(_Frontmatter.model_fields))}") from exc
