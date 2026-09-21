from __future__ import annotations

import ast
from pathlib import Path

import numpy as np
import pandas as pd


SKILL_PATH = Path(__file__).parents[1] / "src" / "skills" / "ml-strategy" / "SKILL.md"


def _python_block() -> str:
    text = SKILL_PATH.read_text(encoding="utf-8")
    return text.split("```python", 1)[1].split("```", 1)[0]


def _load_node(name: str, node_type: type[ast.AST], namespace: dict) -> object:
    tree = ast.parse(_python_block())
    node = next(
        item for item in tree.body if isinstance(item, node_type) and item.name == name
    )
    module = ast.Module(body=[node], type_ignores=[])
    exec(compile(module, str(SKILL_PATH), "exec"), namespace)
    return namespace[name]


class _IdentityScaler:
    def fit_transform(self, values):
        return values

    def transform(self, values):
        return values


class _RecordingModel:
    fits: list[np.ndarray] = []

    def __init__(self, *args, **kwargs):
        pass

    def fit(self, values, labels):
        self.fits.append(values.copy())
        return self

    def predict_proba(self, values):
        return np.array([[0.5, 0.5]])


def _namespace() -> dict:
    return {
        "np": np,
        "pd": pd,
        "StandardScaler": _IdentityScaler,
        "RandomForestClassifier": _RecordingModel,
        "GradientBoostingClassifier": _RecordingModel,
        "LogisticRegression": _RecordingModel,
    }


def test_walk_forward_purges_labels_not_observable_at_prediction_time() -> None:
    walk_forward_predict = _load_node(
        "walk_forward_predict",
        ast.FunctionDef,
        _namespace(),
    )
    features = pd.DataFrame({"row": np.arange(70, dtype=float)})
    labels = pd.Series(np.arange(70, dtype=float) % 2)
    _RecordingModel.fits.clear()

    walk_forward_predict(features, labels, min_train_size=60, retrain_freq=100)

    assert _RecordingModel.fits[0][-1, 0] == 55.0


def test_one_bar_horizon_preserves_existing_training_window() -> None:
    walk_forward_predict = _load_node(
        "walk_forward_predict",
        ast.FunctionDef,
        _namespace(),
    )
    features = pd.DataFrame({"row": np.arange(70, dtype=float)})
    labels = pd.Series(np.arange(70, dtype=float) % 2)
    _RecordingModel.fits.clear()

    walk_forward_predict(
        features,
        labels,
        min_train_size=60,
        retrain_freq=100,
        prediction_horizon=1,
    )

    assert _RecordingModel.fits[0][-1, 0] == 59.0


def test_walk_forward_skips_a_single_class_window_with_a_real_classifier() -> None:
    """The stub model above accepts any label distribution; scikit-learn's
    classifiers do not. A training window that happens to hold only one
    class (a sustained one-directional trend) must not crash fit() or
    predict_proba() on any of the three supported model types."""
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    namespace = {
        "np": np,
        "pd": pd,
        "StandardScaler": StandardScaler,
        "RandomForestClassifier": RandomForestClassifier,
        "GradientBoostingClassifier": GradientBoostingClassifier,
        "LogisticRegression": LogisticRegression,
    }
    walk_forward_predict = _load_node(
        "walk_forward_predict", ast.FunctionDef, namespace
    )

    rng = np.random.default_rng(0)
    features = pd.DataFrame({f"f{i}": rng.standard_normal(300) for i in range(5)})
    labels = pd.Series(0.0, index=range(300))
    labels.iloc[280:] = 1.0  # single class for every window until near the end

    for model_type in ("random_forest", "gradient_boosting", "ridge"):
        result = walk_forward_predict(
            features, labels, min_train_size=252, retrain_freq=20, model_type=model_type
        )
        assert not result.isna().any()
        assert result.between(-1.0, 1.0).all()


def test_a_skipped_retrain_keeps_serving_the_previous_model() -> None:
    """The retrain day itself is predicted too, not left at 0.0 (#1522)."""
    from sklearn.ensemble import GradientBoostingClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.preprocessing import StandardScaler

    namespace = {
        "np": np,
        "pd": pd,
        "StandardScaler": StandardScaler,
        "RandomForestClassifier": RandomForestClassifier,
        "GradientBoostingClassifier": GradientBoostingClassifier,
        "LogisticRegression": LogisticRegression,
    }
    walk_forward_predict = _load_node("walk_forward_predict", ast.FunctionDef, namespace)

    rng = np.random.default_rng(1)
    features = pd.DataFrame({f"f{i}": rng.standard_normal(260) for i in range(3)})
    # Two classes early, one class from row 120: a 60-row sliding window that
    # starts at or after row 120 holds a single class.
    labels = pd.Series(np.where(np.arange(260) < 120, np.arange(260) % 2, 1.0))

    result = walk_forward_predict(
        features,
        labels,
        min_train_size=100,
        retrain_freq=20,
        model_type="ridge",
        window_type="sliding",
        sliding_size=60,
        prediction_horizon=1,
    )

    single_class_retrain_days = [
        i for i in range(100, 260) if (i - 100) % 20 == 0 and max(0, i - 60) >= 120
    ]
    assert single_class_retrain_days, "the fixture must reach a single-class window"
    assert all(result.iloc[i] != 0.0 for i in single_class_retrain_days)


def test_signal_engine_preserves_unavailable_future_labels_as_nan() -> None:
    captured: dict[str, object] = {}

    def fake_predict(features, labels, **kwargs):
        captured["labels"] = labels.copy()
        captured["prediction_horizon"] = kwargs.get("prediction_horizon")
        return pd.Series(0.0, index=features.index)

    namespace = {
        "np": np,
        "pd": pd,
        "validate_data": lambda df: True,
        "build_features": lambda df: pd.DataFrame(
            {"x": np.arange(len(df))}, index=df.index
        ),
        "walk_forward_predict": fake_predict,
    }
    signal_engine = _load_node("SignalEngine", ast.ClassDef, namespace)

    frame = pd.DataFrame({"close": np.arange(1, 11, dtype=float)})
    signal_engine().generate({"TEST": frame})

    labels = captured["labels"]
    assert captured["prediction_horizon"] == 5
    assert labels.iloc[:5].eq(1.0).all()
    assert labels.iloc[-5:].isna().all()
