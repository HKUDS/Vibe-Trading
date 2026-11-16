"""Data gateway CLI: python -m src.data_gateway options AAPL / status / bars ..."""

import argparse
import json
from . import get_gateway


def add_history_parser(commands):
    """Register shared history arguments for both standalone and application CLI."""
    history = commands.add_parser("history", help="Manage quota-bounded historical datasets")
    history.add_argument(
        "action",
        choices=["plan", "create", "run", "status", "rows", "cancel", "delete", "pin", "unpin", "storage", "prune"],
    )
    history.add_argument("--job")
    history.add_argument("--codes", nargs="+")
    history.add_argument("--start")
    history.add_argument("--end")
    history.add_argument("--interval", default="5m")
    history.add_argument("--source", default="auto")
    history.add_argument("--offset", type=int, default=0)
    history.add_argument("--limit", type=int, default=100)
    history.add_argument("--quota-mb", type=int)
    history.add_argument("--retention-days", type=int)
    return history


def run_history(args):
    """Execute a parsed history command and release its local worker resources."""
    from .history_store import HistoryStore, history_directory

    store = HistoryStore(history_directory())
    try:
        if args.action in {"plan", "create"}:
            result = getattr(store, args.action)(
                codes=args.codes, start_date=args.start, end_date=args.end, interval=args.interval, source=args.source
            )
            result.pop("parts", None)
        elif args.action == "run":
            import time

            result = store.start(args.job)
            while result["state"] in {"running", "queued", "waiting"} or result.get("retry_at", 0):
                time.sleep(0.25)
                result = store.status(args.job)
        elif args.action == "storage":
            result = store.settings(
                quota_bytes=args.quota_mb * 1024**2 if args.quota_mb is not None else None,
                retention_days=args.retention_days,
            )
        elif args.action == "prune":
            result = store.prune()
        elif args.action == "status":
            result = store.status(args.job)
        elif args.action == "rows":
            result = store.read(args.job, args.offset, args.limit)
        elif args.action in {"pin", "unpin"}:
            result = store.pin(args.job, args.action == "pin")
        else:
            result = getattr(store, args.action)(args.job)
        print(json.dumps(result, ensure_ascii=False, allow_nan=False))
        if args.action == "run" and result.get("state") not in {"complete", "downloaded"}:
            raise SystemExit(1)
    except KeyboardInterrupt:
        if args.action == "run":
            store.cancel(args.job)
        raise
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": str(exc)}))
        raise SystemExit(1) from None
    finally:
        store.close()


def add_scan_parser(commands):
    """Register a bounded scan command shared with the application CLI."""
    parser = commands.add_parser("scan", help="Queue and await a background bar acquisition scan")
    parser.add_argument("codes", nargs="+")
    parser.add_argument("--start", required=True)
    parser.add_argument("--end", required=True)
    parser.add_argument("--interval", default="1D")


def run_scan(args):
    """Run a process-local scan until completion, printing progress as JSON."""
    import time

    gateway = get_gateway()
    queue = gateway.scan_queue()
    try:
        job = queue.create(args.codes, start_date=args.start, end_date=args.end, interval=args.interval)
        while True:
            print(json.dumps(job), flush=True)
            if job["state"] in {"complete", "partial", "cancelled"}:
                return 0 if job["complete"] else 1
            time.sleep(1)
            job = queue.status(job["id"])
    finally:
        gateway.close()


def main(argv=None):
    """Expose the same gateway used by HTTP and agent tools."""
    parser = argparse.ArgumentParser(description="Unified local data gateway")
    commands = parser.add_subparsers(dest="command", required=True)
    options = commands.add_parser("options")
    options.add_argument("ticker")
    options.add_argument("--expiration", type=int)
    options.add_argument("--full", action="store_true", help="All standard contracts at the selected expiration")
    watch = commands.add_parser("watch")
    watch.add_argument("topics", nargs="+", help="options:AAPL[:expiration], crypto:BTC-USDT or bars:AAPL.US:1D")
    watch.add_argument("--events", type=int, default=10, help="Stop after this many updates (1..10000)")
    commands.add_parser("capabilities")
    commands.add_parser("status")
    commands.add_parser("prune")
    bars = commands.add_parser("bars")
    bars.add_argument("codes", nargs="+")
    bars.add_argument("--start", required=True)
    bars.add_argument("--end", required=True)
    add_history_parser(commands)
    add_scan_parser(commands)
    args = parser.parse_args(argv)
    if args.command == "scan":
        raise SystemExit(run_scan(args))
    if args.command == "history":
        return run_history(args)
    gateway = get_gateway()
    if args.command == "watch":
        import asyncio
        from .streams import StreamHub, Topic

        async def watch_events():
            hub = StreamHub(gateway)
            try:
                if not 1 <= args.events <= 10000:
                    raise ValueError("--events must be between 1 and 10000")
                listener = hub.subscribe([Topic.parse(t) for t in args.topics])
                count = 0
                while count < args.events:
                    for event in await listener.take():
                        print(json.dumps(event, ensure_ascii=False, allow_nan=False), flush=True)
                        count += 1
                        if count >= args.events:
                            break
                    await asyncio.sleep(gateway.config.stream_interval)
            finally:
                await hub.close()
                gateway.close()

        try:
            asyncio.run(watch_events())
        except KeyboardInterrupt:
            pass
        return
    if args.command == "options":
        result = gateway.options_chain(args.ticker, args.expiration, full=args.full)
    elif args.command == "capabilities":
        from .catalog import capabilities

        result = capabilities(gateway.config)
    elif args.command == "bars":
        result = gateway.bars(
            codes=args.codes, start_date=args.start, end_date=args.end, include_provenance=True, max_rows=100
        )
    else:
        if args.command == "prune":
            gateway.cache.prune()
        result = gateway.status()
    print(json.dumps(result, ensure_ascii=False, allow_nan=False))
    gateway.close()
    raise SystemExit(0 if result.get("ok") else 1)


if __name__ == "__main__":
    main()
