"""Local HTTP keep-alive race control; synthetic heartbeats, never market data.

Compares equal server/client expiry with earlier client expiry over 1600 SSE
connections each. The 40ms timeout accelerates the production 5s race window.
"""

import asyncio
import json
import sys
import time
import random
from collections import Counter
import httpx

if "--server" in sys.argv:
    import uvicorn
    from fastapi import FastAPI
    from fastapi.responses import StreamingResponse

    app = FastAPI()

    @app.get("/warm")
    async def warm():
        return {"ok": True}

    @app.get("/stream")
    async def stream():
        async def values():
            yield "retry: 3000\n\n"
            await asyncio.sleep(0.1)
            yield ": heartbeat\n\n"

        return StreamingResponse(values(), media_type="text/event-stream")

    uvicorn.run(app, host="127.0.0.1", port=8914, timeout_keep_alive=0.04, log_level="error")
else:
    import subprocess

    child = subprocess.Popen([sys.executable, __file__, "--server"])

    async def run(expiry):
        errors = []
        counts = Counter()
        start = time.monotonic()

        async def worker():
            async with httpx.AsyncClient(
                limits=httpx.Limits(max_keepalive_connections=1, keepalive_expiry=expiry)
            ) as c:
                for i in range(200):
                    try:
                        await c.get("http://127.0.0.1:8914/warm")
                        await asyncio.sleep(random.uniform(0.038, 0.042))
                        async with c.stream("GET", "http://127.0.0.1:8914/stream") as response:
                            async for line in response.aiter_lines():
                                if line:
                                    break
                        counts["ok"] += 1
                    except Exception as exc:
                        counts[type(exc).__name__] += 1
                        if len(errors) < 5:
                            errors.append(repr(exc))

        await asyncio.gather(*(worker() for _ in range(8)))
        return {"expiry": expiry, "counts": dict(counts), "errors": errors, "seconds": time.monotonic() - start}

    try:
        time.sleep(1)
        out = [asyncio.run(run(0.04)), asyncio.run(run(0.01))]
        print(json.dumps(out), flush=True)
        open("/tmp/gateway-keepalive-race.json", "w").write(json.dumps(out, indent=2))
    finally:
        child.terminate()
        child.wait()
