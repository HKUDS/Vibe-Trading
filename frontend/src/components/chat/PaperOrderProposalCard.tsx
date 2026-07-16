// >>> ICICI PAPER ORDER APPROVAL CARD >>>
import i18n from "@/i18n";
import { memo, useCallback, useMemo, useState } from "react";
import {
  Ban,
  CheckCircle2,
  Clock3,
  Loader2,
  ShieldCheck,
  TriangleAlert,
} from "lucide-react";
import { toast } from "sonner";
import { api, type PaperOrderProposal } from "@/lib/api";
import { AgentAvatar } from "./AgentAvatar";
import { ConfirmDialog } from "@/components/common/ConfirmDialog";

interface Props {
  proposal: PaperOrderProposal;
  onChange?: (proposal: PaperOrderProposal) => void;
}

type BusyAction = "approve" | "reject" | null;

function formatInr(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency: "INR",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

function stateLabel(state: PaperOrderProposal["state"]): string {
  switch (state) {
    case "pending":
      return i18n.t("paperOrder.pending");
    case "processing":
      return i18n.t("paperOrder.processing");
    case "approved":
      return i18n.t("paperOrder.approved");
    case "rejected":
      return i18n.t("paperOrder.rejected");
    case "rejected_by_risk":
      return i18n.t("paperOrder.rejectedByRisk");
    case "expired":
      return i18n.t("paperOrder.expired");
    case "failed":
      return i18n.t("paperOrder.failed");
  }
}

function stateStyle(state: PaperOrderProposal["state"]): {
  icon: typeof ShieldCheck;
  className: string;
} {
  switch (state) {
    case "approved":
      return {
        icon: CheckCircle2,
        className: "border-emerald-500/40 bg-emerald-500/5 text-emerald-600 dark:text-emerald-400",
      };
    case "rejected":
      return {
        icon: Ban,
        className: "border-muted-foreground/30 bg-muted/20 text-muted-foreground",
      };
    case "rejected_by_risk":
    case "failed":
      return {
        icon: TriangleAlert,
        className: "border-destructive/40 bg-destructive/5 text-destructive",
      };
    case "expired":
      return {
        icon: Clock3,
        className: "border-amber-500/40 bg-amber-500/5 text-amber-600 dark:text-amber-400",
      };
    case "processing":
    case "pending":
    default:
      return {
        icon: ShieldCheck,
        className: "border-primary/30 bg-primary/5 text-primary",
      };
  }
}

function expiryLabel(expiresAt: string): string {
  const expires = new Date(expiresAt);
  if (Number.isNaN(expires.getTime())) return "—";
  return expires.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export const PaperOrderProposalCard = memo(function PaperOrderProposalCard({
  proposal,
  onChange,
}: Props) {
  const [current, setCurrent] = useState(proposal);
  const [busy, setBusy] = useState<BusyAction>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

  const pending = current.state === "pending";
  const expiry = useMemo(() => expiryLabel(current.expires_at), [current.expires_at]);
  const { icon: StateIcon, className: stateClassName } = stateStyle(current.state);

  const apply = useCallback(
    (next: PaperOrderProposal) => {
      setCurrent(next);
      onChange?.(next);
      return next;
    },
    [onChange],
  );

  const reject = useCallback(async () => {
    if (!pending || busy != null) return;
    setBusy("reject");
    try {
      const next = apply(
        await api.rejectPaperOrderProposal(current.session_id, current.proposal_id),
      );
      if (next.state === "rejected") {
        toast.success(i18n.t("paperOrder.rejectedToast"));
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : i18n.t("paperOrder.actionFailed"));
    } finally {
      setBusy(null);
    }
  }, [apply, busy, current.proposal_id, current.session_id, pending]);

  const approve = useCallback(async () => {
    if (!pending || busy != null) return;
    setConfirmOpen(false);
    setBusy("approve");
    try {
      const next = apply(
        await api.approvePaperOrderProposal(current.session_id, current.proposal_id),
      );
      if (next.state === "approved") {
        toast.success(i18n.t("paperOrder.approvedToast"));
      } else if (next.state === "rejected_by_risk") {
        toast.warning(i18n.t("paperOrder.riskRejectedToast"));
      } else if (next.state === "expired") {
        toast.warning(i18n.t("paperOrder.expiredToast"));
      }
    } catch (error) {
      toast.error(error instanceof Error ? error.message : i18n.t("paperOrder.actionFailed"));
    } finally {
      setBusy(null);
    }
  }, [apply, busy, current.proposal_id, current.session_id, pending]);

  return (
    <div className="flex gap-3">
      <AgentAvatar />
      <div className="min-w-0 flex-1 space-y-3 rounded-2xl border border-primary/20 bg-background/95 p-4 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-2">
          <div className="flex min-w-0 items-start gap-2">
            <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-primary" />
            <div className="min-w-0">
              <p className="text-sm font-semibold text-foreground">
                {i18n.t("paperOrder.title")}
              </p>
              <p className="text-[11px] text-muted-foreground">
                {i18n.t("paperOrder.paperOnly")} · {i18n.t("paperOrder.immutable")}
              </p>
            </div>
          </div>
          <span className={[
            "inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium",
            stateClassName,
          ].join(" ")}>
            {current.state === "processing" ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <StateIcon className="h-3 w-3" />
            )}
            {stateLabel(current.state)}
          </span>
        </div>

        <dl className="grid grid-cols-2 gap-x-4 gap-y-2 rounded-xl border bg-muted/20 p-3 text-xs sm:grid-cols-3">
          <div>
            <dt className="text-muted-foreground">{i18n.t("paperOrder.symbol")}</dt>
            <dd className="font-mono font-semibold text-foreground">{current.symbol}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("paperOrder.side")}</dt>
            <dd className="font-semibold uppercase text-foreground">{current.side}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("paperOrder.quantity")}</dt>
            <dd className="font-mono font-semibold text-foreground">{current.quantity}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("paperOrder.limitPrice")}</dt>
            <dd className="font-mono font-semibold text-foreground">{formatInr(current.limit_price)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("paperOrder.referencePrice")}</dt>
            <dd className="font-mono font-semibold text-foreground">{formatInr(current.reference_price)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("paperOrder.timeInForce")}</dt>
            <dd className="font-mono font-semibold uppercase text-foreground">{current.time_in_force}</dd>
          </div>
        </dl>

        <div className="flex flex-wrap items-center justify-between gap-2 text-[11px] text-muted-foreground">
          <span className="font-mono">ID: {current.proposal_id}</span>
          <span className="inline-flex items-center gap-1">
            <Clock3 className="h-3 w-3" />
            {i18n.t("paperOrder.expires")}: {expiry}
          </span>
        </div>

        {current.error && (
          <p className="rounded-lg border border-destructive/30 bg-destructive/5 px-3 py-2 text-xs text-destructive">
            {current.error}
          </p>
        )}

        {pending && (
          <div className="flex justify-end gap-2 border-t border-border/60 pt-3">
            <button
              type="button"
              onClick={reject}
              disabled={busy != null}
              className="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
            >
              {busy === "reject" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <Ban className="h-3.5 w-3.5" />
              )}
              {busy === "reject" ? i18n.t("paperOrder.rejecting") : i18n.t("paperOrder.reject")}
            </button>
            <button
              type="button"
              onClick={() => setConfirmOpen(true)}
              disabled={busy != null}
              className="inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground transition-opacity hover:opacity-90 disabled:opacity-40"
            >
              {busy === "approve" ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <ShieldCheck className="h-3.5 w-3.5" />
              )}
              {busy === "approve" ? i18n.t("paperOrder.approving") : i18n.t("paperOrder.approve")}
            </button>
          </div>
        )}
      </div>

      <ConfirmDialog
        open={confirmOpen}
        title={i18n.t("paperOrder.confirmTitle")}
        description={i18n.t("paperOrder.confirmDescription")}
        confirmLabel={i18n.t("paperOrder.confirmButton")}
        cancelLabel={i18n.t("paperOrder.cancel")}
        tone="destructive"
        onCancel={() => setConfirmOpen(false)}
        onConfirm={approve}
      >
        <dl className="grid grid-cols-2 gap-x-3 gap-y-1.5 rounded-lg border bg-muted/20 p-2.5 text-[11px]">
          <div>
            <dt className="text-muted-foreground">{i18n.t("paperOrder.symbol")}</dt>
            <dd className="font-mono font-semibold text-foreground">{current.symbol}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("paperOrder.side")}</dt>
            <dd className="font-semibold uppercase text-foreground">{current.side}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("paperOrder.quantity")}</dt>
            <dd className="font-mono font-semibold text-foreground">{current.quantity}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("paperOrder.limitPrice")}</dt>
            <dd className="font-mono font-semibold text-foreground">{formatInr(current.limit_price)}</dd>
          </div>
        </dl>
      </ConfirmDialog>
    </div>
  );
});
// <<< ICICI PAPER ORDER APPROVAL CARD >>>
