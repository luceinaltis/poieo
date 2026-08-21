"""File tools, confined to the working directory."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..providers.base import ToolDef
from . import Tool, ToolError

_READ_CAP = 200_000     # characters
_GLOB_CAP = 500         # paths


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


async def _glob_files(workdir: Path, args: dict[str, Any]) -> str:
    pattern = args["pattern"]
    if ".." in pattern.split("/") or ".." in pattern.split("\\"):
        raise ToolError("glob patterns may not contain '..'")
    matches = sorted(
        p.relative_to(workdir).as_posix()
        for p in workdir.glob(pattern)
        if p.is_file()
    )
    if len(matches) > _GLOB_CAP:
        return "\n".join(matches[:_GLOB_CAP]) + f"\n... [{len(matches) - _GLOB_CAP} more]"
    return "\n".join(matches) or "(no matches)"


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
]
