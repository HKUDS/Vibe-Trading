"""Build CHANNELS.md and TESTS.md catalogs."""
from __future__ import annotations

import ast
import re
from collections import defaultdict
from pathlib import Path

ROOT = Path(r"c:\Users\user\Desktop\github\Vibe-Trading")
OUT = ROOT / "docs" / "analysis" / "catalog"
CHANNELS = ROOT / "agent" / "src" / "channels"
TESTS = ROOT / "agent" / "tests"


def channel_info(path: Path) -> dict | None:
    text = path.read_text(encoding="utf-8", errors="replace")
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return None
    name = display = None
    bases = []
    for node in tree.body:
        if isinstance(node, ast.ClassDef) and node.name.endswith("Channel"):
            for b in node.bases:
                if isinstance(b, ast.Name):
                    bases.append(b.id)
            for item in node.body:
                if isinstance(item, ast.Assign):
                    for t in item.targets:
                        if isinstance(t, ast.Name) and t.id in {"name", "display_name"}:
                            if isinstance(item.value, ast.Constant):
                                if t.id == "name":
                                    name = item.value.value
                                else:
                                    display = item.value.value
            break
    # docstring first line
    doc = ast.get_docstring(tree) or ""
    first = (doc.strip().splitlines() or [""])[0][:200]
    # deps hints
    deps = sorted(
        {
            m.group(1)
            for m in re.finditer(r"^(?:import|from)\s+([a-zA-Z0-9_]+)", text, re.M)
            if m.group(1)
            not in {
                "asyncio",
                "base64",
                "json",
                "logging",
                "os",
                "re",
                "sys",
                "time",
                "typing",
                "pathlib",
                "dataclasses",
                "collections",
                "functools",
                "hashlib",
                "hmac",
                "io",
                "tempfile",
                "uuid",
                "datetime",
                "enum",
                "contextlib",
                "inspect",
                "traceback",
                "urllib",
                "http",
                "ssl",
                "struct",
                "html",
                "mimetypes",
                "shutil",
                "subprocess",
                "threading",
                "queue",
                "copy",
                "math",
                "warnings",
                "abc",
                "src",
            }
        }
    )
    has_start = "async def start(" in text
    has_send = "async def send(" in text
    overrides_handle = "def _handle_message" in text or "async def _handle_message" in text
    return {
        "file": path.name,
        "class": next(
            (
                n.name
                for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name.endswith("Channel")
            ),
            "",
        ),
        "name": name or path.stem,
        "display_name": display or "",
        "bases": bases,
        "doc": first,
        "lines": text.count("\n") + 1,
        "has_start": has_start,
        "has_send": has_send,
        "overrides_handle": overrides_handle,
        "third_party_hints": [d for d in deps if d not in {"src", "channels"}][:12],
    }


