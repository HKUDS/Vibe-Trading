"""Run one command under a Landlock ruleset (Linux >= 5.13, no privilege needed).

Usage: ``python -I landlock_exec.py <spec-json> <argv...>``. The freshly started, single-threaded
interpreter restricts itself and then execs ``argv``, so the restriction holds for the command
and everything it starts. It is never applied from a ``preexec_fn``, which is unsafe in the
multi-threaded server (see ``src/core/runner.py``). Run with ``-I`` so a file in the command's
working directory cannot shadow a module imported here. Only the standard library is used.

The spec, built by ``src.tools.sandbox``, lists what may be touched; everything else is refused:

* ``read``: paths granted read and execute (a directory's whole tree).
* ``read_dir``: directories whose tree may be listed but not read (the ancestors of a hidden path).
* ``write``: directories granted every filesystem right.
* ``dev``: paths whose existing files may also be written (``/dev`` for ``/dev/null``).
* ``net``: false refuses every TCP bind and connect, which needs Landlock ABI 4 (Linux 6.7).
* ``env``: variables set for the command (``TMPDIR`` when /tmp could not be granted).

Any failure exits 125 before the exec, so a command never starts unconfined.
"""

import ctypes
import json
import os
import sys

# Same numbers on every architecture that has Landlock (they were added after the syscall tables
# were unified).
_CREATE_RULESET, _ADD_RULE, _RESTRICT_SELF = 444, 445, 446
_CREATE_RULESET_VERSION = 1
_RULE_PATH_BENEATH = 1
_PR_SET_NO_NEW_PRIVS = 38

EXECUTE, WRITE_FILE, READ_FILE, READ_DIR = 1 << 0, 1 << 1, 1 << 2, 1 << 3
REFER, TRUNCATE, IOCTL_DEV = 1 << 13, 1 << 14, 1 << 15
_NET_BIND_TCP, _NET_CONNECT_TCP = 1 << 0, 1 << 1
#: Rights Landlock accepts on a path that is not a directory.
_FILE_RIGHTS = EXECUTE | WRITE_FILE | READ_FILE | TRUNCATE | IOCTL_DEV
EXIT_REFUSED = 125


class _RulesetAttr(ctypes.Structure):
    _fields_ = [("handled_access_fs", ctypes.c_uint64), ("handled_access_net", ctypes.c_uint64)]


class _PathBeneath(ctypes.Structure):
    _pack_ = 1
    _fields_ = [("allowed_access", ctypes.c_uint64), ("parent_fd", ctypes.c_int32)]


def _fail(message):
    """Report why the command was refused and exit before it starts."""
    sys.stderr.write(f"landlock sandbox: {message}\n")
    sys.exit(EXIT_REFUSED)


def _fs_rights(abi):
    """Every filesystem right this kernel's Landlock ABI can restrict."""
    rights = (1 << 13) - 1
    if abi >= 2:
        rights |= REFER
    if abi >= 3:
        rights |= TRUNCATE
    if abi >= 5:
        rights |= IOCTL_DEV
    return rights


def _add(libc, ruleset, path, access, *, required):
    """Grant ``access`` beneath ``path``; a failed optional read grant only leaves it refused."""
    try:
        fd = os.open(path, os.O_PATH | os.O_CLOEXEC)
    except OSError as exc:
        if required:
            _fail(f"cannot open {path}: {exc}")
        return
    try:
        if not os.path.isdir(f"/proc/self/fd/{fd}"):
            access &= _FILE_RIGHTS
        rule = _PathBeneath(access, fd)
        if libc.syscall(_ADD_RULE, ruleset, _RULE_PATH_BENEATH, ctypes.byref(rule), 0) != 0 and required:
            _fail(f"cannot grant {path}: errno {ctypes.get_errno()}")
    finally:
        os.close(fd)


def main(argv):
    """Restrict this process as the spec says, then exec the command.

    Args:
        argv: ``[spec_json, program, *args]``.
    """
    if len(argv) < 2:
        _fail("usage: landlock_exec.py <spec-json> <argv...>")
    if not sys.platform.startswith("linux"):
        # The syscall numbers below mean something else on other kernels.
        _fail("Landlock is Linux-only")
    spec, command = json.loads(argv[0]), argv[1:]
    libc = ctypes.CDLL(None, use_errno=True)
    abi = libc.syscall(_CREATE_RULESET, None, 0, _CREATE_RULESET_VERSION)
    if abi < 1:
        _fail(f"Landlock is not available on this kernel (errno {ctypes.get_errno()})")
    if not spec.get("net") and abi < 4:
        _fail(f"Landlock ABI {abi} cannot refuse TCP connections (needs Linux 6.7); "
              "allow the network or use bwrap")
    rights = _fs_rights(abi)
    attr = _RulesetAttr(rights, 0 if spec.get("net") else _NET_BIND_TCP | _NET_CONNECT_TCP)
    size = ctypes.sizeof(_RulesetAttr) if abi >= 4 else ctypes.sizeof(ctypes.c_uint64)
    ruleset = libc.syscall(_CREATE_RULESET, ctypes.byref(attr), size, 0)
    if ruleset < 0:
        _fail(f"cannot create a ruleset: errno {ctypes.get_errno()}")
    for path in spec.get("read", ()):
        _add(libc, ruleset, path, EXECUTE | READ_FILE | READ_DIR, required=False)
    for path in spec.get("read_dir", ()):
        _add(libc, ruleset, path, READ_DIR, required=False)
    for path in spec.get("dev", ()):
        _add(libc, ruleset, path, (EXECUTE | READ_FILE | READ_DIR | WRITE_FILE | TRUNCATE | IOCTL_DEV) & rights,
             required=False)
    for path in spec.get("write", ()):
        _add(libc, ruleset, path, rights, required=True)
    if libc.prctl(_PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) != 0:
        _fail(f"cannot set no_new_privs: errno {ctypes.get_errno()}")
    if libc.syscall(_RESTRICT_SELF, ruleset, 0) != 0:
        _fail(f"cannot restrict this process: errno {ctypes.get_errno()}")
    os.close(ruleset)
    os.environ.update(spec.get("env", {}))
    try:
        os.execvp(command[0], command)
    except OSError as exc:
        _fail(f"cannot start {command[0]}: {exc}")


if __name__ == "__main__":
    main(sys.argv[1:])
