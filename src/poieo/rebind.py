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
from typing import TYPE_CHECKING, Sequence

from .errors import BindingError, SpecError

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .binding import ProviderSpec
    from .detect import Engine

# Two spaces, as everything poieo writes uses and as good as every hand-kept
# YAML file does. Only used for blocks this module creates.
INDENT = "  "

# What a name written into this file may be. Every one of them is composed into
# a line by hand -- `f"{INDENT}{key}:"` -- and YAML reads a newline as the end of
# that line, so a name carrying one is not a bad name, it is a second key. That
# is how a typed-in `api_key_env` came to be able to add a `default:` block
# pointing the whole project at somebody else's model, or a `base_url:` sending
# a real credential to another host.
#
# Checked at the door rather than caught afterwards, because the check
# afterwards reloads the file and asks whether it still means what was asked
# for -- and an *added* key means the file says more, not something else.
#
# `\Z` and not `$`, which also matches before a trailing newline and would have
# let the first line of an injected block through as long as it ended the value.
#
# No slash either, and that one is not about YAML: a slash is what separates the
# endpoint from the model in every reference the product prints and takes back,
# so `office/eu` names an endpoint nothing can ever refer to again.
#
# `\w` and not `[A-Za-z0-9_]`, because `detect._named_for` derives a name with
# `\w` and this has to accept everything that writes. Spelt in ASCII it refused
# `http://사무실:8000` and `http://münchen-box:8000` -- addresses detection reads
# a perfectly good key off -- and two modules disagreeing about what a name is
# is how a product ends up with an option that cannot be used without another.
_NAME = (
    re.compile(r"[\w.][\w.-]*\Z"),
    "letters, digits, `-`, `_` or `.`, and may not start with `-`",
)

# An environment variable's name, as every shell defines one. Narrower than
# `_NAME` on purpose: a value that cannot name a variable would have failed at
# the project's first run instead, with nothing pointing back at the line that
# wrote it.
_VARIABLE = (re.compile(r"[A-Za-z_][A-Za-z0-9_]*\Z"), "letters, digits and `_`, starting with a letter or `_`")

# A role is held to the line and no further. Nothing in this product spells one
# with a space in it, but a graph's `role:` is a free string and a rule invented
# here would refuse a binding somebody already keeps -- so this refuses only what
# genuinely cannot be written down: a value that would not stay on its own line.
_ONE_LINE = (re.compile(r"[^\r\n]+\Z"), "any one line -- a name split over two is two keys, not one")


def _plain(kind: str, value: str, allowed: tuple[re.Pattern[str], str] = _NAME) -> str:
    """``value``, if it is a name this may write down. Raises if it is not."""
    pattern, described = allowed
    if not pattern.match(value):
        raise SpecError(f"{kind} {value!r} is not a name -- it may hold {described}")
    return value


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
    depth = len(lines[siblings[0]]) - len(lines[siblings[0]].lstrip()) if siblings else len(INDENT)
    pad = " " * depth
    at = (siblings[-1] + 1) if siblings else end
    lines[at:at] = [
        f"{pad}{role}:",
        f"{pad}{INDENT}provider: {provider}",
        f"{pad}{INDENT}model: {_quoted(model)}",
    ]
    return "\n".join(lines) + "\n"


def _as_declared(engine: "Engine") -> "ProviderSpec":
    """What :func:`declare`'s block for this engine is supposed to read back as.

    Everything else on a `ProviderSpec` -- headers, a timeout, a retry count --
    stays at its default, because this writes three lines and nothing that
    writes three lines should be able to produce a fourth.
    """
    from .binding import ProviderSpec

    return ProviderSpec(type=engine.type, base_url=engine.base_url, api_key_env=engine.api_key_env or None)


def already(path: Path, engine: "Engine") -> str | None:
    """Why this binding already reaches that endpoint, in words, or None.

    Read from the **file**, not from a spec somebody is holding: a daemon's
    in-memory copy can be a step behind a terminal edit, and answering from it
    refused an endpoint the file does not have -- while the same command in the
    terminal accepted it. `declare` reads the file too, so this is the same
    question asked one moment earlier, in order to say something better than
    "nothing new" about it.
    """
    from .binding import load_binding
    from .detect import declared_as

    providers = load_binding(path).providers
    name = declared_as(providers, engine.key, engine.type, engine.base_url)
    if name is None:
        return None
    if name == engine.key:
        return (
            f"{path} already declares '{name}' -- give this one another name, "
            f"since one already there is never overwritten"
        )
    return f"{path} already reaches that endpoint, as '{name}'"


