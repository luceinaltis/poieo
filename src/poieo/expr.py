"""A small sandboxed expression language shared by prompts, routers and tasks.

* prompt templates -- ``"Classify: {{ input.text }}"``
* router conditions -- ``"category.lower() == 'bug' and state.retries < 3"``
* a task's ``then:`` branches -- ``"run.change and run.steps > 2"``

All three go through :func:`evaluate`, which walks a whitelist of AST nodes.
Anything outside it (imports, lambdas, comprehensions, dunder access, ...) is
rejected at parse time rather than at run time.

All three were typed into a YAML file, so ``true``, ``false`` and ``null`` are
accepted alongside Python's own spelling.

Design: docs/graph.md
"""

from __future__ import annotations

import ast
import json
import re
from typing import Any, Mapping

from .errors import ExpressionError

# Nodes the sandbox is willing to execute. Everything else raises.
_ALLOWED_NODES: tuple[type[ast.AST], ...] = (
    ast.Expression,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.BoolOp,
    ast.And,
    ast.Or,
    ast.UnaryOp,
    ast.Not,
    ast.USub,
    ast.UAdd,
    ast.BinOp,
    ast.Add,
    ast.Sub,
    ast.Mult,
    ast.Div,
    ast.FloorDiv,
    ast.Mod,
    ast.Pow,
    ast.Compare,
    ast.Eq,
    ast.NotEq,
    ast.Lt,
    ast.LtE,
    ast.Gt,
    ast.GtE,
    ast.Is,
    ast.IsNot,
    ast.In,
    ast.NotIn,
    ast.Call,
    ast.keyword,
    ast.Attribute,
    ast.Subscript,
    ast.Slice,
    ast.List,
    ast.Tuple,
    ast.Dict,
    ast.Set,
    ast.IfExp,
    ast.Starred,
)

_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs,
    "all": all,
    "any": any,
    "bool": bool,
    "dict": dict,
    "float": float,
    "int": int,
    "len": len,
    "list": list,
    "max": max,
    "min": min,
    "round": round,
    "sorted": sorted,
    "str": str,
    "sum": sum,
    "tuple": tuple,
    "json_loads": json.loads,
    "json_dumps": json.dumps,
}

# Every expression poieo evaluates was typed into a YAML file, where these are
# how the three literals are spelled. Aliases, not replacements: the source is
# still parsed as Python and `True` still works. Without them a condition
# reading `when: "true"` fails with "unknown name" -- and in a task's `then:`
# block that failure is logged and skipped rather than raised, which is the
# quietest possible way to have a branch that never fires.
_YAML_LITERALS: dict[str, Any] = {"true": True, "false": False, "null": None}

# Attribute access is allowed, but only on plain data and only for public names.
# This keeps ``"BUG".lower()`` working without exposing ``().__class__`` walks.
_ATTR_SAFE_TYPES = (str, list, tuple, dict, set, int, float, bool)

_MAX_EXPR_LENGTH = 4000


class DotDict(dict):
    """A dict whose keys are also reachable as attributes.

    Graph authors write ``input.text``; run data arrives as plain JSON. Wrapping
    it once at the boundary keeps both spellings working, recursively.
    """

    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:  # pragma: no cover - message matters more than path
            raise AttributeError(name) from exc

    def __setattr__(self, name: str, value: Any) -> None:
        self[name] = value


def wrap(value: Any) -> Any:
    """Recursively wrap mappings in :class:`DotDict` for attribute access."""
    if isinstance(value, DotDict):
        return value
    if isinstance(value, Mapping):
        return DotDict({k: wrap(v) for k, v in value.items()})
    if isinstance(value, list):
        return [wrap(v) for v in value]
    if isinstance(value, tuple):
        return tuple(wrap(v) for v in value)
    return value


