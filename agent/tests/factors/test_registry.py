"""Registry tests: scan, pydantic, lazy import, error isolation, sanity checks."""

from __future__ import annotations

import sys
import textwrap
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.factors.registry import (
    AlphaMeta,
    Registry,
    RegistryError,
    SkipAlpha,
    load_alpha_meta_from_py,
)


GOOD_META = """
__alpha_meta__ = {
    "id": "__FULL_ID__",
    "theme": ["momentum"],
    "formula_latex": r"close - open",
    "columns_required": ["close", "open"],
    "universe": ["equity_us"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 1,
}
"""

GOOD_COMPUTE = """
import pandas as pd
def compute(panel):
    return panel["close"] - panel["open"]
"""

BAD_COMPUTE_RAISES = """
def compute(panel):
    raise RuntimeError("intentional")
"""

BAD_COMPUTE_WRONG_TYPE = """
def compute(panel):
    return "not a dataframe"
"""

BAD_COMPUTE_INF = """
import numpy as np
import pandas as pd
def compute(panel):
    out = panel["close"].copy()
    out.iloc[0, 0] = np.inf
    return out
"""


def _full_id(zoo_id: str, short_id: str) -> str:
    suffix = short_id.split("_", 1)[-1] if "_" in short_id else short_id
    return f"{zoo_id}_{suffix}"


def _write_alpha(zoo_dir: Path, short_id: str, zoo_id: str, *, body: str = GOOD_COMPUTE, meta: str | None = None) -> None:
    meta_block = (meta or GOOD_META).replace("__FULL_ID__", _full_id(zoo_id, short_id))
    text = textwrap.dedent(meta_block).strip() + "\n\n" + textwrap.dedent(body).strip() + "\n"
    (zoo_dir / f"{short_id}.py").write_text(text, encoding="utf-8")


@pytest.fixture
def mini_zoo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Build a fake zoo tree and make src.factors.zoo resolve into it."""
    zoo_root = tmp_path / "factors" / "zoo"
    fake_zoo = zoo_root / "fakezoo"
    fake_zoo.mkdir(parents=True)
    (fake_zoo / "__init__.py").write_text("", encoding="utf-8")
    (zoo_root / "__init__.py").write_text("", encoding="utf-8")
    (tmp_path / "factors" / "__init__.py").write_text("", encoding="utf-8")

    _write_alpha(fake_zoo, "alpha_001", "fakezoo")
    _write_alpha(fake_zoo, "alpha_002", "fakezoo", body=BAD_COMPUTE_RAISES)
    _write_alpha(fake_zoo, "alpha_003", "fakezoo", body=BAD_COMPUTE_WRONG_TYPE)
    _write_alpha(fake_zoo, "alpha_004", "fakezoo", body=BAD_COMPUTE_INF)

    # Make `src.factors.zoo.fakezoo.<id>` importable from tmp_path's tree by
    # monkey-patching sys.path to include tmp_path, then creating an `src`
    # alias that points to `factors/`-as-`src.factors`.
    src_alias = tmp_path / "src"
    src_alias.symlink_to(tmp_path)
    monkeypatch.syspath_prepend(str(tmp_path))
    # Reset any cached modules from previous test
    for mod_name in list(sys.modules):
        if mod_name.startswith("src.factors.zoo.fakezoo"):
            del sys.modules[mod_name]

    return zoo_root


def _panel(n: int = 5) -> dict[str, pd.DataFrame]:
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    cols = ["X", "Y"]
    return {
        "close": pd.DataFrame(np.arange(n * 2, dtype=float).reshape(n, 2), index=idx, columns=cols),
        "open": pd.DataFrame(np.arange(n * 2, dtype=float).reshape(n, 2) * 0.5, index=idx, columns=cols),
    }


# ---------------- AST extraction ----------------


def test_load_alpha_meta_from_py(tmp_path: Path) -> None:
    f = tmp_path / "alpha_001.py"
    f.write_text(textwrap.dedent(GOOD_META.replace("__FULL_ID__", "fakezoo_001")) + "\n", encoding="utf-8")
    meta = load_alpha_meta_from_py(f)
    assert isinstance(meta, AlphaMeta)
    assert meta.id == "fakezoo_001"
    assert meta.columns_required == ["close", "open"]


def test_load_alpha_meta_missing_assignment(tmp_path: Path) -> None:
    f = tmp_path / "alpha_001.py"
    f.write_text("# no meta here\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="not found"):
        load_alpha_meta_from_py(f)


def test_load_alpha_meta_not_literal(tmp_path: Path) -> None:
    f = tmp_path / "alpha_001.py"
    f.write_text("x = 1\n__alpha_meta__ = some_callable()\n", encoding="utf-8")
    with pytest.raises(RegistryError, match="not a literal"):
        load_alpha_meta_from_py(f)


def test_load_alpha_meta_pydantic_rejects_unknown_field(tmp_path: Path) -> None:
    f = tmp_path / "alpha_001.py"
    bad = """
