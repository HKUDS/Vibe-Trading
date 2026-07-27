"""Extract catalog inventories for skills, alphas, swarm presets."""
from __future__ import annotations

import ast
import json
import re
from pathlib import Path

ROOT = Path(r"c:\Users\user\Desktop\github\Vibe-Trading")
OUT = ROOT / "docs" / "analysis" / "catalog"
OUT.mkdir(parents=True, exist_ok=True)


def parse_frontmatter(text: str) -> dict[str, str]:
    fm: dict[str, str] = {}
    if not text.startswith("---"):
        return fm
    end = text.find("---", 3)
    if end < 0:
        return fm
    for line in text[3:end].splitlines():
        if ":" not in line:
            continue
        k, v = line.split(":", 1)
        fm[k.strip()] = v.strip().strip("\"'")
    return fm


def inventory_skills() -> list[dict]:
    skills_root = ROOT / "agent" / "src" / "skills"
    rows: list[dict] = []
    for d in sorted(skills_root.iterdir()):
        if not d.is_dir() or d.name.startswith("."):
            continue
        skill = d / "SKILL.md"
        if not skill.exists():
            rows.append({"id": d.name, "error": "no SKILL.md"})
            continue
        text = skill.read_text(encoding="utf-8", errors="replace")
        fm = parse_frontmatter(text)
        n_files = sum(1 for p in d.rglob("*") if p.is_file())
        rows.append(
            {
                "id": d.name,
                "name": fm.get("name", d.name),
                "category": fm.get("category", "") or "uncategorized",
                "description": (fm.get("description") or "")[:400],
                "files": n_files,
                "has_example_engine": (d / "example_signal_engine.py").exists(),
                "body_chars": len(text),
            }
        )
    return rows


def load_alpha_meta(path: Path) -> dict | None:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
    except SyntaxError:
        return None
    for node in tree.body:
        if isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name) and t.id == "__alpha_meta__":
                    try:
                        return ast.literal_eval(node.value)
                    except Exception:
                        return {"id": path.stem, "error": "non-literal meta"}
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if node.target.id == "__alpha_meta__" and node.value is not None:
                try:
                    return ast.literal_eval(node.value)
                except Exception:
                    return {"id": path.stem, "error": "non-literal meta"}
    return None


def inventory_alphas() -> list[dict]:
    zoo = ROOT / "agent" / "src" / "factors" / "zoo"
    rows: list[dict] = []
    for zoo_dir in sorted(zoo.iterdir()):
        if not zoo_dir.is_dir() or zoo_dir.name.startswith(("_", ".")):
            continue
        for py in sorted(zoo_dir.glob("*.py")):
            if py.name.startswith("_"):
                continue
            meta = load_alpha_meta(py) or {}
            rows.append(
                {
                    "zoo": zoo_dir.name,
                    "file": py.name,
                    "id": meta.get("id") or f"{zoo_dir.name}_{py.stem}",
                    "theme": meta.get("theme")
                    if isinstance(meta.get("theme"), str)
                    else (
                        ",".join(str(x) for x in meta.get("theme"))
                        if isinstance(meta.get("theme"), (list, tuple))
                        else str(meta.get("theme") or "")
                    ),
                    "formula_latex": str(meta.get("formula_latex") or "")[:200],
                    "columns_required": meta.get("columns_required") or [],
                    "extras_required": meta.get("extras_required") or [],
                    "requires_sector": bool(meta.get("requires_sector")),
                    "universe": meta.get("universe", ""),
                    "frequency": meta.get("frequency", ""),
                    "decay_horizon": meta.get("decay_horizon"),
                    "min_warmup_bars": meta.get("min_warmup_bars"),
                    "error": meta.get("error"),
                }
            )
    return rows


