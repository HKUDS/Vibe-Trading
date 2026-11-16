"""Short-lived heavy SDK calls; native allocator high-water marks die with workers."""

import ctypes
import json
import os
import subprocess
import sys
import threading

_slot = threading.BoundedSemaphore(1)
_lock = threading.Lock()
_pid = None
_peak_child_bytes = 0


class _Usage(ctypes.Structure):
    _fields_ = [("uuid", ctypes.c_uint8 * 16), ("values", ctypes.c_uint64 * 35)]


_libproc = ctypes.CDLL("/usr/lib/libproc.dylib", use_errno=True) if sys.platform == "darwin" else None


def footprint(pid):
    """Read macOS physical footprint, including compressed resident pages."""
    if _libproc is None or pid is None:
        return {}
    usage = _Usage()
    if _libproc.proc_pid_rusage(pid, 4, ctypes.byref(usage)) != 0:
        return {}
    return {"footprint_bytes": usage.values[7], "peak_footprint_bytes": usage.values[28], "rss_bytes": usage.values[6]}


def status():
    """Expose the child for whole-process-tree memory accounting."""
    with _lock:
        return {
            "pid": _pid,
            "max_workers": 1,
            "lifetime": "one source request",
            "max_completed_child_footprint_bytes": _peak_child_bytes,
            **footprint(_pid),
        }


def requires_isolation(loader):
    """Include adapters inheriting the heavy SDK, notably the Binance route."""
    module = sys.modules.get("backtest.loaders.ccxt_loader")
    base = getattr(module, "DataLoader", None)
    return isinstance(loader, type) and isinstance(base, type) and issubclass(loader, base)


def fetch(params, timeout, limit):
    """Run one CCXT-backed acquisition with the original source identity and deadline.

    Args:
        params: Normalized market-data arguments for one symbol.
        timeout: Remaining wall-clock seconds, including interpreter startup.
        limit: Maximum encoded response bytes (the existing entry budget).

    Returns:
        The unmodified market-data envelope, including provenance.
    """
    from .service import GatewayBusy, GatewayError

    global _pid, _peak_child_bytes
    if not _slot.acquire(blocking=False):
        raise GatewayBusy("Heavy SDK worker occupied")
    child = None
    try:
        child = subprocess.Popen(
            [sys.executable, "-m", "src.data_gateway.isolated", str(limit)],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            env=dict(os.environ),
        )
        with _lock:
            _pid = child.pid
        try:
            output, _ = child.communicate(json.dumps(params, allow_nan=False).encode(), timeout=max(0.01, timeout))
        except subprocess.TimeoutExpired:
            with _lock:
                _peak_child_bytes = max(_peak_child_bytes, footprint(child.pid).get("peak_footprint_bytes", 0))
            child.kill()
            child.communicate()
            raise TimeoutError("Heavy SDK request deadline reached") from None
        if child.returncode or len(output) > limit + 1024:
            raise GatewayError("Heavy SDK returned no bounded response")
        value = json.loads(output)
        if value.get("_worker_error"):
            raise GatewayError("Heavy SDK acquisition failed")
        with _lock:
            _peak_child_bytes = max(_peak_child_bytes, value.get("memory", {}).get("peak_footprint_bytes", 0))
        return value["payload"]
    finally:
        if child is not None and child.poll() is None:
            child.kill()
            child.wait()
        with _lock:
            _pid = None
        _slot.release()


def main():
    """Child-only entry; no SDK object or allocator arena survives this call."""
    from contextlib import redirect_stdout

    params = json.loads(sys.stdin.buffer.read(65536))
    limit = int(sys.argv[1])
    try:
        with redirect_stdout(sys.stderr):
            from backtest.loaders import registry
            from src.market_data import fetch_market_data_json

            registry._ensure_registered()

            def resolve(name):
                loader = registry.LOADER_REGISTRY.get(name)
                if name != params["source"] or not requires_isolation(loader):
                    raise ValueError("Unexpected isolated source")
                return loader

            value = fetch_market_data_json(**params, loader_resolver=resolve)
        encoded = value.encode()
        if len(encoded) > limit:
            raise ValueError("Response exceeds entry budget")
    except Exception:
        encoded = b'{"_worker_error":true}'
    if encoded != b'{"_worker_error":true}':
        encoded = json.dumps(
            {"payload": json.loads(encoded), "memory": footprint(os.getpid())}, separators=(",", ":")
        ).encode()
    sys.stdout.buffer.write(encoded)


if __name__ == "__main__":
    main()
