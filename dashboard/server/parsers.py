from __future__ import annotations

import csv
import io
from pathlib import Path
from typing import Any

import yaml


def csv_to_records(path: Path) -> list[dict[str, Any]]:
    """Parse a CSV file into a list of dicts.  Numbers are cast to float where possible."""
    text = path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    rows: list[dict[str, Any]] = []
    for row in reader:
        cast: dict[str, Any] = {}
        for k, v in row.items():
            if v is None or v == "":
                cast[k] = None
                continue
            try:
                cast[k] = float(v) if "." in v else int(v)
            except (ValueError, TypeError):
                cast[k] = v
        rows.append(cast)
    return rows


def load_yaml(path: Path) -> dict[str, Any]:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def is_path_allowed(path: Path, repo_root: Path, allowed_dirs: list[str]) -> bool:
    """Return True only if resolved path is inside one of the allowed directories."""
    try:
        resolved = path.resolve()
        for d in allowed_dirs:
            if resolved.is_relative_to((repo_root / d).resolve()):
                return True
    except Exception:
        pass
    return False