__alpha_meta__ = {
    "id": "x_001",
    "theme": ["momentum"],
    "formula_latex": "close",
    "columns_required": ["close"],
    "universe": ["equity_us"],
    "frequency": ["1d"],
    "decay_horizon": 5,
    "min_warmup_bars": 1,
    "py_module": "should be forbidden",
}
"""
    f.write_text(textwrap.dedent(bad), encoding="utf-8")
    with pytest.raises(RegistryError, match="validation"):
        load_alpha_meta_from_py(f)


def test_load_alpha_meta_py_size_cap(tmp_path: Path) -> None:
    f = tmp_path / "alpha_001.py"
    # pad to > _MAX_PY_BYTES (200 KB)
    body = "# " + "x" * 250_000 + "\n"
    f.write_text(body, encoding="utf-8")
    with pytest.raises(RegistryError, match="cap"):
        load_alpha_meta_from_py(f)


# ---------------- Registry scan + isolation ----------------


def test_registry_scans_and_reports_health(mini_zoo: Path) -> None:
    reg = Registry(zoo_root=mini_zoo)
    health = reg.health()
    # 4 alphas registered; isolation is at compute-time, not scan-time
    assert health["loaded"] == 4
    assert health["failed"] == 0


def test_registry_invalid_zoo_id_rejected(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    zoo_root = tmp_path / "factors" / "zoo"
    bad_zoo = zoo_root / "1bad"  # starts with digit → fails regex
    bad_zoo.mkdir(parents=True)
    _write_alpha(bad_zoo, "alpha_001", "fakezoo")
    reg = Registry(zoo_root=zoo_root)
    assert reg.health()["loaded"] == 0
    assert any("1bad" in e["alpha_id"] for e in reg.health()["errors"])


def test_registry_duplicate_id_rejected(tmp_path: Path) -> None:
    zoo_root = tmp_path / "factors" / "zoo"
    z = zoo_root / "fakezoo"
    z.mkdir(parents=True)
    _write_alpha(z, "alpha_001", "fakezoo")
    # second file with same alpha id (different filename, same __alpha_meta__["id"])
    text = textwrap.dedent(GOOD_META.replace("__FULL_ID__", "fakezoo_001")) + "\n" + textwrap.dedent(GOOD_COMPUTE) + "\n"
    (z / "alpha_dup.py").write_text(text, encoding="utf-8")
    reg = Registry(zoo_root=zoo_root)
    assert any("duplicate" in e["reason"] for e in reg.health()["errors"])


def test_registry_list_filters(mini_zoo: Path) -> None:
    reg = Registry(zoo_root=mini_zoo)
    assert reg.list(zoo="fakezoo") == sorted(reg.list())
    assert reg.list(theme="reversal") == []
    assert "fakezoo_001" in reg.list(theme="momentum")
    assert reg.list(universe="crypto") == []


def test_registry_get_unknown_raises(mini_zoo: Path) -> None:
    reg = Registry(zoo_root=mini_zoo)
    with pytest.raises(KeyError):
        reg.get("does_not_exist")


# ---------------- compute() error isolation ----------------


def test_registry_compute_good_alpha(mini_zoo: Path) -> None:
    reg = Registry(zoo_root=mini_zoo)
    out = reg.compute("fakezoo_001", _panel())
    assert isinstance(out, pd.DataFrame)
    assert out.shape == (5, 2)


def test_registry_compute_skip_missing_column(mini_zoo: Path) -> None:
    reg = Registry(zoo_root=mini_zoo)
    panel = _panel()
    del panel["open"]
    with pytest.raises(SkipAlpha, match="open"):
        reg.compute("fakezoo_001", panel)


def test_registry_compute_raises_isolated(mini_zoo: Path) -> None:
    reg = Registry(zoo_root=mini_zoo)
    with pytest.raises(RegistryError, match="intentional"):
        reg.compute("fakezoo_002", _panel())


def test_registry_compute_wrong_return_type(mini_zoo: Path) -> None:
    reg = Registry(zoo_root=mini_zoo)
    with pytest.raises(RegistryError, match="DataFrame"):
        reg.compute("fakezoo_003", _panel())


def test_registry_compute_inf_rejected(mini_zoo: Path) -> None:
    reg = Registry(zoo_root=mini_zoo)
    with pytest.raises(RegistryError, match="inf"):
        reg.compute("fakezoo_004", _panel())


# ---------------- export_manifest ----------------


def test_export_manifest_shape(mini_zoo: Path) -> None:
    reg = Registry(zoo_root=mini_zoo)
    m = reg.export_manifest()
    assert "generated_at" in m
    assert m["zoos"][0]["zoo_id"] == "fakezoo"
    assert len(m["zoos"][0]["alphas"]) == 4


def test_registry_masks_nan_on_declared_dependencies(mini_zoo: Path) -> None:
    reg = Registry(zoo_root=mini_zoo)
    panel = _panel()
    # NaN in a required column should propagate to output
    panel["close"].iloc[2, 0] = np.nan
    out = reg.compute("fakezoo_001", panel)
    assert np.isnan(out.iloc[2, 0])
    # Also test with NaN in another required column
    panel = _panel()
    panel["open"].iloc[1, 1] = np.nan
    out = reg.compute("fakezoo_001", panel)
    assert np.isnan(out.iloc[1, 1])


def test_registry_masks_nan_without_close_declared(mini_zoo: Path) -> None:
    """The NaN mask must run even when the alpha does not declare ``close``.

    The mask's shape reference was hardcoded to ``panel["close"]``, so an alpha
    declaring only ``["open"]`` got no NaN enforcement on a panel without a
    close column — a fabricated value (np.where on a NaN comparison) survived.
    The reference is now the first declared dependency.
    """
    reg = Registry(zoo_root=mini_zoo)
    meta = GOOD_META.replace('"close", "open"', '"open"')
    body = textwrap.dedent(
        """\
        import numpy as np
        import pandas as pd

        def compute(panel):
            o = panel["open"]
            # NaN < 0 is False: a missing bar falls through to 0.0 (fabricated).
            return pd.DataFrame(np.where(o < 0, 1.0, 0.0), index=o.index, columns=o.columns)
        """
    )
    _write_alpha(mini_zoo / "fakezoo", "alpha_005", "fakezoo", meta=meta, body=body)
    reg = Registry(zoo_root=mini_zoo)
    panel = _panel()
    del panel["close"]  # no close column at all
    panel["open"].iloc[2, 0] = np.nan
    out = reg.compute("fakezoo_005", panel)
    assert np.isnan(out.iloc[2, 0])  # masked, not the fabricated 0.0
    assert out.notna().sum().sum() > 0  # mask did not wipe the whole panel


# ---------------- filesystem loader vs the bundled module cache ----------------


def _wave_panel(n: int = 30) -> dict[str, pd.DataFrame]:
    """A panel that rises and falls, so cntp5's output is not a constant."""
    idx = pd.date_range("2024-01-01", periods=n, freq="D")
    cols = ["X", "Y"]
    wave = np.sin(np.arange(n, dtype=float)).reshape(n, 1)
    close = pd.DataFrame(np.repeat(wave, 2, axis=1), index=idx, columns=cols)
    return {"close": close, "open": close * 0.99}


