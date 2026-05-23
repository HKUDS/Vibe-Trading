"""Result type for explicit error handling. Never raise exceptions in domain code."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Generic, TypeVar

T = TypeVar("T")
E = TypeVar("E")


@dataclass(frozen=True, slots=True)
class Ok(Generic[T]):
    """Successful result."""

    value: T


@dataclass(frozen=True, slots=True)
class Err(Generic[E]):
    """Failed result."""

    error: E


type Result[T, E] = Ok[T] | Err[E]


def is_ok(result: Result[Any, Any]) -> bool:
    """Check if result is Ok."""
    return isinstance(result, Ok)


def is_err(result: Result[Any, Any]) -> bool:
    """Check if result is Err."""
    return isinstance(result, Err)


def unwrap(result: Result[T, Any]) -> T:
    """Unwrap Ok value or raise."""
    if isinstance(result, Ok):
        return result.value
    raise ValueError(f"Cannot unwrap Err: {result.error}")


def unwrap_or(result: Result[T, Any], default: T) -> T:
    """Unwrap Ok value or return default."""
    if isinstance(result, Ok):
        return result.value
    return default
