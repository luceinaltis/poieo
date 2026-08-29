"""File tools, confined to the working directory."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from ..providers.base import ToolDef
from . import Tool, ToolError

_READ_CAP = 200_000     # characters
_GLOB_CAP = 500         # paths
_SEARCH_CAP = 200       # matches
_LINE_CAP = 300         # characters of any one matched line


def resolve_path(workdir: Path, raw: str) -> Path:
    """Resolve ``raw`` against ``workdir`` and refuse anything that escapes.

    ``resolve()`` follows symlinks, so a link pointing outside is caught too.
    """
    root = workdir.resolve()
    raw_path = Path(raw)
    candidate = (raw_path if raw_path.is_absolute() else root / raw_path).resolve()
    if candidate != root and root not in candidate.parents:
        raise ToolError(f"path '{raw}' escapes the working directory")
    return candidate


async def _read_file(workdir: Path, args: dict[str, Any]) -> str:
    """Read a file, numbered, and optionally only a window of it.

    A step that read whole files ran its conversation to 271,064 characters of
    file text and was still resending all of it every turn; one that read
    ranges never reached the cap at all. SWE-agent measured the same thing
    from the other side -- showing whole files rather than a window cost 5.3
    points, and a window too *narrow* cost 3.7, which is why there is no
    default window here. The size of the window is the model's to choose; only
    the ceiling is ours.

    The numbers are what make a range askable at all -- Anthropic's text editor
    calls them "essential" for exactly that. They cost something: a model may
    copy one into an `edit_file` call, which is why `_place` takes them back
    off rather than failing on them.
    """
    path = resolve_path(workdir, args["path"])
    if not path.is_file():
        raise ToolError(f"no such file: {args['path']}")
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()

    offset = max(1, int(args.get("offset") or 1))
    limit = args.get("limit")
    last = len(lines) if limit is None else offset + max(0, int(limit)) - 1
    window = lines[offset - 1 : last]

    if not window:
        # Silence would read as an empty file and the model would believe it.
        return f"(no lines there: {args['path']} has {len(lines)} line(s))"

    numbered = "\n".join(f"{offset + i}\t{line}" for i, line in enumerate(window))
    if len(numbered) > _READ_CAP:
        # Cut on a line, and say where it stopped. `... [truncated]` was a
        # dead end until this tool could read a window; now the number to
        # carry on from is the useful half of the message, and a line cut in
        # half is a line of code that does not exist -- which `edit_file`
        # would then fail to match, without either of them saying why.
        kept = numbered[:_READ_CAP].rsplit("\n", 1)[0].split("\n")
        last = offset + len(kept) - 1
        return (
            f"{args['path']} lines {offset}-{last} of {len(lines)}, truncated\n"
            + "\n".join(kept)
            + f"\n... [give offset={last + 1} to read on]"
        )
    if len(window) == len(lines):
        # The whole file: the last number already says how many lines there
        # are, and a header saying "lines 1-40 of 40" would be a line of
        # nothing on every read.
        return numbered
    shown = f"{offset}-{offset + len(window) - 1}"
    return f"{args['path']} lines {shown} of {len(lines)}\n{numbered}"


async def _write_file(workdir: Path, args: dict[str, Any]) -> str:
    path = resolve_path(workdir, args["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = str(args.get("content", ""))
    path.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {args['path']}"


# A line number the way a file viewer writes one, so an `old` copied straight
# out of a listing can have them taken back off.
_NUMBERED = re.compile(r"^\s*\d+[\t:]\s?", re.MULTILINE)


def _loosened(text: str) -> str:
    """The same text with what models get wrong about it taken out.

    Line endings and trailing spaces, and nothing else. **Not indentation**:
    in Python indentation is meaning, and a tool that matched it loosely would
    be guessing at which block the model meant.
    """
    return "\n".join(line.rstrip() for line in text.replace("\r\n", "\n").split("\n"))


def _place(text: str, old: str) -> tuple[str, int] | None:
    """Where `old` sits in `text`, trying three readings of "the same".

    Exact first. Then without the line numbers a file viewer prints, because
    both reference implementations number their output and then ask the model
    to remember to strip them -- and the models that need reminding are the
    ones that will not. Then ignoring trailing whitespace and line endings,
    which is where the reported edit failure rates on models that were never
    trained on this tool mostly come from.

    Returns the text it matched and how many times it appears, or None.
    Uniqueness is checked by the caller and is **not** relaxed here: matching
    is what becomes forgiving, never the safeguard.
    """
    for candidate in (old, _NUMBERED.sub("", old), None):
        if candidate is None:
            break
        count = text.count(candidate)
        if count:
            return candidate, count
    loose_old = _loosened(_NUMBERED.sub("", old))
    loose_text = _loosened(text)
    count = loose_text.count(loose_old)
    if count:
        return loose_old, count
    return None


def _would_parse(path: Path, text: str) -> str | None:
    """Whether Python would still read this file, or why not.

    Worth three points in SWE-agent's ablation and free from the standard
    library. A file left unparseable is worse than a refused edit: the model
    finds out one test run later and spends the next turns debugging its own
    typo instead of the task. Anything that is not Python is left to whatever
    tools that language has.
    """
    if path.suffix != ".py":
        return None
    try:
        compile(text, str(path), "exec")
    except SyntaxError as exc:
        return f"{exc.msg} (line {exc.lineno})"
    return None


async def _edit_file(workdir: Path, args: dict[str, Any]) -> str:
    path = resolve_path(workdir, args["path"])
    if not path.is_file():
        raise ToolError(f"no such file: {args['path']}")
    old, new = str(args.get("old", "")), str(args.get("new", ""))
    if old == new:
        raise ToolError("`old` and `new` are the same; that edit would do nothing")

    text = path.read_text(encoding="utf-8")
    found = _place(text, old)
    if found is None:
        raise ToolError(
            f"could not find that text in {args['path']}. It has to match the "
            f"file exactly, indentation included -- read the file and copy the "
            f"lines you mean"
        )
    matched, count = found
    if count > 1:
        raise ToolError(
            f"that text appears {count} times in {args['path']}; include more "
            f"of the lines around it so there is only one place it can mean"
        )
    # `_loosened` may have been what matched, in which case the replacement
    # lands in the loosened text -- which is the file with its line endings
    # normalised and its trailing spaces gone. Both are changes nobody minds.
    body = text if matched in text else _loosened(text)
    updated = body.replace(matched, new, 1)

    broken = _would_parse(path, updated)
    if broken:
        raise ToolError(f"that edit would not parse as Python: {broken}")
    path.write_text(updated, encoding="utf-8")
    return f"replaced one occurrence in {args['path']}"


async def _append_file(workdir: Path, args: dict[str, Any]) -> str:
    """Add to the end of a file, which was four of five surgeries in a run.

    `cat >> file << 'EOF'` is how a model reaches for this, and a Windows
    shell answers `<<은(는) 예상되지 않았습니다`. The other spelling seen in
    the wild wrote a temporary file, appended it, and deleted it again.
    """
    path = resolve_path(workdir, args["path"])
    if not path.is_file():
        # Making a file is `write_file`'s job. A typo in a path here should
        # not quietly become a new file nobody asked for.
        raise ToolError(f"no such file: {args['path']} -- use write_file to make one")
    content = str(args.get("content", ""))
    with path.open("a", encoding="utf-8") as handle:
        handle.write(content)
    return f"added {len(content)} characters to the end of {args['path']}"


async def _list_dir(workdir: Path, args: dict[str, Any]) -> str:
    path = resolve_path(workdir, args.get("path", "."))
    if not path.is_dir():
        raise ToolError(f"no such directory: {args.get('path', '.')}")
    lines = []
    for entry in sorted(path.iterdir(), key=lambda e: (e.is_file(), e.name)):
        if entry.is_dir():
            lines.append(f"{entry.name}/")
        else:
            lines.append(f"{entry.name}  ({entry.stat().st_size} bytes)")
    return "\n".join(lines) or "(empty)"


def _checked_glob(pattern: str) -> str:
    """A glob may not climb out of the workdir, the way a path may not.

    `resolve_path` guards the tools that take one path; a pattern never becomes
    a path until it has matched, so it is checked here instead.
    """
    if ".." in pattern.split("/") or ".." in pattern.split("\\"):
        raise ToolError("glob patterns may not contain '..'")
    return pattern


async def _glob_files(workdir: Path, args: dict[str, Any]) -> str:
    pattern = _checked_glob(args["pattern"])
    matches = sorted(
        p.relative_to(workdir).as_posix()
        for p in workdir.glob(pattern)
        if p.is_file()
    )
    if len(matches) > _GLOB_CAP:
        return "\n".join(matches[:_GLOB_CAP]) + f"\n... [{len(matches) - _GLOB_CAP} more]"
    return "\n".join(matches) or "(no matches)"


async def _search_files(workdir: Path, args: dict[str, Any]) -> str:
    """Find a pattern across files, and say where without saying too much.

    Searching a repository was the shell's job, and a third of the shell
    commands in a measured run were `grep` -- one of which died on a Windows
    shell for spelling its paths the POSIX way. Doing it here is the same
    reasoning that put `env` on `run_command`: take the shell's dialect out of
    something that was never about the shell.

    **Both caps matter more than they look.** SWE-agent measured an
    unsummarized, iterative search scoring six points *below* having no search
    at all: results that fill the context are worse than no results. So the
    answer is bounded twice, in matches and in line length.
    """
    try:
        expression = re.compile(str(args["pattern"]))
    except re.error as exc:
        raise ToolError(f"not a usable search pattern: {exc}") from exc
    pattern = _checked_glob(str(args.get("glob", "**/*")))
    limit = int(args.get("max_results", _SEARCH_CAP) or _SEARCH_CAP)

    hits: list[str] = []
    dropped = 0
    for path in sorted(workdir.glob(pattern)):
        if not path.is_file():
            continue
        relative = path.relative_to(workdir)
        # `.git` and its like: a run's folder is a git copy, so this is packs
        # and objects -- noise at best, and binary at worst.
        if any(part.startswith(".") for part in relative.parts):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue  # not text, or not readable; either way not searchable
        for number, line in enumerate(text.splitlines(), start=1):
            if not expression.search(line):
                continue
            if len(hits) >= limit:
                dropped += 1
                continue
            clipped = line if len(line) <= _LINE_CAP else line[:_LINE_CAP] + "..."
            hits.append(f"{relative.as_posix()}:{number}: {clipped}")
    if not hits:
        return "(no matches)"
    if dropped:
        hits.append(f"... [{dropped} more]")
    return "\n".join(hits)


def _schema(props: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required}


FILES_TOOLS: list[Tool] = [
    Tool(
        ToolDef(
            name="read_file",
            description=(
                "Read a text file, with line numbers. Paths are relative to the "
                "working directory. Give `offset` and `limit` to read a window "
                "rather than the whole file -- a long file read whole stays in "
                "the conversation and is sent again on every turn after it. "
                "search_files answers with line numbers you can use here."
            ),
            input_schema=_schema(
                {
                    "path": {"type": "string"},
                    "offset": {
                        "type": "number",
                        "description": "first line to read, counting from 1",
                    },
                    "limit": {"type": "number", "description": "how many lines"},
                },
                ["path"],
            ),
        ),
        _read_file,
    ),
    Tool(
        ToolDef(
            name="write_file",
            description="Write a text file, creating parent directories as needed.",
            input_schema=_schema(
                {"path": {"type": "string"}, "content": {"type": "string"}}, ["path"]
            ),
        ),
        _write_file,
    ),
    Tool(
        ToolDef(
            name="edit_file",
            description=(
                "Change one place in a file: `old` is replaced by `new`. Prefer "
                "this to rewriting a whole file with write_file -- the parts you "
                "did not mean to touch cannot come back different, and the file's "
                "body does not have to travel. `old` must match exactly, "
                "indentation included, and must appear exactly once; if it "
                "appears more than once, include more of the surrounding lines."
            ),
            input_schema=_schema(
                {
                    "path": {"type": "string"},
                    "old": {"type": "string", "description": "text to replace"},
                    "new": {"type": "string", "description": "what to put there"},
                },
                ["path", "old", "new"],
            ),
        ),
        _edit_file,
    ),
    Tool(
        ToolDef(
            name="append_file",
            description=(
                "Add text to the end of an existing file. Use this rather than "
                "a shell redirect: heredocs and `>>` are spelled differently "
                "from one shell to the next, and some do not have them at all."
            ),
            input_schema=_schema(
                {"path": {"type": "string"}, "content": {"type": "string"}},
                ["path", "content"],
            ),
        ),
        _append_file,
    ),
    Tool(
        ToolDef(
            name="list_dir",
            description="List a directory. Omit path for the working directory itself.",
            input_schema=_schema({"path": {"type": "string"}}, []),
        ),
        _list_dir,
    ),
    Tool(
        ToolDef(
            name="glob_files",
            description="Find files by glob pattern, e.g. '**/*.py'.",
            input_schema=_schema({"pattern": {"type": "string"}}, ["pattern"]),
        ),
        _glob_files,
    ),
    Tool(
        ToolDef(
            name="search_files",
            description=(
                "Search file contents for a regular expression and get back "
                "'path:line: text' for each match. Prefer this to running grep "
                "in a shell: it does not depend on which shell this machine "
                "has. Narrow with `glob` when you know the file type. The "
                "answer is capped, and says how many matches it left out."
            ),
            input_schema=_schema(
                {
                    "pattern": {"type": "string", "description": "regular expression"},
                    "glob": {
                        "type": "string",
                        "description": "which files to search; defaults to all",
                    },
                    "max_results": {"type": "number"},
                },
                ["pattern"],
            ),
        ),
        _search_files,
    ),
]
