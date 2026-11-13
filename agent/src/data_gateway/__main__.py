"""Read-only CLI: python -m src.data_gateway options AAPL / status / bars ..."""

import argparse
import json
from . import get_gateway


def main():
    """Expose the same gateway used by HTTP and agent tools."""
    parser = argparse.ArgumentParser(description="Unified local data gateway")
    commands = parser.add_subparsers(dest="command", required=True)
    options = commands.add_parser("options")
    options.add_argument("ticker")
    options.add_argument("--expiration", type=int)
    options.add_argument("--full", action="store_true", help="All standard contracts at the selected expiration")
    watch = commands.add_parser("watch")
    watch.add_argument("topics", nargs="+", help="options:AAPL[:expiration] or crypto:BTC-USDT")
    watch.add_argument("--events", type=int, default=10, help="Stop after this many updates (1..10000)")
    commands.add_parser("capabilities")
    commands.add_parser("status")
    commands.add_parser("prune")
    bars = commands.add_parser("bars")
    bars.add_argument("codes", nargs="+")
    bars.add_argument("--start", required=True)
    bars.add_argument("--end", required=True)
    args = parser.parse_args()
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
