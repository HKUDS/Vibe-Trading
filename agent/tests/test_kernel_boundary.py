"""Dependency and standalone execution contracts for the conversation kernel."""
import ast
import subprocess
import sys
from dataclasses import dataclass
from importlib.util import resolve_name
from pathlib import Path

KERNEL = Path(__file__).resolve().parents[1] / "src/kernel"

# Adding a dependency here is a review of what the generic runner can access.
ALLOWED_IMPORTS = {
    "__future__", "collections.abc", "concurrent.futures", "contextvars",
    "dataclasses", "enum", "itertools", "json", "logging", "queue",
    "threading", "time", "typing",
    "src.kernel.contracts", "src.kernel.events", "src.kernel.state",
}


def _import_targets(node, package):
    if isinstance(node, ast.Import):
        return [alias.name for alias in node.names]
    if not isinstance(node, ast.ImportFrom):
        return []
    target = "." * node.level + (node.module or "")
    try:
        module = resolve_name(target, package)
    except ImportError:
        return [target]
    if module == "src.kernel":
        return [f"{module}.{alias.name}" for alias in node.names]
    return [module]


def _optional_field_reads(tree, filename):
    # Limit getattr to the two optional data fields used by the scheduler.
    fields = {("loop.py", "response", "finish_reason"), ("progress.py", "_local", "emit")}
    for node in ast.walk(tree):
        match node:
            case ast.Call(func=ast.Name(id="getattr") as func, args=[
                ast.Name(id=receiver), ast.Constant(value=field), ast.Constant(value=None)
            ], keywords=[]):
                if (filename, receiver, field) in fields:
                    yield func


def test_kernel_import_allowlist():
    violations = []
    for path in sorted(KERNEL.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        relative = path.relative_to(KERNEL)
        package = ".".join(("src", "kernel", *relative.parent.parts))
        optional_reads = set(_optional_field_reads(tree, relative.as_posix()))
        for node in ast.walk(tree):
            for name in _import_targets(node, package):
                if name not in ALLOWED_IMPORTS:
                    violations.append(f"{relative}:{node.lineno} imports {name}")
            match node:
                case ast.Name(id=name) | ast.Attribute(attr=name):
                    pass
                case ast.FunctionDef(name=name) | ast.AsyncFunctionDef(name=name):
                    pass
                case _:
                    continue
            if name in {"__import__", "import_module", "__getattr__", "__getattribute__"} or (
                name == "getattr" and node not in optional_reads
            ):
                violations.append(f"{relative}:{node.lineno} uses {name}")
    assert not violations, "\n".join(violations)


def test_standalone_turn_with_fake_ports(tmp_path):
    # No site packages, editable installs or modules loaded by pytest fixtures.
    result = subprocess.run(
        [sys.executable, "-I", "-S", "-B", __file__], cwd=tmp_path,
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def _standalone_turn():
    class KernelOnly:
        def find_spec(self, fullname, path, target=None):
            root = fullname.partition(".")[0]
            if root in sys.stdlib_module_names or fullname in {"src", "src.kernel"}:
                return None
            if not fullname.startswith("src.kernel."):
                raise AssertionError(f"Standalone turn tried to load {fullname}")
            return None

    sys.meta_path.insert(0, KernelOnly())
    sys.path.insert(0, str(KERNEL.parents[1]))
    from src.kernel.contracts import BoundCall, LLMResponse, LoopDecision, LoopPorts, ToolCallRequest
    from src.kernel.loop import run_loop
    from src.kernel.tool_runner import execute_batch

    @dataclass
    class Context:
        iteration: int = 0
        final_answer_retry: bool = False
        final_answer_retry_pending: bool = False

    observed = []

    def prepare(context):
        context.iteration += 1
        return LoopDecision.CONTINUE

    def request(context):
        observed.append(("request", context.iteration))
        if context.iteration == 1:
            return LLMResponse(tool_calls=[ToolCallRequest("one", "echo", {"value": "hello"})])
        return LLMResponse(content="done")

    def run_tools(context, response):
        (call,) = response.tool_calls
        execute_batch([BoundCall(
            start=lambda parallel: lambda: (call.arguments["value"], 0),
            finish=lambda text, elapsed: observed.append((call.id, text)),
            skip=unexpected, parallel=False,
        )], cancelled=lambda: False)
        return LoopDecision.CONTINUE

    def after_text(context, response):
        observed.append(("answer", response.content))
        return LoopDecision.STOP

    def unexpected(*args):
        raise AssertionError(f"Unexpected port call {args}")

    ports = LoopPorts(prepare, request, unexpected, after_text, run_tools)
    run_loop(Context(), ports, max_iterations=3)
    assert observed == [("request", 1), ("one", "hello"), ("request", 2), ("answer", "done")]


if __name__ == "__main__":
    _standalone_turn()