def declare(path: Path, engines: "Sequence[Engine]") -> list[str]:
    """Add each engine to ``providers:`` that is not already there.

    Returns the keys actually added, so a caller with nothing to report can
    say so. **Never touches one that is already declared**: somebody may have
    pointed it at another port or another machine, and adding is adding -- it
    is not a second round of `init`. Nothing about `default:` moves either;
    choosing is what `config use` is for.
    """
    from .binding import load_binding
    from .detect import declared_as

    path = Path(path)
    original = path.read_text(encoding="utf-8")
    was = load_binding(path)

    # By address as well as by key. Filtering on the key alone wrote one server
    # into one file twice: an Ollama declared as `fast` is one this project
    # reaches, and adding it again under the name detection would have picked
    # is not adding an endpoint, it is adding a second word for one.
    fresh = [
        engine for engine in engines if declared_as(was.providers, engine.key, engine.type, engine.base_url) is None
    ]
    if not fresh:
        return []

    for engine in fresh:
        _plain("endpoint name", engine.key)
        if engine.api_key_env:
            _plain("api_key_env", engine.api_key_env, _VARIABLE)

    # Before the write, not after it: this is what the file will be checked
    # against once it has been read back, and building it is the second place
    # an engine can turn out to be undeclarable at all. Finding that out with a
    # half-edited file on disk would leave the one state this module exists to
    # make impossible.
    try:
        wanted = {engine.key: _as_declared(engine) for engine in fresh}
    except ValueError as exc:
        raise SpecError(f"cannot declare {', '.join(e.key for e in fresh)} in {path}: {exc}") from exc

    lines = original.splitlines()
    span = _top_level(lines, "providers")
    if span is None:
        raise SpecError(
            f"could not find `providers:` to add to in {path}. Open it and "
            f"declare {', '.join(e.key for e in fresh)} by hand -- this only "
            f"edits the ordinary block form poieo writes."
        )

    block: list[str] = []
    for engine in fresh:
        block.append(f"{INDENT}{engine.key}:")
        block.append(f"{INDENT * 2}type: {engine.type}")
        if engine.base_url is not None:
            # Absent, not empty, when the backend's own SDK knows where it
            # lives: a guessed address is worse than no address.
            block.append(f"{INDENT * 2}base_url: {engine.base_url}")
        if engine.api_key_env:
            # The variable's **name**. A hosted endpoint wants a key and this
            # file is one people commit, so the name lives here and the value
            # lives in the environment -- see providers.credential_for.
            block.append(f"{INDENT * 2}api_key_env: {engine.api_key_env}")

    body = [i for i in range(span[0] + 1, span[1]) if lines[i].strip()]
    at = (body[-1] + 1) if body else span[1]
    lines[at:at] = block

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        now = load_binding(path)
    except SpecError as exc:
        path.write_text(original, encoding="utf-8")
        raise SpecError(f"adding to {path} would have broken it ({exc}); it has been left exactly as it was") from exc

    added = [engine.key for engine in fresh]
    if not set(added) <= set(now.providers):
        path.write_text(original, encoding="utf-8")
        raise SpecError(f"{path} did not take {added} as expected; it is unchanged")

    # Adding is adding. Asking only whether the new keys arrived says nothing
    # about what else the file now means -- a written line that ended up being
    # two would pass that. So the whole binding has to read back as the old one
    # plus exactly the endpoints asked for: nothing else moved, and each new
    # endpoint saying what this composed for it and no more.
    kept = {key: spec for key, spec in now.providers.items() if key not in wanted}
    mine = {key: spec for key, spec in now.providers.items() if key in wanted}
    if (kept, mine, now.default, now.roles) != (was.providers, wanted, was.default, was.roles):
        path.write_text(original, encoding="utf-8")
        raise SpecError(
            f"adding {', '.join(added)} to {path} would have changed more of it than that; "
            f"it has been left exactly as it was"
        )
    return added


def point_at(path: Path, role: str, provider: str, model: str) -> None:
    """Point ``role`` at ``provider``'s ``model``, in the file, in place.

    Everything else -- comments included -- is left exactly as it was. Refuses
    before writing if the provider is not declared or the shape cannot be
    edited, and undoes itself if the result will not load.
    """
    from .binding import load_binding

    path = Path(path)
    _plain("role", role, _ONE_LINE)
    original = path.read_text(encoding="utf-8")

    declared = load_binding(path).providers
    if provider not in declared:
        raise SpecError(f"{path} declares no provider '{provider}'; it has: {', '.join(sorted(declared))}")

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
        raise SpecError(f"editing {path} would have broken it ({exc}); it has been left exactly as it was") from exc