def inventory_swarm() -> list[dict]:
    presets = ROOT / "agent" / "src" / "swarm" / "presets"
    rows: list[dict] = []
    try:
        import yaml  # type: ignore
    except ImportError:
        yaml = None

    for path in sorted(presets.glob("*.yaml")):
        text = path.read_text(encoding="utf-8", errors="replace")
        data: dict = {}
        if yaml is not None:
            data = yaml.safe_load(text) or {}
        else:
            # minimal fallback
            for key in ("name", "title", "description"):
                m = re.search(rf"^{key}:\s*[\"']?(.*?)[\"']?\s*$", text, re.M)
                if m:
                    data[key] = m.group(1)
            data["agents"] = re.findall(r"^\s*-\s*id:\s*(\S+)", text, re.M)
            data["tasks"] = re.findall(r"^\s*-\s*id:\s*(\S+)", text, re.M)

        agents = data.get("agents") or []
        tasks = data.get("tasks") or []
        agent_ids = [
            a.get("id") if isinstance(a, dict) else str(a) for a in agents
        ]
        task_ids = [t.get("id") if isinstance(t, dict) else str(t) for t in tasks]
        deps = []
        for t in tasks:
            if isinstance(t, dict) and t.get("depends_on"):
                deps.append({"task": t.get("id"), "depends_on": t.get("depends_on")})
        rows.append(
            {
                "file": path.name,
                "name": data.get("name") or path.stem,
                "title": data.get("title") or "",
                "description": (data.get("description") or "")[:400],
                "n_agents": len(agents),
                "n_tasks": len(tasks),
                "agent_ids": agent_ids,
                "task_ids": task_ids,
                "dependencies": deps,
                "variables": list((data.get("variables") or {}).keys())
                if isinstance(data.get("variables"), dict)
                else data.get("variables") or [],
            }
        )
    return rows


def write_md_skills(rows: list[dict]) -> None:
    by_cat: dict[str, list] = {}
    for r in rows:
        by_cat.setdefault(r.get("category") or "uncategorized", []).append(r)
    lines = [
        "# Skills Catalog (88)",
        "",
        f"Total: **{len(rows)}** skills under `agent/src/skills/`.",
        "",
        "## By category",
        "",
    ]
    for cat in sorted(by_cat):
        lines.append(f"### {cat} ({len(by_cat[cat])})")
        lines.append("")
        lines.append("| id | description | files | example_engine |")
        lines.append("|----|-------------|------:|:--------------:|")
        for r in by_cat[cat]:
            desc = (r.get("description") or "").replace("|", "/")
            lines.append(
                f"| `{r['id']}` | {desc} | {r.get('files', 0)} | "
                f"{'Y' if r.get('has_example_engine') else ''} |"
            )
        lines.append("")
    (OUT / "SKILLS.md").write_text("\n".join(lines), encoding="utf-8")


def write_md_alphas(rows: list[dict]) -> None:
    by_zoo: dict[str, list] = {}
    for r in rows:
        by_zoo.setdefault(r["zoo"], []).append(r)
    lines = [
        "# Alpha Zoo Catalog",
        "",
        f"Total modules with meta: **{len(rows)}**.",
        "",
    ]
    for zoo in sorted(by_zoo):
        items = by_zoo[zoo]
        lines.append(f"## {zoo} ({len(items)})")
        lines.append("")
        lines.append("| id | theme | columns | warmup | formula |")
        lines.append("|----|-------|---------|-------:|---------|")
        for r in items:
            cols = ",".join(r.get("columns_required") or [])[:40]
            formula = (r.get("formula_latex") or "").replace("|", "/")[:60]
            theme = (r.get("theme") or "").replace("|", "/")[:30]
            lines.append(
                f"| `{r['id']}` | {theme} | {cols} | {r.get('min_warmup_bars') or ''} | {formula} |"
            )
        lines.append("")
    (OUT / "ALPHAS.md").write_text("\n".join(lines), encoding="utf-8")


def write_md_swarm(rows: list[dict]) -> None:
    lines = [
        "# Swarm Presets Catalog (30)",
        "",
        f"Total: **{len(rows)}**.",
        "",
    ]
    for r in rows:
        lines.append(f"## `{r['name']}` — {r.get('title') or r['file']}")
        lines.append("")
        lines.append(r.get("description") or "(no description)")
        lines.append("")
        lines.append(f"- agents ({r['n_agents']}): {', '.join(f'`{a}`' for a in r['agent_ids'])}")
        lines.append(f"- tasks ({r['n_tasks']}): {', '.join(f'`{t}`' for t in r['task_ids'])}")
        if r.get("dependencies"):
            lines.append("- depends_on:")
            for d in r["dependencies"]:
                lines.append(f"  - `{d['task']}` ← {d['depends_on']}")
        if r.get("variables"):
            lines.append(f"- variables: {r['variables']}")
        lines.append("")
    (OUT / "SWARM_PRESETS.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    skills = inventory_skills()
    (OUT / "skills_inventory.json").write_text(
        json.dumps(skills, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_md_skills(skills)
    print(f"skills: {len(skills)}")

    alphas = inventory_alphas()
    (OUT / "alphas_inventory.json").write_text(
        json.dumps(alphas, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_md_alphas(alphas)
    print(f"alphas: {len(alphas)}")

    swarm = inventory_swarm()
    (OUT / "swarm_inventory.json").write_text(
        json.dumps(swarm, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_md_swarm(swarm)
    print(f"swarm: {len(swarm)}")


if __name__ == "__main__":
    main()
