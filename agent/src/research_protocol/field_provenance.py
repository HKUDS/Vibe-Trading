"""Protocol field provenance with v1.2.1 confirmation state."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

SCHEMA_VERSION = "1.2.1"

FieldSource = Literal["explicit_user", "system_default", "inferred", "missing"]
ConfirmationStatus = Literal["not_required", "pending", "confirmed", "rejected"]


class ProtocolFieldProvenance(BaseModel):
    """Source and confirmation status for one protocol field."""

    model_config = ConfigDict(extra="ignore")

    schema_version: str = SCHEMA_VERSION
    field_path: str
    source: FieldSource
    confidence: float | None = None
    evidence_text: str | None = None
    requires_confirmation: bool = False
    confirmation_status: ConfirmationStatus = "not_required"
    confirmation_event_hash: str | None = None
    default_rule_id: str | None = None

    @field_validator("field_path")
    @classmethod
    def _field_path_not_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("field_path must not be empty")
        return text

    @field_validator("confidence")
    @classmethod
    def _confidence_between_zero_and_one(cls, value: float | None) -> float | None:
        if value is not None and not 0.0 <= value <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        return value

    @model_validator(mode="after")
    def _validate_confirmation_state(self) -> "ProtocolFieldProvenance":
        if self.source == "system_default" and not self.default_rule_id:
            raise ValueError("system_default provenance requires default_rule_id")
        if self.source == "inferred" and self.requires_confirmation and self.confirmation_status == "not_required":
            self.confirmation_status = "pending"
        if self.confirmation_status == "confirmed" and not self.confirmation_event_hash:
            raise ValueError("confirmed provenance requires confirmation_event_hash")
        if not self.requires_confirmation and self.confirmation_status == "pending":
            raise ValueError("pending confirmation requires requires_confirmation=True")
        return self
