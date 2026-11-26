"""read_file and __data_ref__ select one JSON value by RFC 6901 pointer, or fail explicitly.

Ported from claude/agent-runtime-simplify (5050655e5). A missing or malformed
pointer must be an error, never the whole document: a reader that silently gets
the full file reads as a correct selection.
"""

from __future__ import annotations

import inspect
import json

import pytest

from src.agent.tools import ToolRegistry
from src.config.accessor import get_env_config
from src.product.result_artifacts import deliver_tool_result
from src.product.tool_policy import ToolPolicy
from src.tools.data_refs import resolve_data_refs
from src.tools.path_utils import FileRoots
from src.tools.read_file_tool import ReadFileTool


def _roots() -> FileRoots:
    return FileRoots.from_config(get_env_config().api)


@pytest.fixture()
def source(tmp_path, monkeypatch):
    monkeypatch.setenv("VIBE_TRADING_ALLOWED_RUN_ROOTS", str(tmp_path))
    value = {
        "series": {"truncated": True, "data": [{"close": i} for i in range(12000)]},
        "a/b~": {"": [False, 0, None]},
        "_provenance": {"source": "recorded", "currency": "USD"},
    }
    path = tmp_path / "observations.json"
    path.write_text(json.dumps(value))
    return path, value


def read(path, pointer, **kwargs):
    return json.loads(ReadFileTool(roots=_roots()).execute(
        path=str(path), run_dir=str(path.parent), pointer=pointer, **kwargs))


@pytest.mark.parametrize("pointer,expected,sampled", [
    ("/_provenance", {"source": "recorded", "currency": "USD"}, False),
    ("/series/data/11999", {"close": 11999}, True),
    ("/a~1b~0//0", False, False),
    ("/a~1b~0//1", 0, False),
    ("/a~1b~0//2", None, False),
])
def test_exact_selection_retains_source_coverage(source, pointer, expected, sampled):
    path, _ = source
    body = read(path, pointer)
    assert body["status"] == "ok"
    assert json.loads(body["content"]) == expected
    assert body["pointer"] == pointer
    assert body["source_chars"] == len(path.read_text())
    assert bool(body.get("source_truncated")) is sampled
    assert not body.get("truncated")
    assert len(json.dumps(body)) < 1000


def test_empty_pointer_selects_the_whole_document(source):
    path, _ = source
    small = path.parent / "small.json"
    small.write_text('{"x": [1]}')
    whole = read(small, "")
    assert whole["status"] == "ok" and whole["pointer"] == ""
    assert json.loads(whole["content"]) == {"x": [1]}
    assert not whole.get("truncated")


@pytest.mark.parametrize("pointer", [
    "missing-slash", "/missing", "/a~2b", "/series/data/-1", "/series/data/01",
    "/series/data/12000", "/series/data/0/close/x", "/series/data/-", 3,
])
def test_invalid_selection_fails_without_returning_the_whole_file(source, pointer):
    path, _ = source
    body = read(path, pointer)
    assert body["status"] == "error"
    assert "content" not in body


def test_selection_keeps_limits_and_source_metadata(source):
    path, value = source
    registry = ToolRegistry(policy=ToolPolicy.from_config(get_env_config()))
    registry.register(ReadFileTool(roots=_roots()))
    body = read(path, "/series/data")
    assert body["truncated"] and body["source_truncated"]
    assert body["total_chars"] == len(json.dumps(value["series"]["data"], ensure_ascii=False, indent=2))
    receipt = json.loads(deliver_tool_result(json.dumps(body), path.parent, registry, tool_name="read_file"))
    for key in ("pointer", "source_chars", "total_chars", "source_truncated", "truncated"):
        assert receipt[key] == body[key]
    assert receipt["path"] == str(path)
    limited = read(path, "/_provenance", limit=1)
    assert limited["truncated"] and limited["content"] == "{\n"


def test_selection_does_not_bypass_file_boundaries(source, tmp_path):
    path, _ = source
    directory = read(path.parent, "")
    assert directory["status"] == "error" and "content" not in directory and "entries" not in directory
    invalid = tmp_path / "invalid.txt"
    invalid.write_text("not JSON")
    invalid_result = read(invalid, "")
    assert invalid_result["status"] == "error"
    assert invalid_result["error_code"] == "invalid_json"
    assert "Omit pointer" in invalid_result["error"]
    link = tmp_path / "outside.json"
    link.symlink_to("/etc/hosts")
    assert read(link, "")["error_code"] == "outside_readable_roots"


@pytest.mark.parametrize("pointer", ["/missing", "/a~2b", "/series/data/01", "/series/data/12000", "nope"])
def test_data_ref_pointer_errors_are_explicit(source, pointer):
    path, _ = source
    with pytest.raises(ValueError, match="pointer"):
        resolve_data_refs({"__data_ref__": {"path": str(path), "pointer": pointer}},
                          str(path.parent), [], roots=_roots())


def test_data_ref_pointer_selects_the_same_value_as_read_file(source):
    path, value = source
    sources = []
    selected = resolve_data_refs({"__data_ref__": {"path": str(path), "pointer": "/a~1b~0//1"}},
                                 str(path.parent), sources, roots=_roots())
    assert selected == 0 == json.loads(read(path, "/a~1b~0//1")["content"])
    assert sources[0]["pointer"] == "/a~1b~0//1"


def test_mcp_forwards_same_selection_contract(monkeypatch):
    import mcp_server

    calls = []

    class Registry:
        def execute(self, name, arguments):
            calls.append((name, arguments))
            return "result"

    monkeypatch.setattr(mcp_server, "_get_registry", Registry)
    wrapper = getattr(mcp_server.read_file, "fn", None) or mcp_server.read_file
    assert set(inspect.signature(wrapper).parameters) == set(ReadFileTool.parameters["properties"])
    assert wrapper("data.json", pointer="/rows/2", limit=4) == "result"
    wrapper("data.json")
    assert calls == [
        ("read_file", {"path": "data.json", "pointer": "/rows/2", "limit": 4}),
        ("read_file", {"path": "data.json"}),
    ]