def unwrap(value: Any) -> Any:
    """Inverse of :func:`wrap`, for anything that gets persisted as JSON."""
    if isinstance(value, Mapping):
        return {k: unwrap(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [unwrap(v) for v in value]
    return value


def _check(tree: ast.AST) -> None:
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_NODES):
            raise ExpressionError(
                f"{type(node).__name__} is not allowed in poieo expressions"
            )
        if isinstance(node, ast.Attribute) and node.attr.startswith("_"):
            raise ExpressionError(f"access to private attribute '{node.attr}' is denied")
        if isinstance(node, ast.Name) and node.id.startswith("_"):
            raise ExpressionError(f"access to private name '{node.id}' is denied")


class _Evaluator(ast.NodeVisitor):
    def __init__(self, scope: Mapping[str, Any]):
        self.scope = scope

    # -- entry ---------------------------------------------------------------
    def run(self, tree: ast.Expression) -> Any:
        return self.visit(tree.body)

    def generic_visit(self, node: ast.AST) -> Any:  # pragma: no cover - guarded above
        raise ExpressionError(f"unsupported expression element: {type(node).__name__}")

    # -- literals ------------------------------------------------------------
    def visit_Constant(self, node: ast.Constant) -> Any:
        return node.value

    def visit_List(self, node: ast.List) -> Any:
        return [self.visit(e) for e in node.elts]

    def visit_Tuple(self, node: ast.Tuple) -> Any:
        return tuple(self.visit(e) for e in node.elts)

    def visit_Set(self, node: ast.Set) -> Any:
        return {self.visit(e) for e in node.elts}

    def visit_Dict(self, node: ast.Dict) -> Any:
        return {
            (self.visit(k) if k is not None else None): self.visit(v)
            for k, v in zip(node.keys, node.values)
        }

    # -- names and access ----------------------------------------------------
    def visit_Name(self, node: ast.Name) -> Any:
        if node.id in self.scope:
            return self.scope[node.id]
        if node.id in _SAFE_BUILTINS:
            return _SAFE_BUILTINS[node.id]
        # Last, so run data named `true` is still that run's own data.
        if node.id in _YAML_LITERALS:
            return _YAML_LITERALS[node.id]
        raise ExpressionError(f"unknown name '{node.id}'")

    def visit_Attribute(self, node: ast.Attribute) -> Any:
        target = self.visit(node.value)
        if isinstance(target, Mapping):
            if node.attr in target:
                return target[node.attr]
            if not hasattr(target, node.attr):
                # Say what was actually there. A template naming a key the run
                # does not carry is the commonest authoring mistake, and
                # "journal" on its own tells nobody anything.
                known = ", ".join(sorted(str(k) for k in target)) or "nothing"
                raise ExpressionError(f"no '{node.attr}' here; this has: {known}")
        if isinstance(target, _ATTR_SAFE_TYPES):
            try:
                return getattr(target, node.attr)
            except AttributeError as exc:
                raise ExpressionError(str(exc)) from exc
        raise ExpressionError(
            f"cannot read attribute '{node.attr}' from {type(target).__name__}"
        )

    def visit_Subscript(self, node: ast.Subscript) -> Any:
        target = self.visit(node.value)
        key = self.visit(node.slice)
        try:
            return target[key]
        except (KeyError, IndexError, TypeError) as exc:
            raise ExpressionError(f"invalid subscript: {exc}") from exc

    def visit_Slice(self, node: ast.Slice) -> Any:
        return slice(
            self.visit(node.lower) if node.lower else None,
            self.visit(node.upper) if node.upper else None,
            self.visit(node.step) if node.step else None,
        )

    # -- operators -----------------------------------------------------------
    def visit_BoolOp(self, node: ast.BoolOp) -> Any:
        if isinstance(node.op, ast.And):
            result: Any = True
            for value in node.values:
                result = self.visit(value)
                if not result:
                    return result
            return result
        result = False
        for value in node.values:
            result = self.visit(value)
            if result:
                return result
        return result

    def visit_UnaryOp(self, node: ast.UnaryOp) -> Any:
        operand = self.visit(node.operand)
        if isinstance(node.op, ast.Not):
            return not operand
        if isinstance(node.op, ast.USub):
            return -operand
        return +operand

    _BINOPS = {
        ast.Add: lambda a, b: a + b,
        ast.Sub: lambda a, b: a - b,
        ast.Mult: lambda a, b: a * b,
        ast.Div: lambda a, b: a / b,
        ast.FloorDiv: lambda a, b: a // b,
        ast.Mod: lambda a, b: a % b,
    }

    def visit_BinOp(self, node: ast.BinOp) -> Any:
        left, right = self.visit(node.left), self.visit(node.right)
        if isinstance(node.op, ast.Pow):
            # Bound the exponent: 10 ** 10 ** 10 would otherwise hang the daemon.
            if isinstance(right, (int, float)) and right > 64:
                raise ExpressionError("exponent too large")
            return left**right
        handler = self._BINOPS.get(type(node.op))
        if handler is None:
            raise ExpressionError(f"unsupported operator: {type(node.op).__name__}")
        try:
            return handler(left, right)
        except (TypeError, ZeroDivisionError) as exc:
            raise ExpressionError(str(exc)) from exc

    _CMPOPS = {
        ast.Eq: lambda a, b: a == b,
        ast.NotEq: lambda a, b: a != b,
        ast.Lt: lambda a, b: a < b,
        ast.LtE: lambda a, b: a <= b,
        ast.Gt: lambda a, b: a > b,
        ast.GtE: lambda a, b: a >= b,
        ast.Is: lambda a, b: a is b,
        ast.IsNot: lambda a, b: a is not b,
        ast.In: lambda a, b: a in b,
        ast.NotIn: lambda a, b: a not in b,
    }

    def visit_Compare(self, node: ast.Compare) -> Any:
        left = self.visit(node.left)
        for op, comparator in zip(node.ops, node.comparators):
            right = self.visit(comparator)
            handler = self._CMPOPS.get(type(op))
            if handler is None:
                raise ExpressionError(f"unsupported comparison: {type(op).__name__}")
            try:
                if not handler(left, right):
                    return False
            except TypeError as exc:
                raise ExpressionError(str(exc)) from exc
            left = right
        return True

    def visit_IfExp(self, node: ast.IfExp) -> Any:
        return self.visit(node.body) if self.visit(node.test) else self.visit(node.orelse)

    def visit_Call(self, node: ast.Call) -> Any:
        func = self.visit(node.func)
        if not callable(func):
            raise ExpressionError("attempted to call a non-callable value")
        args: list[Any] = []
        for arg in node.args:
            if isinstance(arg, ast.Starred):
                args.extend(self.visit(arg.value))
            else:
                args.append(self.visit(arg))
        kwargs = {kw.arg: self.visit(kw.value) for kw in node.keywords if kw.arg}
        try:
            return func(*args, **kwargs)
        except ExpressionError:
            raise
        except Exception as exc:
            raise ExpressionError(f"call failed: {exc}") from exc


def compile_expr(source: str) -> ast.Expression:
    """Parse and validate an expression, raising :class:`ExpressionError` early.

    Graph loading calls this for every condition and template so a typo surfaces
    at ``poieo validate`` time instead of halfway through a production run.
    """
    if len(source) > _MAX_EXPR_LENGTH:
        raise ExpressionError("expression is too long")
    try:
        tree = ast.parse(source.strip(), mode="eval")
    except SyntaxError as exc:
        raise ExpressionError(f"syntax error in {source.strip()!r}: {exc.msg}") from exc
    _check(tree)
    return tree


def evaluate(source: str | ast.Expression, scope: Mapping[str, Any]) -> Any:
    """Evaluate an expression against ``scope``."""
    tree = source if isinstance(source, ast.Expression) else compile_expr(source)
    return _Evaluator(scope).run(tree)


_PLACEHOLDER = re.compile(r"\{\{(.*?)\}\}", re.DOTALL)


def render(template: str, scope: Mapping[str, Any]) -> str:
    """Substitute every ``{{ expression }}`` in ``template``.

    Non-string results are JSON-encoded so a dict lands in the prompt as valid
    JSON rather than as a Python repr with single quotes.
    """

    def substitute(match: re.Match[str]) -> str:
        value = evaluate(match.group(1), scope)
        if isinstance(value, str):
            return value
        if value is None:
            return ""
        if isinstance(value, (Mapping, list, tuple)):
            return json.dumps(unwrap(value), ensure_ascii=False, indent=2)
        return str(value)

    return _PLACEHOLDER.sub(substitute, template)


def validate_template(template: str) -> None:
    """Parse every placeholder in ``template`` without evaluating it."""
    for match in _PLACEHOLDER.finditer(template):
        compile_expr(match.group(1))


# The fixed names `RunContext.scope()` puts in front of every template. A graph
# may add output aliases on top; those are not knowable from a node alone, and
# missing one only costs the nicer of two error messages.
_RUN_NAMES = frozenset({"input", "state", "nodes", "run"})
_ROOT = re.compile(r"\s*([A-Za-z_][A-Za-z_0-9]*)")


def reaches_for_run_data(text: str) -> str | None:
    """The first ``{{ … }}`` in ``text`` that reads the run's own data, if any.

    For text that is *not* a template -- a compiled script -- and where `{{`
    therefore means what the language says it means. `[][]int{{1,2},{3,4}}` is
    ordinary Go and must pass; `{{ input.floor }}` is somebody expecting a
    substitution that will not happen, and is worth catching at load.
    """
    for match in _PLACEHOLDER.finditer(text):
        root = _ROOT.match(match.group(1))
        if root and root.group(1) in _RUN_NAMES:
            return match.group(0)
    return None