def test_custom_zoo_root_does_not_shadow_the_bundled_module(tmp_path: Path) -> None:
    """A custom zoo_root must not replace a bundled alpha process-wide (#1465).

    Both roots derive the same ``module_path``
    (``src.factors.zoo.<zoo>.<short>``), and the filesystem loader registered its
    module under that bare name in ``sys.modules``. The bundled registry's own
    ``importlib.import_module`` then returned the custom module, so a default
    ``Registry()`` silently computed the custom code.
    """
    zoo_root = tmp_path / "zoo"
    (zoo_root / "qlib158").mkdir(parents=True)
    _write_alpha(
        zoo_root / "qlib158",
        "cntp5",
        "qlib158",
        body="""
        import pandas as pd

        def compute(panel):
            c = panel["close"]
            return pd.DataFrame(1.0, index=c.index, columns=c.columns)
        """,
    )

    module_path = "src.factors.zoo.qlib158.cntp5"
    previous = sys.modules.get(module_path)
    try:
        panel = _wave_panel()
        # Bundled registry: this imports the real module into sys.modules.
        bundled = Registry().compute("qlib158_cntp5", panel)
        # A custom root reusing the same zoo/alpha names must not touch it.
        # Modules load lazily, so the custom root has to compute for the
        # collision to happen at all.
        custom = Registry(zoo_root=zoo_root).compute("qlib158_cntp5", panel)
        assert (custom.to_numpy() == 1.0).all()  # the custom root did load its file
        again = Registry().compute("qlib158_cntp5", panel)
    finally:
        if previous is None:
            sys.modules.pop(module_path, None)
        else:
            sys.modules[module_path] = previous

    assert not (bundled.to_numpy() == 1.0).all()  # baseline is the real alpha
    pd.testing.assert_frame_equal(bundled, again)
