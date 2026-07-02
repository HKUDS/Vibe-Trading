"""Upload and Shadow Account report HTTP routes.

Mounted by ``agent/api_server.py`` via ``register_uploads_routes(app, ...)``.
"""

from __future__ import annotations

import re
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable

from fastapi import Depends, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

UPLOADS_DIR = Path(__file__).resolve().parent.parent.parent / "uploads"
MAX_UPLOAD_SIZE = 50 * 1024 * 1024  # 50 MB
_UPLOAD_CHUNK_SIZE = 1024 * 1024  # 1 MB

_BLOCKED_UPLOAD_EXT = {
    # binaries / executables we should never accept
    ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".app", ".dmg",
    ".so", ".dll", ".dylib",
    # executable-adjacent source, shell, config, and template files
    ".py", ".pyw", ".sh", ".bash", ".zsh", ".fish", ".ps1",
    ".yaml", ".yml", ".j2", ".jinja", ".jinja2", ".template",
    # archives — don't auto-extract; user can unpack locally
    ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
}

_BLOCKED_UPLOAD_NAMES = {
    "dockerfile",
    "containerfile",
}

_SHADOW_ID_RE = re.compile(r"^shadow_[0-9a-f]{8}$")

# ---------------------------------------------------------------------------
# Registration
# ---------------------------------------------------------------------------

AuthDep = Callable[..., Awaitable[Any] | Any]


def register_uploads_routes(
    app: FastAPI,
    require_auth: AuthDep | None = None,
) -> None:
    """Mount the upload routes onto ``app``.

    Args:
        app: The host FastAPI app.
        require_auth: Header-auth dependency for JSON endpoints.

    For backwards compatibility, when the dependency callable is not passed
    explicitly we resolve it from the host ``api_server`` module via
    ``sys.modules``. Prefer the explicit form in new call sites.
    """
    if require_auth is None:
        import sys as _sys

        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        if host is None:  # pragma: no cover - only triggers on unusual import setups
            raise RuntimeError(
                "register_uploads_routes: api_server module not in sys.modules; "
                "pass require_auth explicitly"
            )
        require_auth = host.require_auth

    # Resolve host attributes at call time so existing tests and operator
    # overrides like ``monkeypatch.setattr(api_server, "UPLOADS_DIR", ...)`` work.
    def _host_uploads_dir() -> Path:
        import sys as _sys

        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return host.UPLOADS_DIR if host else UPLOADS_DIR

    def _host_max_upload_size() -> int:
        import sys as _sys

        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return host.MAX_UPLOAD_SIZE if host else MAX_UPLOAD_SIZE

    def _host_chunk_size() -> int:
        import sys as _sys

        host = _sys.modules.get("api_server") or _sys.modules.get("agent.api_server")
        return host._UPLOAD_CHUNK_SIZE if host else _UPLOAD_CHUNK_SIZE

    @app.get("/shadow-reports/{shadow_id}", dependencies=[Depends(require_auth)])
    async def get_shadow_report(shadow_id: str, format: str = "html"):
        """Serve a rendered Shadow Account report.

        Reports live under ``~/.vibe-trading/shadow_reports/<shadow_id>.{html,pdf}``.
        """
        if not _SHADOW_ID_RE.match(shadow_id):
            raise HTTPException(status_code=400, detail="invalid shadow_id")
        if format not in ("html", "pdf"):
            raise HTTPException(status_code=400, detail="format must be html or pdf")

        reports_dir = Path.home() / ".vibe-trading" / "shadow_reports"
        path = reports_dir / f"{shadow_id}.{format}"
        if not path.exists():
            raise HTTPException(status_code=404, detail=f"Shadow report not found: {shadow_id}.{format}")

        media_type = "text/html; charset=utf-8" if format == "html" else "application/pdf"
        return FileResponse(
            path,
            media_type=media_type,
            headers={"Content-Disposition": f'inline; filename="{shadow_id}.{format}"'},
        )

    @app.post("/upload", dependencies=[Depends(require_auth)])
    async def upload_file(file: UploadFile):
        """Upload any document or data file (max 50MB).

        Accepts most common formats: PDF, Word, Excel, PowerPoint, images,
        CSV/TSV, plain text, JSON, and TOML. Executables, executable-adjacent
        source/config/template files, and archives are rejected.
        """
        if not file.filename:
            raise HTTPException(status_code=400, detail="Missing filename")
        filename = Path(file.filename).name
        ext = Path(filename).suffix.lower()
        if ext in _BLOCKED_UPLOAD_EXT or filename.lower() in _BLOCKED_UPLOAD_NAMES:
            raise HTTPException(
                status_code=400,
                detail="This file type is not allowed for upload.",
            )

        uploads_dir = _host_uploads_dir()
        max_size = _host_max_upload_size()
        chunk_size = _host_chunk_size()

        safe_name = f"{uuid.uuid4().hex}{ext}"
        dest = uploads_dir / safe_name
        total_size = 0

        try:
            uploads_dir.mkdir(parents=True, exist_ok=True)
            with dest.open("wb") as handle:
                while True:
                    chunk = await file.read(chunk_size)
                    if not chunk:
                        break
                    total_size += len(chunk)
                    if total_size > max_size:
                        handle.close()
                        if dest.exists():
                            dest.unlink()
                        raise HTTPException(
                            status_code=413,
                            detail=f"File too large (limit {max_size // (1024 * 1024)} MB)",
                        )
                    handle.write(chunk)
        except HTTPException:
            raise
        except OSError as exc:
            if dest.exists():
                dest.unlink()
            raise HTTPException(
                status_code=500,
                detail="Upload failed while storing the file. Please retry or choose a different file.",
            ) from exc
        finally:
            await file.close()

        return {
            "status": "ok",
            "file_path": f"uploads/{safe_name}",
            "filename": filename,
        }
