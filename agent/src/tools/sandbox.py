"""Optional OS-level sandboxing for shell tools.

The sandbox is opt-in.  When enabled, an unsupported platform or missing
backend fails closed before a command is started.

Backends: Seatbelt (``sandbox-exec``) on macOS; on Linux bubblewrap (``bwrap``), and Landlock
when bwrap cannot run. A container usually cannot give bwrap its namespaces (Docker's default
seccomp profile refuses them), while Landlock needs no privilege at all: the command starts
through ``landlock_exec.py``, which restricts itself and then execs it.
"""

from __future__ import annotations

import ast
import functools
import logging
import platform
import re
import json
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

from src.config.env_schema import APIConfig


logger = logging.getLogger(__name__)

#: Reasons already warned about, so an unconfined swarm fallback is logged once per process.
_WARNED_UNAVAILABLE: set[str] = set()
_PROBE_TIMEOUT_SECONDS = 10
#: The shared temporary directory every backend leaves writable (Seatbelt matches it resolved:
#: /tmp is a symlink to /private/tmp on macOS).
SHARED_TMP = Path("/tmp")


class SandboxUnavailableError(RuntimeError):
    """Raised when an enabled sandbox cannot be provided by this host."""


@functools.lru_cache(maxsize=None)
def _probe_backend(backend: str, network: bool) -> str | None:
    """Start a trivial command inside the backend once per process.

    Args:
        backend: ``sandbox-exec`` or ``bwrap``.
        network: Whether commands keep the network; without it bwrap must also unshare it.

    Returns:
        None when the backend confines a command on this host, else why it cannot.
    """
    if shutil.which(backend) is None:
        return f"{backend} is not installed"
    if backend == "sandbox-exec":
        argv = ["sandbox-exec", "-p", "(version 1)(allow default)", "/bin/sh", "-c", ":"]
    else:
        argv = ["bwrap", "--die-with-parent", "--new-session", "--ro-bind", "/", "/",
                *([] if network else ["--unshare-net"]), "/bin/sh", "-c", ":"]
    try:
        probe = subprocess.run(argv, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SECONDS)
    except (OSError, subprocess.SubprocessError) as exc:
        return f"{backend} could not be started: {exc}"
    if probe.returncode != 0:
        detail = (probe.stderr or "").strip()[:200]
        return f"{backend} cannot create a sandbox on this host (exit {probe.returncode}): {detail}"
    return None


#: Started as ``python -I`` so the command's directory cannot shadow its imports.
LANDLOCK_EXEC = Path(__file__).with_name("landlock_exec.py")


def landlock_command(argv: list[str], spec: dict) -> list[str]:
    """Wrap ``argv`` so it starts under the Landlock ruleset ``spec`` describes.

    Args:
        argv: The command to confine.
        spec: A spec from :func:`build_landlock_spec`.

    Returns:
        The argv that applies the ruleset and then execs ``argv``.
    """
    return [sys.executable, "-I", str(LANDLOCK_EXEC), json.dumps(spec), *argv]


@functools.lru_cache(maxsize=None)
def _probe_landlock(network: bool) -> str | None:
    """Start a trivial command under Landlock once per process.

    Args:
        network: Whether commands keep the network; without it the kernel must refuse TCP too.

    Returns:
        None when Landlock confines a command on this host, else why it cannot.
    """
    if platform.system() != "Linux":
        return "Landlock is Linux-only"
    with tempfile.TemporaryDirectory(prefix="vibe-landlock-probe-") as scratch:
        argv = landlock_command(["/bin/sh", "-c", ":"], {"write": [scratch], "read": ["/"], "net": network})
        try:
            probe = subprocess.run(argv, capture_output=True, text=True, timeout=_PROBE_TIMEOUT_SECONDS)
        except (OSError, subprocess.SubprocessError) as exc:
            return f"landlock could not be started: {exc}"
    if probe.returncode != 0:
        return (probe.stderr or "").strip()[:200] or f"landlock probe failed (exit {probe.returncode})"
    return None


def landlock_available(network: bool) -> str | None:
    """Why Landlock cannot confine a command on this host, or None when it can.

    Args:
        network: Whether the command keeps the network.

    Returns:
        None when available, else the reason (probed once per process).
    """
    return _probe_landlock(network)


