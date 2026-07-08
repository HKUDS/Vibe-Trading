from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ASTNode:
    op: str
    args: tuple[Any, ...] = ()
    value: str | int | float | None = None

    @property
    def depth(self) -> int:
        child_depths = [
            arg.depth for arg in self.args if isinstance(arg, ASTNode)
        ]
        return 1 + (max(child_depths) if child_depths else 0)

    @property
    def node_count(self) -> int:
        return 1 + sum(
            arg.node_count for arg in self.args if isinstance(arg, ASTNode)
        )

    def operators(self) -> set[str]:
        ops = set()
        if self.op != "field":
            ops.add(self.op)
        for arg in self.args:
            if isinstance(arg, ASTNode):
                ops |= arg.operators()
        return ops

    def fields(self) -> set[str]:
        output: set[str] = set()
        if self.op == "field" and isinstance(self.value, str):
            output.add(self.value)
        for arg in self.args:
            if isinstance(arg, ASTNode):
                output |= arg.fields()
        return output

    def windows(self) -> list[int]:
        values: list[int] = []
        for arg in self.args:
            if isinstance(arg, int):
                values.append(arg)
            elif isinstance(arg, ASTNode):
                values.extend(arg.windows())
        return values


@dataclass(frozen=True)
class ValidationResult:
    ok: bool
    errors: list[str]
