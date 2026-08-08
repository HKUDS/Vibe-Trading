"""BaseTool wrapper for registering factors/strategies into the strategy store."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any

from src.agent.tools import BaseTool
from src.strategy_store.models import (
    Artifact,
    ArtifactStatus,
    ArtifactType,
    ModelTier,
    ValidationStatus,
)
from src.strategy_store._shared import get_store as _get_store


def _ok(payload: dict[str, Any]) -> str:
    return json.dumps({"status": "ok", **payload}, ensure_ascii=False)


def _error(exc: Exception) -> str:
    return json.dumps({"status": "error", "error": str(exc)}, ensure_ascii=False)


class SdmRegisterTool(BaseTool):
    """Register a new factor or strategy into the strategy store."""

    name = "sdm_register"
    description = (
        "Register a new factor or strategy extracted from a paper into the "
        "strategy store. Research-only: does not place trades."
    )
    is_readonly = False
    repeatable = True
    parameters = {
        "type": "object",
        "properties": {
            "artifact_type": {
                "type": "string",
                "enum": ["factor", "strategy"],
                "description": "Type of artifact",
            },
            "name": {
                "type": "string",
                "description": "Unique name for the factor or strategy",
            },
            "universe": {
                "type": "string",
                "description": "Target market universe (e.g. CSI300, SP500, BTC)",
            },
            "source_paper": {
                "type": "string",
                "description": "Source paper title or DOI",
            },
            "source_url": {
                "type": "string",
                "description": "Source paper URL",
            },
            "formula_latex": {
                "type": "string",
                "description": "Factor formula in LaTeX (factor only)",
            },
            "theme": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Factor themes (factor only)",
            },
            "columns_required": {
                "type": "array",
                "items": {"type": "string"},
                "description": "Required data columns (factor only)",
            },
            "signal_definition": {
                "type": "string",
                "description": "Signal logic description (strategy only)",
            },
            "signal_engine_path": {
                "type": "string",
                "description": "Path to signal_engine.py",
            },
            "hypothesis_id": {
                "type": "string",
                "description": "Linked hypothesis ID",
            },
            # --- model governance -------------------------------------------
            # Without these an artifact is an UNREGISTERED MODEL under any
            # firm's own model-risk policy: nobody owns it, nobody validated
            # it, and nothing records what it may and may not be used for.
            "developer": {
                "type": "string",
                "description": "Who built this model. Kept separate from approver on purpose.",
            },
            "owner": {
                "type": "string",
                "description": "Who is accountable for it in production.",
            },
            "validator": {
                "type": "string",
                "description": "Who independently validated it.",
            },
            "approver": {
                "type": "string",
                "description": (
                    "Who approved it for use. Same person as developer is a "
                    "four-eyes violation -- allowed here, but reported by "
                    "sdm_status so it can be seen."
                ),
            },
            "model_version": {"type": "string", "description": "Version of the model itself."},
            "artifact_version": {
                "type": "string",
                "description": "Version of the artifact this model is bound to.",
            },
            "model_tier": {
                "type": "string",
                "enum": ["tier_1_critical", "tier_2_significant", "tier_3_limited"],
                "description": "Materiality tier; decides how much validation is required.",
            },
            "intended_use": {
                "type": "string",
                "description": (
                    "What this model may be used for. Required whenever any "
                    "governance field is supplied."
                ),
            },
            "limitations": {
                "type": "string",
                "description": (
                    "Where it stops being valid. Required whenever any "
                    "governance field is supplied -- a model registration with "
                    "no stated limitations is not a registration."
                ),
            },
            "validation_status": {
                "type": "string",
                "enum": ["unvalidated", "in_validation", "validated", "approved", "rejected"],
                "description": (
                    "Lifecycle state. Cannot jump straight to 'approved' from "
                    "'unvalidated'; the store refuses it."
                ),
            },
            "validation_date": {
                "type": "string",
                "description": (
                    "ISO date the validation was performed. Never auto-filled -- "
                    "stamping a date on a model nobody validated would fabricate "
                    "the evidence the field exists to carry."
                ),
            },
        },
        "required": ["artifact_type", "name", "universe"],
    }

    #: Governance fields. Supplying any one of them means this registration is
    #: claiming to be a model record, which makes intended_use and limitations
    #: mandatory -- a claim without those two cannot be reviewed.
    _GOVERNANCE_FIELDS = (
        "developer", "owner", "validator", "approver", "model_version",
        "artifact_version", "model_tier", "intended_use", "limitations",
        "validation_status", "validation_date",
    )

    def execute(self, **kwargs: Any) -> str:
        """Build an Artifact from kwargs, register it, and return the record."""
        try:
            store = _get_store()

            artifact_type = ArtifactType(kwargs["artifact_type"])

            theme_raw = kwargs.get("theme")
            theme = tuple(theme_raw) if theme_raw else ()

            columns_raw = kwargs.get("columns_required")
            columns_required = tuple(columns_raw) if columns_raw else ()

            artifact = Artifact(
                id="",
                type=artifact_type,
                name=str(kwargs["name"]),
                universe=str(kwargs["universe"]),
                source_paper=kwargs.get("source_paper"),
                source_url=kwargs.get("source_url"),
                formula_latex=kwargs.get("formula_latex"),
                theme=theme,
                columns_required=columns_required,
                signal_definition=kwargs.get("signal_definition"),
                signal_engine_path=kwargs.get("signal_engine_path"),
                hypothesis_id=kwargs.get("hypothesis_id"),
                status=ArtifactStatus.CREATED,
                **self._governance_kwargs(kwargs),
            )

            artifact_id = store.register_artifact(artifact)
            stored = store.get_artifact(artifact_id)
            return _ok({"artifact": asdict(stored)})  # type: ignore[arg-type]
        except Exception as exc:
            return _error(exc)

    def _governance_kwargs(self, kwargs: dict[str, Any]) -> dict[str, Any]:
        """Extract the model-governance fields, enforcing the pair that matters.

        Supplying any governance field means this registration claims to be a
        model record. Two of them are then mandatory: ``intended_use`` says what
        the model may be used for and ``limitations`` says where it stops being
        valid. A registration missing either cannot be reviewed by anyone, which
        makes it indistinguishable from no registration at all.

        Args:
            kwargs: Raw tool arguments.

        Returns:
            Keyword arguments to pass to :class:`Artifact`, empty when no
            governance field was supplied.

        Raises:
            ValueError: If governance fields were supplied without both
                ``intended_use`` and ``limitations``, or if an enum value is
                unknown.
        """
        supplied = {
            f: kwargs[f]
            for f in self._GOVERNANCE_FIELDS
            if kwargs.get(f) not in (None, "")
        }
        if not supplied:
            return {}

        missing = [f for f in ("intended_use", "limitations") if f not in supplied]
        if missing:
            raise ValueError(
                f"model governance fields were supplied ({sorted(supplied)}), so "
                f"{missing} are required too. A model record without a stated "
                "intended use and stated limitations cannot be reviewed."
            )

        if "model_tier" in supplied:
            supplied["model_tier"] = ModelTier(supplied["model_tier"])
        if "validation_status" in supplied:
            supplied["validation_status"] = ValidationStatus(supplied["validation_status"])
        return supplied
