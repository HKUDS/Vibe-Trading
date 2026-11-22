"""Optional OS-level sandboxing for shell tools.

The sandbox is opt-in.  When enabled, an unsupported platform or missing
backend fails closed before a command is started.
"""

from __future__ import annotations

import ast
import platform
import re
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from src.config.accessor import get_env_value


class SandboxUnavailableError(RuntimeError):
    """Raised when an enabled sandbox cannot be provided by this host."""


def _env_bool(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def enumerate_protected_runtime_paths(runtime_root: Path) -> tuple[Path, ...]:
    """Find broker/auth runtime paths from the source's path declarations.

    Root-level JSON config files and credential directories are hidden inside a
    shell sandbox.  The directory names are discovered from ``get_runtime_root``
    path expressions and connector ``CONFIG_FILENAME`` declarations so adding a
    connector does not require a second security list.
    """
    root = Path(runtime_root).expanduser().resolve()
    source_root = Path(__file__).resolve().parents[1]
    names: set[str] = set()
    config_files: set[str] = set()
    for source in source_root.rglob("*.py"):
        try:
            text = source.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (OSError, SyntaxError):
            continue
        if "get_runtime_root" in text:
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.BinOp)
                    and isinstance(node.op, ast.Div)
                    and isinstance(node.left, ast.Call)
                    and getattr(node.left.func, "id", getattr(node.left.func, "attr", None)) == "get_runtime_root"
                    and isinstance(node.right, ast.Constant)
                    and isinstance(node.right.value, str)
                ):
                    names.add(node.right.value.split("/", 1)[0])
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and len(node.targets) == 1:
                target = node.targets[0]
                if isinstance(target, ast.Name) and re.search(r"(^|_)(CONFIG_FILENAME|DB_FILENAME)$", target.id):
                    if isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                        config_files.add(node.value.value)
                if isinstance(target, ast.Name) and re.search(r"(^|_)FILENAMES$", target.id):
                    if isinstance(node.value, (ast.Tuple, ast.List)):
                        config_files.update(
                            element.value for element in node.value.elts
                            if isinstance(element, ast.Constant) and isinstance(element.value, str)
                        )
    # These are only selected when the codebase actually declares the matching
    # runtime path.  They cover the credential-bearing containers used by the
    # live connector and auth code.
    protected: set[Path] = {
        root / name for name in names if name in {"connectors", "auth", "live"}
    }
    protected.update(root / name for name in config_files if name.endswith(".json"))
    protected.update(root.glob("*.json"))
    return tuple(sorted(protected, key=lambda path: str(path)))


@dataclass(frozen=True)
class SandboxSettings:
    """Resolved shell sandbox settings."""

    enabled: bool = False
    network: bool = False
    backend: str | None = None
    runtime_root: Path | None = None

    @classmethod
    def from_env(cls, runtime_root: Path | None = None) -> "SandboxSettings":
        """Resolve settings without relying on the cached Pydantic config."""
        backend = get_env_value("VIBE_TRADING_SANDBOX_BACKEND", "").strip().lower() or None
        return cls(
            enabled=_env_bool(get_env_value("VIBE_TRADING_SANDBOX_ENABLED")),
            network=_env_bool(get_env_value("VIBE_TRADING_SANDBOX_NETWORK")),
            backend=backend,
            runtime_root=runtime_root,
        )

    def resolved_backend(self) -> str:
        """Return the supported backend name or raise when unavailable."""
        if not self.enabled:
            return "disabled"
        requested = self._selected_backend()
        if not requested or shutil.which(requested) is None:
            raise SandboxUnavailableError(
                f"sandbox is enabled but {requested or 'this platform'} is unavailable"
            )
        return requested

    def _selected_backend(self) -> str:
        """Select the platform backend without checking executable presence."""
        requested = self.backend
        if requested in {"sandbox-exec", "seatbelt"}:
            requested = "sandbox-exec"
        elif requested in {"bwrap", "bubblewrap"}:
            requested = "bwrap"
        elif requested not in (None, ""):
            raise SandboxUnavailableError(f"unsupported sandbox backend {requested!r}")
        if requested is None:
            requested = "sandbox-exec" if platform.system() == "Darwin" else "bwrap" if platform.system() == "Linux" else ""
        return requested

    def profile_text(self, workspace: Path) -> str:
        """Generate the macOS Seatbelt profile for a writable workspace."""
        backend = self._selected_backend()
        if backend != "sandbox-exec":
            raise SandboxUnavailableError("Seatbelt profile requested for a non-macOS backend")
        root = Path(self.runtime_root or get_env_value("VIBE_TRADING_HOME", str(Path.home() / ".vibe-trading"))).expanduser().resolve()
        lines = [
            "(version 1)",
            "(deny default)",
            "(allow process-exec)",
            "(allow process-fork)",
            "(allow signal)",
            "(allow sysctl-read)",
            # Seatbelt's runtime needs the interpreter, dynamic libraries,
            # locale files and device metadata.  The whole filesystem is
            # readable, while writes remain limited and credential paths are
            # denied below.
            '(allow file-read* (subpath "/"))',
            f'(allow file-read* (subpath "{Path(workspace).resolve()}"))',
            f'(allow file-write* (subpath "{Path(workspace).resolve()}"))',
            '(allow file-write* (subpath "/tmp"))',
        ]
        if self.network:
            lines.append("(allow network*)")
        for protected in enumerate_protected_runtime_paths(root):
            lines.append(f'(deny file-read* (subpath "{protected}"))')
        return "\n".join(lines) + "\n"

    def command_argv(self, command: str, workspace: Path) -> tuple[list[str], Path | None]:
        """Return a shell argv and a temporary profile to remove after spawn."""
        backend = self.resolved_backend()
        workspace = Path(workspace).expanduser().resolve()
        if backend == "sandbox-exec":
            root = Path(self.runtime_root or get_env_value("VIBE_TRADING_HOME", str(Path.home() / ".vibe-trading"))).expanduser()
            root.mkdir(parents=True, exist_ok=True)
            handle = tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", prefix=".sandbox-", suffix=".sb", dir=root, delete=False
            )
            profile = Path(handle.name)
            with handle:
                handle.write(self.profile_text(workspace))
            return ["sandbox-exec", "-f", str(profile), "/bin/sh", "-c", command], profile
        if backend == "bwrap":
            argv = ["bwrap", "--die-with-parent", "--new-session", "--ro-bind", "/", "/"]
            if not self.network:
                argv.append("--unshare-net")
            argv.extend(["--bind", str(workspace), str(workspace)])
            for protected in enumerate_protected_runtime_paths(
                Path(self.runtime_root or get_env_value("VIBE_TRADING_HOME", str(Path.home() / ".vibe-trading")))
            ):
                if protected.exists():
                    argv.extend(["--tmpfs", str(protected)])
            argv.extend(["--chdir", str(workspace), "/bin/sh", "-c", command])
            return argv, None
        raise SandboxUnavailableError(f"unsupported sandbox backend {backend!r}")


def sandbox_command(command: str, workspace: Path, settings: SandboxSettings | None = None) -> tuple[list[str], Path | None]:
    """Build an enabled sandbox command, refusing unsupported hosts."""
    return (settings or SandboxSettings.from_env()).command_argv(command, workspace)


__all__ = [
    "SandboxSettings", "SandboxUnavailableError", "enumerate_protected_runtime_paths", "sandbox_command",
]
