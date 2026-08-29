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
    path = resolve_path(workdir, args["path"])
    if not path.is_file():
        raise ToolError(f"no such file: {args['path']}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > _READ_CAP:
        return text[:_READ_CAP] + f"\n... [truncated: file is {len(text)} characters]"
    return text


async def _write_file(workdir: Path, args: dict[str, Any]) -> str:
    path = resolve_path(workdir, args["path"])
    path.parent.mkdir(parents=True, exist_ok=True)
    content = str(args.get("content", ""))
    path.write_text(content, encoding="utf-8")
    return f"wrote {len(content)} characters to {args['path']}"


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
            description="Read a text file. Paths are relative to the working directory.",
            input_schema=_schema({"path": {"type": "string"}}, ["path"]),
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
