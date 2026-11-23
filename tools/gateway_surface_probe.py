"""Compare real completed history pages through HTTP, CLI, and the agent tool."""

import argparse
import asyncio
import hashlib
import json
import os
from pathlib import Path
import sys

import httpx


async def run(args):
    environment = dict(os.environ, VIBE_GATEWAY_HISTORY_DIR=str(args.directory))
    agent_code = (
        "import sys; from src.tools.history_data_tool import HistoryDataTool; "
        "print(HistoryDataTool().execute(action='rows', job=sys.argv[1], offset=int(sys.argv[2])))"
    )

    async def command(argv):
        process = await asyncio.create_subprocess_exec(
            sys.executable,
            *argv,
            env=environment,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            stdout, _ = await asyncio.wait_for(process.communicate(), 45)
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
        return process.returncode, json.loads(stdout.decode().strip().splitlines()[-1])

    async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{args.port}", timeout=25) as client:
        http, cli, agent = await asyncio.gather(
            client.get(f"/data/history/jobs/{args.job}/rows", params={"limit": 25, "offset": args.offset}),
            command(
                [
                    "-m",
                    "cli",
                    "data",
                    "history",
                    "rows",
                    "--job",
                    args.job,
                    "--limit",
                    "25",
                    "--offset",
                    str(args.offset),
                ]
            ),
            command(["-c", agent_code, args.job, str(args.offset)]),
        )
        assert http.status_code == 200 and cli[0] == 0 and agent[0] == 0 and agent[1]["ok"]
        values = {"http": http.json(), "cli": cli[1], "agent_tool": agent[1]["data"]}
        results = {}
        for name, value in values.items():
            assert len(value["rows"]) == 25 and not value.get("sampled")
            assert set(value["provenance"]) == {row["symbol"] for row in value["rows"]}
            results[name] = {
                "rows": len(value["rows"]),
                "coverage_verified": value["coverage_verified"],
                "sha256": hashlib.sha256(json.dumps(value["rows"], sort_keys=True).encode()).hexdigest(),
                "provenance": value["provenance"],
                "interval": value["interval"],
            }
        assert len({v["sha256"] for v in results.values()}) == 1
        assert len({json.dumps(v["provenance"], sort_keys=True) for v in results.values()}) == 1
        assert len({v["interval"] for v in results.values()}) == 1
        bad = "not-a-job"
        http_bad, cli_bad, agent_bad = await asyncio.gather(
            client.get(f"/data/history/jobs/{bad}/rows"),
            command(["-m", "cli", "data", "history", "rows", "--job", "../../etc/passwd"]),
            command(["-c", agent_code, "../../etc/passwd", "0"]),
        )
        assert http_bad.status_code == 409 and cli_bad[0] != 0 and not agent_bad[1]["ok"]
        report = {
            "completed": True,
            "offset": args.offset,
            "pages": results,
            "invalid_ids_refused": True,
            "method": "Concurrent real HTTP, application CLI subprocess and agent tool subprocess; same on-disk dataset; no MCP transport claim",
        }
        args.output.write_text(json.dumps(report, indent=2))
        print(json.dumps(report))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, required=True)
    parser.add_argument("--job", required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--directory", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    asyncio.run(run(parser.parse_args()))
