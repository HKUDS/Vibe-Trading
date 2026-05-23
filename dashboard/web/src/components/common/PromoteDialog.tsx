import { useState } from "react";
import { api, type StrategyManifest, type GateThreshold } from "../../lib/api";
import { cn } from "../../lib/utils";

interface Props {
  manifest: StrategyManifest;
  onClose: () => void;
  onSuccess: () => void;
}

function FailedThresholdList({ thresholds }: { thresholds: GateThreshold[] }) {
  const failed = thresholds.filter((t) => !t.passed);
  if (failed.length === 0) return null;
  return (
    <ul className="space-y-1 text-sm">
      {failed.map((t) => (
        <li
          key={t.name}
          className={cn(
            "flex items-center gap-2 rounded px-2 py-1",
            t.fatal
              ? "bg-red-100 text-red-700 dark:bg-red-950/40 dark:text-red-300"
              : "bg-orange-50 text-orange-700 dark:bg-orange-950/30 dark:text-orange-300",
          )}
        >
          <span>{t.fatal ? "🔴" : "🟠"}</span>
          <span className="font-medium">{t.name}</span>
          <span className="text-xs opacity-70">
            要求 {t.threshold} · 實際 {t.actual ?? "—"}
          </span>
          {t.fatal && (
            <span className="ml-auto text-xs font-bold">硬擋</span>
          )}
        </li>
      ))}
    </ul>
  );
}

export function PromoteDialog({ manifest, onClose, onSuccess }: Props) {
  const gate = manifest.gate;
  const isFatalFail = gate?.fatal_fail ?? false;
  const isNonFatalFail = gate !== null && !gate.overall_pass && !isFatalFail;
  const isPass = gate?.overall_pass ?? false;

  const [acknowledged, setAcknowledged] = useState(false);
  const [overrideReason, setOverrideReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [apiError, setApiError] = useState<string | null>(null);

  async function handlePromote() {
    setSubmitting(true);
    setApiError(null);
    try {
      const body = isNonFatalFail ? { override_reason: overrideReason } : {};
      const res = await api.promote(manifest.strategy_id, body);
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error((data as { detail?: string }).detail ?? `${res.status} ${res.statusText}`);
      }
      onSuccess();
    } catch (e) {
      setApiError(e instanceof Error ? e.message : String(e));
    } finally {
      setSubmitting(false);
    }
  }

  const canSubmit =
    !isFatalFail &&
    !submitting &&
    (isPass || (isNonFatalFail && acknowledged && overrideReason.trim().length > 0));

  return (
    /* Backdrop */
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/50"
      onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}
    >
      <div className="w-full max-w-lg rounded-xl border bg-card shadow-2xl mx-4">
        {/* Header */}
        <div className="flex items-center justify-between border-b px-5 py-4">
          <h2 className="text-base font-semibold">
            Promote 策略到 Testnet
          </h2>
          <button
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground transition-colors text-lg leading-none"
          >
            ✕
          </button>
        </div>

        {/* Body */}
        <div className="px-5 py-4 space-y-4">
          <div className="text-sm text-muted-foreground">
            策略：<span className="font-mono font-medium text-foreground">{manifest.strategy_id}</span>
            <span className="ml-2">{manifest.symbol}</span>
          </div>

          {/* Fatal hard block */}
          {isFatalFail && (
            <div className="rounded-lg border border-red-400 bg-red-50 dark:bg-red-950/30 dark:border-red-700 p-4 space-y-3">
              <p className="text-sm font-semibold text-red-700 dark:text-red-400">
                🔴 致命門檻未過 — 無法 Promote
              </p>
              <p className="text-xs text-red-600 dark:text-red-400">
                下列致命項失敗，系統硬擋，不允許任何 override。必須修正策略再重新跑 pipeline。
              </p>
              {gate && <FailedThresholdList thresholds={gate.thresholds} />}
            </div>
          )}

          {/* Soft block — non-fatal fail */}
          {isNonFatalFail && gate && (
            <div className="space-y-3">
              <div className="rounded-lg border border-orange-300 bg-orange-50 dark:bg-orange-950/30 dark:border-orange-700 p-3">
                <p className="text-sm font-semibold text-orange-700 dark:text-orange-300 mb-2">
                  🟠 部分門檻未過 — 可 Override（軟擋）
                </p>
                <FailedThresholdList thresholds={gate.thresholds} />
              </div>

              <label className="flex items-start gap-2 cursor-pointer text-sm">
                <input
                  type="checkbox"
                  checked={acknowledged}
                  onChange={(e) => setAcknowledged(e.target.checked)}
                  className="mt-0.5 accent-primary"
                />
                <span>
                  我知道上列門檻未通過，仍決定 Promote，並對此決策負責
                </span>
              </label>

              <div className="space-y-1">
                <label className="text-xs font-medium text-muted-foreground">
                  Override 理由 <span className="text-red-500">*</span>
                </label>
                <textarea
                  value={overrideReason}
                  onChange={(e) => setOverrideReason(e.target.value)}
                  placeholder="說明為何仍決定 Promote（例如：此策略用於特定 regime，門檻設計不符合情境）"
                  rows={3}
                  disabled={!acknowledged}
                  className={cn(
                    "w-full rounded-md border bg-background px-3 py-2 text-sm resize-none focus:outline-none focus:ring-2 focus:ring-primary",
                    !acknowledged && "opacity-40 cursor-not-allowed",
                  )}
                />
              </div>
            </div>
          )}

          {/* All passed — simple confirm */}
          {isPass && (
            <div className="rounded-lg border border-emerald-300 bg-emerald-50 dark:bg-emerald-950/30 dark:border-emerald-700 p-3 text-sm text-emerald-700 dark:text-emerald-300">
              ✓ 所有門檻通過，可直接 Promote
            </div>
          )}

          {/* No gate data */}
          {gate === null && (
            <div className="rounded-md border bg-muted p-3 text-sm text-muted-foreground">
              尚無 Gate 評估資料，將直接 Promote（未通過驗證）
            </div>
          )}

          {/* API error */}
          {apiError && (
            <div className="rounded-md border border-red-300 bg-red-50 dark:bg-red-950/30 p-3 text-sm text-red-700 dark:text-red-400">
              錯誤：{apiError}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-3 border-t px-5 py-4">
          <button
            onClick={onClose}
            className="rounded-md px-4 py-2 text-sm text-muted-foreground hover:bg-muted transition-colors"
          >
            取消
          </button>
          {!isFatalFail && (
            <button
              onClick={handlePromote}
              disabled={!canSubmit}
              className={cn(
                "rounded-md px-4 py-2 text-sm font-medium transition-colors",
                canSubmit
                  ? "bg-primary text-primary-foreground hover:bg-primary/90"
                  : "bg-muted text-muted-foreground cursor-not-allowed",
              )}
            >
              {submitting ? "Promoting…" : "確認 Promote"}
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
