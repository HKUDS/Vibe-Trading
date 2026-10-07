"""Stage generated PDFs for authenticated download and channel delivery."""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from src.config.paths import get_runtime_root


def reports_root() -> Path:
    """Return the runtime-only generated report directory."""
    return get_runtime_root() / "generated_reports"


def publish_pdf(path: Path) -> dict[str, str]:
    """Stage an actual PDF and return its opaque download handle.

    Args:
        path: Successful report output, not a model-supplied download path.

    Returns:
        Metadata for the staged file, shared by HTTP and IM transports.

    Raises:
        ValueError: The file is not a PDF.
    """
    with path.open("rb") as stream:
        if stream.read(5) != b"%PDF-":
            raise ValueError("The generated report is not a valid PDF")
    report_id = uuid.uuid4().hex
    directory = reports_root() / report_id
    directory.mkdir(parents=True)
    destination = directory / path.name
    shutil.copyfile(path, destination)
    return {"report_id": report_id, "download_url": f"/api/reports/{report_id}",
            "filename": path.name, "media_type": "application/pdf"}


def report_path(report_id: str) -> Path | None:
    """Resolve an opaque report ID, refusing traversal and symlink escapes."""
    if len(report_id) != 32 or any(char not in "0123456789abcdef" for char in report_id):
        return None
    directory = reports_root() / report_id
    if not directory.is_dir() or directory.is_symlink():
        return None
    files = [path for path in directory.iterdir() if path.suffix.lower() == ".pdf" and path.is_file() and not path.is_symlink()]
    return files[0] if len(files) == 1 else None
