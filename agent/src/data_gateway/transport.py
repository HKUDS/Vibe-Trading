"""Bounded TLS configuration reuse across public-stream reconnects."""

import ssl
import threading

_context = None
_lock = threading.Lock()


def tls_context():
    """Share one verified context instead of rebuilding trust stores per reconnect.

    Closed asyncio TLS transports can remain in reference cycles until GC. A
    shared immutable context bounds their native certificate-store cost without
    forcing process-wide GC or disabling certificate/hostname verification.
    """
    global _context
    with _lock:
        if _context is None:
            _context = ssl.create_default_context()
        return _context