def _related(path: Path, others: set[Path]) -> bool:
    """Whether ``path`` is one of ``others``, inside one, or above one."""
    return any(path == other or path.is_relative_to(other) or other.is_relative_to(path) for other in others)


def landlock_grants(hidden: set[Path], top: Path = Path("/")) -> tuple[list[str], list[str]]:
    """Split the filesystem into what a Landlock command may read and what it may only list.

    Landlock can only grant, so "everything but the hidden paths" is granted as every sibling
    along the way down to each hidden path. The directories on that way may be listed (their
    tree's names, hidden ones included) but not read. A symlink is granted only when its target
    has nothing to do with a hidden path, because a grant follows it.

    Args:
        hidden: Resolved absolute paths whose contents must stay unreadable.
        top: Where the walk starts.

    Returns:
        ``(read, read_dir)`` path lists for the spec.
    """
    read: list[str] = []
    listed: list[str] = [str(top)]
    pending = [top]
    while pending:
        folder = pending.pop()
        try:
            entries = sorted(folder.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry in hidden:
                continue
            if entry.is_symlink():
                try:
                    target = entry.resolve()
                except OSError:
                    continue
                if not _related(target, hidden):
                    read.append(str(entry))
            elif any(other.is_relative_to(entry) for other in hidden):
                listed.append(str(entry))
                pending.append(entry)
            else:
                read.append(str(entry))
    return read, listed


def enumerate_protected_runtime_paths(runtime_root: Path) -> tuple[Path, ...]:
    """Find broker/auth runtime paths from the source's path declarations.

    Root-level JSON config files and credential directories are hidden inside a
    shell sandbox.  The directory names are discovered from ``get_runtime_root``
    path expressions and connector ``CONFIG_FILENAME`` declarations so adding a
    connector does not require a second security list.

    Args:
        runtime_root: The runtime root (``get_runtime_root()``).

    Returns:
        The credential paths under it, sorted, whether or not they exist yet.
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


def build_landlock_spec(*, hidden: set[Path], writable: list[Path], network: bool, private_tmp: Path,
                        readable: tuple[Path, ...] = ()) -> dict:
    """Describe a Landlock ruleset: read all but ``hidden``, write ``writable`` and the temp dirs.

    Landlock can only grant, so when a hidden path lies inside /tmp (a runtime root there), /tmp
    is not granted and TMPDIR moves to ``private_tmp`` instead; a /tmp grant would cover it.

    Args:
        hidden: Resolved paths whose contents stay unreadable.
        writable: Directories granted every filesystem right.
        network: Whether TCP stays open.
        private_tmp: The TMPDIR used when /tmp cannot be granted; created then.
        readable: Paths inside ``hidden`` that are readable after all.

    Returns:
        The spec ``landlock_exec.py`` reads.
    """
    read, read_dir = landlock_grants(hidden)
    read += [str(path) for path in readable if path.exists()]
    tmp = SHARED_TMP.resolve()
    env: dict[str, str] = {}
    granted = [str(Path(path).resolve()) for path in writable]
    if _related(tmp, hidden):
        Path(private_tmp).mkdir(parents=True, exist_ok=True)
        env["TMPDIR"] = str(private_tmp)
        granted.append(str(Path(private_tmp).resolve()))
    else:
        granted.append(str(tmp))
    granted += [path for path in ("/dev/shm",) if Path(path).is_dir()]
    return {"read": read, "read_dir": read_dir, "write": list(dict.fromkeys(granted)), "dev": ["/dev"],
            "net": network, "env": env}


@dataclass(frozen=True)
class SandboxSettings:
    """Resolved shell sandbox settings.

    ``workspace`` is set only for a swarm node: its commands always run there, and inside a
    sandbox it is the one writable directory besides /tmp. ``unavailable`` records why no
    backend works for such a node.
    """

    runtime_root: Path
    enabled: bool = False
    network: bool = False
    backend: str | None = None
    swarm_mode: str = "off"
    workspace: Path | None = None
    unavailable: str | None = None

    @classmethod
    def from_config(cls, config: APIConfig, *, runtime_root: Path) -> "SandboxSettings":
        """Resolve settings from the supplied host configuration.

        Args:
            config: Host API settings carrying the sandbox switches.
            runtime_root: The runtime root (``get_runtime_root()``) whose credentials are hidden.

        Returns:
            Settings for the main agent's shell; swarm nodes derive theirs with :meth:`for_workspace`.
        """
        backend = config.vibe_trading_sandbox_backend.strip().lower() or None
        return cls(
            enabled=config.vibe_trading_sandbox_enabled,
            network=config.vibe_trading_sandbox_network,
            backend=backend,
            runtime_root=runtime_root,
            swarm_mode=config.vibe_trading_swarm_shell_sandbox,
        )

    def for_workspace(self, workspace: Path) -> "SandboxSettings":
        """Derive the settings for one swarm node's shell commands.

        ``off`` keeps these settings. ``auto`` confines commands to the workspace when a backend
        works on this host and otherwise runs them there unconfined, warning once per process;
        ``required`` refuses instead. When the main sandbox is enabled, ``auto`` refuses too, so a
        node is never less confined than the main agent.

        Args:
            workspace: The node's task workspace.

        Returns:
            Settings pinned to the resolved workspace.
        """
        if self.swarm_mode == "off":
            return self
        pinned = Path(workspace).expanduser().resolve()
        try:
            candidates = self._candidate_backends()
        except SandboxUnavailableError as exc:
            candidates, reasons = [], [str(exc)]
        else:
            reasons = [] if candidates else ["no sandbox backend exists for this platform"]
        for backend in candidates:
            reason = self._probe(backend)
            if reason is None:
                return replace(self, enabled=True, backend=backend, workspace=pinned)
            reasons.append(reason)
        reason = "; ".join(reasons)
        if self.swarm_mode == "required" or self.enabled:
            return replace(self, enabled=True, workspace=pinned, unavailable=reason)
        if reason not in _WARNED_UNAVAILABLE:
            _WARNED_UNAVAILABLE.add(reason)
            logger.warning(
                "Swarm node shell commands run unconfined in their workspace: %s. "
                "Set VIBE_TRADING_SWARM_SHELL_SANDBOX=required to refuse them instead.", reason,
            )
        return replace(self, enabled=False, workspace=pinned, unavailable=reason)

    def _candidate_backends(self) -> list[str]:
        """The backends to try in order: the selected one, then Landlock on Linux unless one was named.

        Raises:
            SandboxUnavailableError: An unsupported backend was named.
        """
        selected = self._selected_backend()
        if selected == "bwrap" and self.backend is None:
            return ["bwrap", "landlock"]
        return [selected] if selected else []

    def _probe(self, backend: str) -> str | None:
        """Why ``backend`` cannot confine a command here, or None when it can."""
        if backend == "landlock":
            return _probe_landlock(self.network)
        return _probe_backend(backend, self.network)

    @property
    def unconfined_fallback(self) -> bool:
        """Whether a swarm node's commands run without the sandbox it asked for.

        Returns:
            True for ``auto`` on a host where no backend works.
        """
        return not self.enabled and self.unavailable is not None

    def resolved_backend(self) -> str:
        """Return the supported backend name or raise when unavailable.

        Returns:
            ``disabled`` when the sandbox is off, else ``sandbox-exec``, ``bwrap`` or ``landlock``
            (on Linux when bwrap cannot run and no backend was named).

        Raises:
            SandboxUnavailableError: The sandbox is required but this host cannot provide it.
        """
        if not self.enabled:
            return "disabled"
        if self.unavailable is not None:
            raise SandboxUnavailableError(f"a swarm node shell sandbox is required but unavailable: {self.unavailable}")
        candidates = self._candidate_backends()
        if "landlock" in candidates:
            reasons = []
            for backend in candidates:
                reason = self._probe(backend)
                if reason is None:
                    return backend
                reasons.append(reason)
            raise SandboxUnavailableError(f"sandbox is enabled but no backend works: {'; '.join(reasons)}")
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
        elif requested == "landlock":
            pass
        elif requested not in (None, ""):
            raise SandboxUnavailableError(f"unsupported sandbox backend {requested!r}")
        if requested is None:
            requested = "sandbox-exec" if platform.system() == "Darwin" else "bwrap" if platform.system() == "Linux" else ""
        return requested

    def profile_text(self, workspace: Path) -> str:
        """Generate the macOS Seatbelt profile for a writable workspace.

        Args:
            workspace: The one writable directory besides /tmp and the standard devices.

        Returns:
            Seatbelt profile text that also denies reads of the runtime root's credentials.

        Raises:
            SandboxUnavailableError: The selected backend is not Seatbelt.
        """
        backend = self._selected_backend()
        if backend != "sandbox-exec":
            raise SandboxUnavailableError("Seatbelt profile requested for a non-macOS backend")
        root = self.runtime_root.expanduser().resolve()
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
            f'(allow file-write* (subpath "{SHARED_TMP.resolve()}"))',
            '(allow file-write* (literal "/dev/null") (literal "/dev/zero") (literal "/dev/dtracehelper")'
            ' (literal "/dev/stdout") (literal "/dev/stderr") (subpath "/dev/fd") (regex #"^/dev/tty"))',
        ]
        if self.network:
            lines.append("(allow network*)")
        for protected in enumerate_protected_runtime_paths(root):
            lines.append(f'(deny file-read* (subpath "{protected}"))')
        return "\n".join(lines) + "\n"

    def command_argv(self, command: str, workspace: Path) -> tuple[list[str], Path | None]:
        """Return a shell argv and a temporary profile to remove after spawn.

        Args:
            command: Shell command to run inside the sandbox.
            workspace: Writable working directory of the command.

        Returns:
            The argv to spawn and the Seatbelt profile file to delete afterwards (None otherwise).

        Raises:
            SandboxUnavailableError: No supported backend is available.
        """
        backend = self.resolved_backend()
        workspace = Path(workspace).expanduser().resolve()
        if backend == "sandbox-exec":
            root = self.runtime_root.expanduser()
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
            # The read-only root covers /dev and /tmp too: a fresh /dev (null, zero, urandom, shm,
            # tty) and the shared /tmp keep what Seatbelt allows writable.
            tmp = str(SHARED_TMP.resolve())
            argv.extend(["--dev", "/dev", "--bind", tmp, tmp, "--bind", str(workspace), str(workspace)])
            for protected in enumerate_protected_runtime_paths(self.runtime_root):
                # --tmpfs needs a directory; a credential file is covered with an empty one.
                if protected.is_dir():
                    argv.extend(["--tmpfs", str(protected)])
                elif protected.exists():
                    argv.extend(["--ro-bind", "/dev/null", str(protected)])
            argv.extend(["--chdir", str(workspace), "/bin/sh", "-c", command])
            return argv, None
        if backend == "landlock":
            return landlock_command(["/bin/sh", "-c", command], self.landlock_spec(workspace)), None
        raise SandboxUnavailableError(f"unsupported sandbox backend {backend!r}")

    def landlock_spec(self, workspace: Path) -> dict:
        """The Landlock ruleset for one command, matching what Seatbelt allows.

        Everything is readable except the runtime root's credential paths; the workspace, /tmp
        and /dev/shm (semaphores) are writable; files under /dev may be written; the network
        follows ``network``. Landlock can only grant, so when a credential path lies inside /tmp
        (a runtime root there), /tmp is not granted and the command's TMPDIR moves into the
        workspace instead.

        Args:
            workspace: The one writable directory besides the temporary ones.

        Returns:
            The spec ``landlock_exec.py`` reads.
        """
        workspace = Path(workspace).resolve()
        hidden = {path.resolve() for path in enumerate_protected_runtime_paths(self.runtime_root)}
        return build_landlock_spec(hidden=hidden, writable=[workspace], network=self.network,
                                   private_tmp=workspace / ".tmp")


def sandbox_command(command: str, workspace: Path, settings: SandboxSettings) -> tuple[list[str], Path | None]:
    """Build an enabled sandbox command, refusing unsupported hosts.

    Args:
        command: Shell command to run.
        workspace: Its writable working directory.
        settings: The resolved sandbox settings.

    Returns:
        The argv to spawn and the Seatbelt profile to delete afterwards (None otherwise).

    Raises:
        SandboxUnavailableError: No supported backend is available.
    """
    return settings.command_argv(command, workspace)


__all__ = [
    "SandboxSettings", "SandboxUnavailableError", "build_landlock_spec", "enumerate_protected_runtime_paths",
    "landlock_command", "landlock_available", "sandbox_command",
]
