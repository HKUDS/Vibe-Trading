"""Industry and size neutralized IC diagnostics."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from src.reliability.quant.scorecard import QuantIssue


class IndustryClassificationDecision(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    source: str
    warnings: list[QuantIssue] = Field(default_factory=list)


class NeutralizedICReport(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)

    ic_raw: float
    ic_industry_neutral: float | None = None
    ic_size_neutral: float | None = None
    ic_double_neutral: float | None = None
    selected_ic: float | None = None
    classification_source: str
    taxonomy: str
    as_of: str
    warnings: list[QuantIssue] = Field(default_factory=list)


def select_industry_classification(
    *,
    wind: str | None,
    citic: str | None,
    sw: str | None,
) -> IndustryClassificationDecision:
    """Select industry classification by Phase 5 priority."""
    for value in (wind, citic, sw):
        if value:
            return IndustryClassificationDecision(source=value)
    return IndustryClassificationDecision(
        source="unavailable",
        warnings=[
            QuantIssue(
                code="QUANT_INDUSTRY_CLASSIFICATION_UNAVAILABLE",
                severity="warning",
                message="industry classification is unavailable",
            )
        ],
    )


def build_neutralized_ic_report(
    *,
    ic_raw: float,
    ic_size_neutral: float | None,
    ic_industry_neutral: float | None,
    ic_double_neutral: float | None,
    classification_source: str,
    taxonomy: str,
    as_of: str,
) -> NeutralizedICReport:
    """Build neutralized IC report and select the scorecard IC value."""
    warnings: list[QuantIssue] = []
    selected = ic_double_neutral
    if selected is None:
        selected = ic_size_neutral
        warnings.append(
            QuantIssue(
                code="QUANT_NEUTRALIZED_IC_FALLBACK_TO_SIZE",
                severity="warning",
                message="double-neutral IC unavailable; falling back to size-neutral IC",
            )
        )

    if classification_source == "unavailable":
        warnings.append(
            QuantIssue(
                code="QUANT_INDUSTRY_CLASSIFICATION_UNAVAILABLE",
                severity="warning",
                message="industry classification is unavailable",
            )
        )

    if ic_double_neutral is not None and abs(float(ic_raw) - float(ic_double_neutral)) > 0.02:
        warnings.append(
            QuantIssue(
                code="QUANT_STYLE_INDUSTRY_EXPOSURE_LARGE",
                severity="warning",
                message="raw IC differs materially from double-neutral IC",
                metadata={"ic_raw": ic_raw, "ic_double_neutral": ic_double_neutral},
            )
        )

    return NeutralizedICReport(
        ic_raw=ic_raw,
        ic_industry_neutral=ic_industry_neutral,
        ic_size_neutral=ic_size_neutral,
        ic_double_neutral=ic_double_neutral,
        selected_ic=selected,
        classification_source=classification_source,
        taxonomy=taxonomy,
        as_of=as_of,
        warnings=warnings,
    )
