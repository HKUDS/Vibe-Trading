"""Cooperative market acquisition on the gateway's existing bounded source pool."""

from concurrent.futures import wait, FIRST_COMPLETED
from dataclasses import dataclass
import time
from typing import Callable

from .service import GatewayBusy


@dataclass(frozen=True)
class SourceCall:
    """One source attempt yielded by a market's sequential fallback chain."""

    source: str
    function: Callable
    cost: int


def acquire_groups(gateway, walkers, until, *, parallel):
    """Drive independent routes without new threads or source-slot replacement.

    Args:
        gateway: Owner of the unchanged source pool, pacer and capacity limits.
        walkers: Generators yielding SourceCall and returning a result envelope.
        until: Absolute request deadline, including time already spent queueing.
        parallel: False preserves the serialized background acquisition path.

    Returns:
        Per-market envelopes in input order, including explicit missing data.
    """
    ready, pending, results = {}, {}, {}

    def advance(index, value=None, error=None):
        try:
            ready[index] = walkers[index].throw(error) if error else walkers[index].send(value)
        except StopIteration as ended:
            results[index] = ended.value

    try:
        for index in range(len(walkers)):
            advance(index)
        while ready or pending:
            for future, (index, expires) in list(pending.items()):
                if future.done() or time.monotonic() >= expires:
                    pending.pop(future)
                    try:
                        if not future.done():
                            future.cancel()
                            raise TimeoutError("Source attempt deadline reached")
                        value = future.result()
                    except Exception as exc:
                        advance(index, error=exc)
                    else:
                        advance(index, value)
            for index, call in list(ready.items()):
                remaining = until - time.monotonic()
                if remaining <= 0:
                    ready.pop(index)
                    advance(index, error=GatewayBusy("Request deadline reached waiting for source capacity"))
                    continue
                timeout = min(remaining, gateway.config.source_timeout)
                if not parallel:
                    # A scan cannot monopolize the background coordinator for
                    # its entire multi-source batch. Yield at a source boundary;
                    # the original request clock keeps running while suspended.
                    gateway.coordinators.cooperate()
                    remaining = until - time.monotonic()
                    if remaining <= 0:
                        continue
                    timeout = min(remaining, gateway.config.source_timeout)
                try:
                    future = gateway.submit_source(
                        call.function,
                        {},
                        timeout,
                        admit=lambda call=call: gateway.pacer.try_acquire(call.source, call.cost),
                        shared_bulk=parallel,
                    )
                except GatewayBusy:
                    continue  # Local capacity/rate wait never poisons source health.
                except Exception as exc:
                    ready.pop(index)
                    advance(index, error=exc)
                else:
                    ready.pop(index)
                    pending[future] = (index, min(until, time.monotonic() + timeout))
            if pending:
                wait(pending, timeout=min(0.02, max(0, until - time.monotonic())), return_when=FIRST_COMPLETED)
            elif ready:
                time.sleep(min(0.02, max(0, until - time.monotonic())))
        return [results[index] for index in range(len(walkers))]
    finally:
        for future in pending:
            future.cancel()  # Running calls keep their slots until actual completion.
        for walker in walkers:
            walker.close()
