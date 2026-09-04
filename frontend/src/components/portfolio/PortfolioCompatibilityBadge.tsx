import { useTranslation } from "react-i18next";
import type { PortfolioConnectorCompatibility } from "@/lib/api";

const STYLE = {
  native: "bg-positive/10 text-positive",
  contract_tested: "bg-primary/10 text-primary",
  experimental: "bg-warning/10 text-warning",
} as const;

/** Explain how far a connector has been verified for portfolio aggregation. */
export function PortfolioCompatibilityBadge({
  compatibility,
}: {
  compatibility?: PortfolioConnectorCompatibility;
}) {
  const { t } = useTranslation();
  if (!compatibility) return null;
  const label = compatibility.level === "native"
    ? t("portfolio.compatibility.native")
    : compatibility.level === "contract_tested"
      ? t("portfolio.compatibility.contractTested")
      : t("portfolio.compatibility.experimental");
  return <span
    className={`inline-flex rounded-full px-2 py-1 text-xs ${STYLE[compatibility.level]}`}
    title={compatibility.note}
  >
    {label}
  </span>;
}