def write_channels() -> None:
    adapters = []
    skip = {
        "base.py",
        "registry.py",
        "manager.py",
        "runtime.py",
        "config.py",
        "utils.py",
        "__init__.py",
    }
    for path in sorted(CHANNELS.glob("*.py")):
        if path.name in skip:
            continue
        info = channel_info(path)
        if info and info["class"]:
            adapters.append(info)

    lines = [
        "# Channels Adapter Catalog",
        "",
        "Core: `base.py` → `bus/` → `runtime.py` (inbound→SessionService) + `manager.py` (outbound).",
        "",
        f"Adapters analyzed: **{len(adapters)}**.",
        "",
        "| name | display | file | lines | _handle override | libs (hint) | doc |",
        "|------|---------|------|------:|:----------------:|-------------|-----|",
    ]
    for a in adapters:
        libs = ", ".join(f"`{x}`" for x in a["third_party_hints"][:5])
        doc = a["doc"].replace("|", "/")
        lines.append(
            f"| `{a['name']}` | {a['display_name']} | `{a['file']}` | {a['lines']} | "
            f"{'Y' if a['overrides_handle'] else ''} | {libs} | {doc} |"
        )
    lines.extend(
        [
            "",
            "## Per-adapter notes (from code structure)",
            "",
        ]
    )
    notes = {
        "telegram": "python-telegram-bot long polling; media download; pairing via BaseChannel.",
        "discord": "discord.py gateway; thread session_key.",
        "slack": "Socket Mode; emoji react progress.",
        "dingtalk": "dingtalk_stream Stream Mode.",
        "feishu": "lark_oapi WebSocket.",
        "whatsapp": "neonize WhatsApp Web; rich media.",
        "matrix": "matrix-nio sync; workspace restrict kwargs.",
        "email": "IMAP poll + SMTP reply.",
        "signal": "signal-cli REST/JSON-RPC; **overrides _handle_message** (direct publish).",
        "weixin": "personal WeChat HTTP long-poll (ilink).",
        "wecom": "enterprise WeCom aibot SDK.",
        "msteams": "Bot Framework webhook HTTP (DM MVP).",
        "qq": "botpy official QQ bot.",
        "napcat": "OneBot v11 WebSocket.",
        "mochat": "Socket.IO + HTTP polling fallback.",
        "websocket": "Local WS/Unix + channelsui gateway for WebUI.",
    }
    for a in adapters:
        note = notes.get(a["name"], "Standard BaseChannel ingress.")
        lines.append(f"### `{a['name']}`")
        lines.append("")
        lines.append(f"- class: `{a['class']}` ({a['lines']} lines)")
        lines.append(f"- start/send: {'yes' if a['has_start'] else 'no'} / {'yes' if a['has_send'] else 'no'}")
        lines.append(f"- note: {note}")
        lines.append("")

    (OUT / "CHANNELS.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"channels: {len(adapters)}")


def write_tests() -> None:
    files = sorted(TESTS.glob("test_*.py"))
    groups: dict[str, list[str]] = defaultdict(list)
    for f in files:
        stem = f.stem[len("test_") :]
        # group by first token or known prefixes
        prefix = stem.split("_")[0]
        # longer domain prefixes
        for p in (
            "swarm",
            "tushare",
            "alpha",
            "cli",
            "sdk",
            "runner",
            "loader",
            "goal",
            "session",
            "channel",
            "live",
            "mandate",
            "shadow",
            "mcp",
            "backtest",
            "factor",
            "yahoo",
            "okx",
            "futu",
            "trading",
            "security",
            "web",
            "sse",
            "api",
        ):
            if stem.startswith(p):
                prefix = p
                break
        groups[prefix].append(f.name)

    lines = [
        "# Agent Tests Suite Map",
        "",
        f"Top-level `test_*.py` files: **{len(files)}**.",
        "",
        "Subdirs: `factors/`, `fixtures/`, `memory/`.",
        "",
        "## By domain prefix",
        "",
        "| prefix | count | examples |",
        "|--------|------:|----------|",
    ]
    for prefix, names in sorted(groups.items(), key=lambda x: (-len(x[1]), x[0])):
        ex = ", ".join(f"`{n}`" for n in names[:3])
        if len(names) > 3:
            ex += f", …(+{len(names)-3})"
        lines.append(f"| `{prefix}` | {len(names)} | {ex} |")

    lines.extend(
        [
            "",
            "## Notable areas (coverage intent)",
            "",
            "- **swarm_***: DAG, grounding, registry, trust model, worker, presets packaging",
            "- **loader / tushare / yahoo / okx / futu**: data fetch contracts",
            "- **runner / backtest / validation**: execution pipeline",
            "- **live / mandate / sdk / trading**: order gate & connectors",
            "- **session / goal / sse / api**: HTTP + EventBus",
            "- **mcp / security / web**: tool surface & SSRF",
            "- **shadow / factor / alpha**: research artifacts",
            "",
            "## Subpackages",
            "",
        ]
    )
    for sub in sorted(p.name for p in TESTS.iterdir() if p.is_dir() and not p.name.startswith(".")):
        n = sum(1 for _ in (TESTS / sub).rglob("test_*.py"))
        lines.append(f"- `{sub}/` — {n} test modules")

    (OUT / "TESTS.md").write_text("\n".join(lines), encoding="utf-8")
    print(f"tests: {len(files)}")


if __name__ == "__main__":
    write_channels()
    write_tests()
