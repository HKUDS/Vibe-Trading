"""Repo-wide gate: a dataclass or ``NamedTuple`` field must not share its name
with a class-body binding that follows it.

``dataclasses._process_class`` resolves each field's default with
``default = getattr(cls, name, MISSING)`` *after* the class body has run. A
class-body binding of the same name therefore replaces the field's default with
whatever that binding evaluated to. There is no in-body spelling that keeps
both halves intact — reordering only moves the damage, and an explicit
``field(default=None)`` is overwritten the same way — so the two roles have to
be split across the class boundary.

Two shapes are caught, and the second is the quieter one:

* a field with a default (``market: str | None = None``) followed by a
  same-named ``def``/assignment — the default silently becomes that object
  (``repr`` and ``dataclasses.asdict`` then carry it, and JSON serialisation of
  the descriptor raises ``TypeError``);
* a field *without* a default (``kind: TriggerKind``) plus any same-named
  class-body binding — a required constructor argument silently becomes
  optional, defaulting to that object. Type checkers still report the field as
  required, so a caller that forgets it is not caught.

The gate is static and dependency-free on purpose: importing every module to
inspect the dataclasses for real would drag the whole optional-dependency
surface into a unit test. ``src/live/runtime/triggers.py`` is the one place in
the tree that used to trip this, which is exactly why it is pinned here rather
than left to review.

``ClassVar`` names are exempt: ``@dataclass`` ignores them entirely, so a
same-named binding cannot corrupt a field that never exists, and flagging the
pattern would be a false positive.

Deliberately out of scope: the mirror-image shape where a class-body member is
listed *before* the field and quietly replaced by the field's default (the
member stops being callable). That one is loud at the call site rather than
silent in the constructor, and flagging it would mean failing on ordinary
``ClassVar``-free dataclasses, so it stays a review item.

``typing.NamedTuple`` fails the same way: its metaclass reads
``_field_defaults`` from the finished class body, so both shapes apply there
too (it simply has no ``field(default_factory=...)`` spelling). The gate
therefore covers both class kinds.

Remediation note: the worked example binds the factory after the class body.
For a ``slots=True`` dataclass that rebinding replaces the slot descriptor and
breaks instance assignment, so rename the member instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SCAN_ROOT = REPO_ROOT / "agent"
# Test fixtures and test-local dataclasses are not part of the shipped surface;
# scanning them would also trip the gate on deliberately broken snippets.
EXCLUDED_DIRS = (REPO_ROOT / "agent" / "tests",)


def _is_dataclass(node: ast.ClassDef) -> bool:
    """True when the class carries a ``@dataclass`` decorator (any spelling)."""
    for decorator in node.decorator_list:
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Name) and target.id == "dataclass":
            return True
        if isinstance(target, ast.Attribute) and target.attr == "dataclass":
            return True
    return False


def _is_namedtuple(node: ast.ClassDef) -> bool:
    """True for ``class X(NamedTuple)`` under its usual import spellings."""
    for base in node.bases:
        name = ast.unparse(base).split("[", 1)[0]
        if name in {"NamedTuple", "typing.NamedTuple", "typing_extensions.NamedTuple"}:
            return True
    return False


def _class_body_bindings(node: ast.ClassDef) -> list[tuple[str, ast.stmt, str]]:
    """Every class-body statement that binds a bare name, in body order."""
    bindings: list[tuple[str, ast.stmt, str]] = []
    for stmt in node.body:
        if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bindings.append((stmt.name, stmt, f"def {stmt.name}"))
        elif isinstance(stmt, ast.AnnAssign):
            if isinstance(stmt.target, ast.Name) and stmt.value is not None:
                bindings.append((stmt.target.id, stmt, f"{stmt.target.id} = <value>"))
        elif isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name):
                    bindings.append((target.id, stmt, f"{target.id} = <value>"))
    return bindings


def _is_classvar(annotation: ast.expr) -> bool:
    """True for ``ClassVar[...]`` under any of its usual spellings.

    Aliased imports (``from typing import ClassVar as CV``) are not resolved;
    the tree does not use them, and a miss there is merely a false positive.
    """
    if isinstance(annotation, ast.Constant) and isinstance(annotation.value, str):
        try:
            annotation = ast.parse(annotation.value, mode="eval").body
        except SyntaxError:
            return False
    base = ast.unparse(annotation).split("[", 1)[0]
    return base in {"ClassVar", "typing.ClassVar", "typing_extensions.ClassVar"}


def _collisions(tree: ast.Module) -> list[str]:
    """Describe every dataclass/NamedTuple field shadowed by a class-body binding."""
    found: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef) or not (_is_dataclass(node) or _is_namedtuple(node)):
            continue

        annotated: dict[str, ast.AnnAssign] = {}
        for stmt in node.body:
            if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                if _is_classvar(stmt.annotation):
                    # ``@dataclass`` ignores ``ClassVar`` entirely: it never
                    # becomes a field or a constructor parameter, so a
                    # same-named binding cannot corrupt anything. Flagging it
                    # would be a false positive on a legitimate pattern.
                    continue
                annotated[stmt.target.id] = stmt

        bindings = _class_body_bindings(node)
        for field_name, field_stmt in annotated.items():
            same_name = [(stmt, text) for name, stmt, text in bindings if name == field_name]
            if not same_name:
                continue  # the field has no default and no same-named binding
            last_stmt, last_text = same_name[-1]
            # Two assignments can occupy one source line; only the actual
            # annotated statement owns the declared field default.
            if last_stmt is field_stmt:
                continue
            shape = (
                "required field silently becomes optional"
                if field_stmt.value is None
                else "field default silently replaced"
            )
            found.append(
                f"{node.name}.{field_name} (field line {field_stmt.lineno}) is shadowed by "
                f"`{last_text}` on line {last_stmt.lineno}: {shape}"
            )
    return found


def test_no_field_is_shadowed_by_a_class_body_binding() -> None:
    """No dataclass/NamedTuple in the tree may lose a field default to a same-named member."""
    failures: list[str] = []
    for path in sorted(SCAN_ROOT.rglob("*.py")):
        if any(path.is_relative_to(excluded) for excluded in EXCLUDED_DIRS):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError) as exc:  # pragma: no cover - unreadable file
            failures.append(f"{path.relative_to(REPO_ROOT)}: could not be parsed ({exc})")
            continue
        for detail in _collisions(tree):
            failures.append(f"{path.relative_to(REPO_ROOT)}: {detail}")

    assert not failures, (
        "A dataclass/NamedTuple field shares its name with a class-body binding, so the "
        "constructor default is that object instead of the declared one. Move the "
        "factory/attribute off the class body and bind it after the class "
        "definition (see src/live/runtime/triggers.py for the worked example):\n  "
        + "\n  ".join(failures)
    )


def _collisions_in(source: str) -> list[str]:
    """Run the detector over an in-memory snippet (no repository involved)."""
    return _collisions(ast.parse(source))


def test_default_field_shadowed_by_method_is_flagged() -> None:
    """Shape one: the declared default silently becomes the method."""
    failures = _collisions_in(
        """
