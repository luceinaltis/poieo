"""Changing a binding file without losing what a person wrote in it.

A binding is a file somebody keeps. The generated one carries its model
catalogue in comments; a hand-kept one carries whatever its owner put there.
Reading it with a YAML parser and writing it back would take all of that, so
this edits **the two lines it came for** and leaves every other byte alone.

Text surgery is fragile by nature, and this module is written on the
assumption that it will sometimes be wrong:

- it refuses before touching the file when it cannot find what it came to
  change, naming the file and the key so a person can do it by hand;
- and it verifies afterwards by **reloading**, restoring the original if the
  result does not parse or does not resolve the way it was asked to.

Design: docs/cli.md
"""

from __future__ import annotations

import re
from pathlib import Path

from .errors import BindingError, SpecError

# Two spaces, as everything poieo writes uses and as good as every hand-kept
# YAML file does. Only used for blocks this module creates.
INDENT = "  "


def _top_level(lines: list[str], key: str) -> tuple[int, int] | None:
    """The half-open line range of a top-level ``key:`` block, or None.

    A block runs from its key to the next line that starts in column zero and
    is neither blank nor a comment -- so trailing comments stay with the block
    above them, which is where a person put them.
    """
    opener = re.compile(rf"^{re.escape(key)}\s*:")
    for start, line in enumerate(lines):
        if line.startswith("#") or not opener.match(line):
            continue
        for end in range(start + 1, len(lines)):
            probe = lines[end]
            if not probe.strip() or probe.lstrip().startswith("#"):
                continue
            if not probe[:1].isspace():
                return start, end
        return start, len(lines)
    return None


def _child(lines: list[str], span: tuple[int, int], name: str) -> tuple[int, int] | None:
    """The range of ``name:`` nested one level inside ``span``."""
    start, end = span
    body = [(i, lines[i]) for i in range(start + 1, end) if lines[i].strip()]
    if not body:
        return None
    depth = len(body[0][1]) - len(body[0][1].lstrip())
    opener = re.compile(rf"^\s{{{depth}}}{re.escape(name)}\s*:")

    for position, (index, line) in enumerate(body):
        if line.lstrip().startswith("#") or not opener.match(line):
            continue
        for deeper, _ in body[position + 1 :]:
            if len(lines[deeper]) - len(lines[deeper].lstrip()) <= depth:
                return index, deeper
        return index, end
    return None


def _set_scalars(lines: list[str], span: tuple[int, int], values: dict[str, str]) -> bool:
    """Rewrite ``key: value`` lines that are direct children of ``span``.

    True when every key asked for was found and replaced. Deeper keys are not
    touched -- a `params:` block under the same role is somebody's tuning, and
    repointing a model is not a licence to undo it.
    """
    start, end = span
    body = [i for i in range(start + 1, end) if lines[i].strip()]
    if not body:
        return False
    depth = len(lines[body[0]]) - len(lines[body[0]].lstrip())

    left = dict(values)
    for index in body:
        line = lines[index]
        if len(line) - len(line.lstrip()) != depth or line.lstrip().startswith("#"):
            continue
        key = line.strip().split(":", 1)[0]
        if key in left:
            lines[index] = f"{' ' * depth}{key}: {left.pop(key)}"
    return not left


def _quoted(model: str) -> str:
    """Model ids carry colons and slashes; quoting keeps YAML's hands off."""
    return '"{}"'.format(model.replace("\\", "\\\\").replace('"', '\\"'))


def _repoint(text: str, role: str, provider: str, model: str) -> str:
    """``text`` with ``role`` pointed at ``provider``'s ``model``.

    Raises :class:`SpecError` naming the key it could not find, rather than
    guessing at a shape it does not recognise.
    """
    lines = text.splitlines()
    values = {"provider": provider, "model": _quoted(model)}

    if role == "default":
        span = _top_level(lines, "default")
        if span is None or not _set_scalars(lines, span, values):
            raise SpecError("default")
        return "\n".join(lines) + "\n"

    roles = _top_level(lines, "roles")
    if roles is None:
        # The generated file has no `roles:` key at all -- only a comment
        # showing one. Naming a role is what makes the block.
        block = [
            "",
            "roles:",
            f"{INDENT}{role}:",
            f"{INDENT * 2}provider: {provider}",
            f"{INDENT * 2}model: {_quoted(model)}",
        ]
        return "\n".join(lines + block) + "\n"

    existing = _child(lines, roles, role)
    if existing is not None:
        if not _set_scalars(lines, existing, values):
            raise SpecError(f"roles.{role}")
        return "\n".join(lines) + "\n"

    # A block that exists but does not name this role yet: insert at its end,
    # at whatever depth its siblings already use.
    start, end = roles
    siblings = [i for i in range(start + 1, end) if lines[i].strip()]
    depth = (
        len(lines[siblings[0]]) - len(lines[siblings[0]].lstrip())
        if siblings
        else len(INDENT)
    )
    pad = " " * depth
    at = (siblings[-1] + 1) if siblings else end
    lines[at:at] = [
        f"{pad}{role}:",
        f"{pad}{INDENT}provider: {provider}",
        f"{pad}{INDENT}model: {_quoted(model)}",
    ]
    return "\n".join(lines) + "\n"


def point_at(path: Path, role: str, provider: str, model: str) -> None:
    """Point ``role`` at ``provider``'s ``model``, in the file, in place.

    Everything else -- comments included -- is left exactly as it was. Refuses
    before writing if the provider is not declared or the shape cannot be
    edited, and undoes itself if the result will not load.
    """
    from .binding import load_binding

    path = Path(path)
    original = path.read_text(encoding="utf-8")

    declared = load_binding(path).providers
    if provider not in declared:
        raise SpecError(
            f"{path} declares no provider '{provider}'; it has: "
            f"{', '.join(sorted(declared))}"
        )

    try:
        updated = _repoint(original, role, provider, model)
    except SpecError as exc:
        raise SpecError(
            f"could not find `{exc}` to edit in {path}. Open it and set "
            f"provider to '{provider}' and model to '{model}' by hand -- this "
            f"only edits the ordinary block form it writes."
        ) from exc

    path.write_text(updated, encoding="utf-8")
    try:
        resolved = load_binding(path).resolve(role)
        if (resolved.provider_name, resolved.model) != (provider, model):
            raise BindingError(f"reads back as {resolved.provider_name}/{resolved.model}")
    except (SpecError, BindingError) as exc:
        # Surgery is verified by reloading, and a bad result is undone rather
        # than left on somebody's disk.
        path.write_text(original, encoding="utf-8")
        raise SpecError(
            f"editing {path} would have broken it ({exc}); it has been left "
            f"exactly as it was"
        ) from exc
