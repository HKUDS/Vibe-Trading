"""Private worker pipes coexist with an open, blocked MCP-like stdin."""

import queue
import subprocess
import sys
import threading


def test_worker_starts_while_host_stdin_is_blocked_and_prints_do_not_corrupt_ipc():
    driver = r'''
import sys, threading
from src.tools.paper_trade.strategy_process import start_strategy_process
blocked = threading.Thread(target=lambda: sys.stdin.buffer.read(1), daemon=True)
blocked.start()
payload = {
    "source": "print('strategy output')\nclass SignalEngine:\n    def generate_signals(self, ctx, trade_date): return []\n",
    "filename": "synthetic.py", "days": (), "symbols": (),
}
process, connection = start_strategy_process(payload)
try:
    assert connection.poll(20), 'no worker startup'
    assert connection.recv() == ('ready',)
    assert connection.poll(5)
    assert connection.recv() == ('done',)
    process.wait(timeout=5)
finally:
    if process.poll() is None:
        process.kill()
        process.wait(timeout=5)
    connection.close()
assert not connection.thread.is_alive(), 'IPC reader leaked'
print('private-ipc-ok', flush=True)
blocked.join(timeout=20)
assert not blocked.is_alive()
'''
    bootstrap = f"import sys; sys.path[:] = {sys.path!r}; exec({driver!r})"
    host = subprocess.Popen([sys.executable, "-B", "-u", "-c", bootstrap],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    received = queue.Queue()
    reader = threading.Thread(target=lambda: received.put(host.stdout.readline()), daemon=True)
    reader.start()
    try:
        line = received.get(timeout=30)
        _, stderr = host.communicate(input=b"x", timeout=10)
        assert line in {b"private-ipc-ok\n", b"private-ipc-ok\r\n"}, stderr.decode(errors="replace")
        assert host.returncode == 0, stderr.decode(errors="replace")
    finally:
        if host.poll() is None:
            host.kill()
        host.communicate(timeout=5)
        reader.join(timeout=1)