from dataclasses import dataclass

@dataclass
class Broken:
    market: str | None = None

    @classmethod
    def market(cls, market: str):
        return market
"""
    )
    assert len(failures) == 1
    assert "Broken.market" in failures[0]
    assert "field default silently replaced" in failures[0]


def test_required_field_shadowed_by_method_is_flagged() -> None:
    """Shape two: a required argument silently becomes optional."""
    failures = _collisions_in(
        """
from dataclasses import dataclass

@dataclass
class Broken:
    kind: str

    @classmethod
    def kind(cls):
        return "factory"
"""
    )
    assert len(failures) == 1
    assert "Broken.kind" in failures[0]
    assert "required field silently becomes optional" in failures[0]


def test_default_factory_field_shadowed_is_flagged() -> None:
    """A same-named binding also silently drops a declared ``default_factory``."""
    failures = _collisions_in(
        """
from dataclasses import dataclass, field

@dataclass
class Broken:
    xs: list = field(default_factory=list)

    def xs(self):
        return "method"
"""
    )
    assert len(failures) == 1
    assert "Broken.xs" in failures[0]
    assert "field default silently replaced" in failures[0]


def test_namedtuple_field_shadowed_by_method_is_flagged() -> None:
    failures = _collisions_in(
        """
from typing import NamedTuple

class Broken(NamedTuple):
    market: str | None = None

    def market(self, market: str):
        return market
"""
    )
    assert len(failures) == 1
    assert "Broken.market" in failures[0]


def test_namedtuple_required_field_shadowed_is_flagged() -> None:
    failures = _collisions_in(
        """
import typing

class Broken(typing.NamedTuple):
    kind: str

    def kind(self):
        return "factory"
"""
    )
    assert len(failures) == 1
    assert "Broken.kind" in failures[0]
    assert "required field silently becomes optional" in failures[0]


def test_classvar_shadowing_is_not_flagged() -> None:
    """A ``ClassVar`` never becomes a field, so the same name is not a collision."""
    failures = _collisions_in(
        """
from dataclasses import dataclass
from typing import ClassVar

@dataclass
class Fine:
    registry: ClassVar[dict] = {}

    @classmethod
    def registry(cls):
        return cls
"""
    )
    assert failures == []


def test_quoted_classvar_shadowing_is_not_flagged() -> None:
    failures = _collisions_in(
        '''
from dataclasses import dataclass
from typing import ClassVar
import typing

@dataclass
class Fine:
    registry: "ClassVar[dict]" = {}
    other: "typing.ClassVar[dict]" = {}

    def registry(self):
        return None

    def other(self):
        return None
'''
    )
    assert failures == []


def test_same_line_overwrite_is_flagged() -> None:
    for declaration, shape in (
        ("value: int = 1; value = 2", "field default silently replaced"),
        ("value: int; value = 2", "required field silently becomes optional"),
    ):
        failures = _collisions_in(f"@dataclass\nclass Broken:\n    {declaration}\n")
        assert len(failures) == 1
        assert "Broken.value" in failures[0]
        assert shape in failures[0]


def test_mirror_image_shape_stays_out_of_scope() -> None:
    """Member first, field second: the default wins and the member breaks loudly."""
    failures = _collisions_in(
        """
from dataclasses import dataclass

@dataclass
class Mirror:
    @classmethod
    def market(cls):
        return None

    market: str | None = None
"""
    )
    assert failures == []


def test_clean_dataclass_is_not_flagged() -> None:
    failures = _collisions_in(
        """
from dataclasses import dataclass

@dataclass
class Fine:
    kind: str
    market: str | None = None

    @classmethod
    def interval(cls, interval_ms: int):
        return interval_ms
"""
    )
    assert failures == []


def test_unrelated_decorator_argument_is_not_a_dataclass_decorator() -> None:
    assert _collisions_in("""
@identity(dataclasses.dataclass())
class Ordinary:
    field: int = 1
    def field(self):
        return 2
""") == []
