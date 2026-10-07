import { memo, useState } from "react";
import { CalendarClock, Check, X } from "lucide-react";

import i18n from "@/i18n";
import { api, type ScheduledResearchProposal } from "@/lib/api";

interface Props {
  proposal: ScheduledResearchProposal;
}

function formatTime(value: number | null | undefined): string {
  if (!value) return i18n.t("scheduled.proposalNoEnd");
  return new Intl.DateTimeFormat(undefined, {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(new Date(value));
}

export const ScheduledResearchProposalCard = memo(function ScheduledResearchProposalCard({
  proposal,
}: Props) {
  const [status, setStatus] = useState(proposal.status);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const job = proposal.job;
  const isCreate = proposal.operation === "create";

  async function decide(commit: boolean) {
    setBusy(true);
    setError(null);
    try {
      const result = commit
        ? await api.commitScheduledResearchProposal(proposal.proposal_id)
        : await api.discardScheduledResearchProposal(proposal.proposal_id);
      setStatus(result.status);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  if (status !== "pending") {
    return (
      <div className="mx-auto flex max-w-2xl items-center gap-2 rounded-xl border border-border/60 bg-muted/35 px-4 py-3 text-sm">
        <CalendarClock className="h-4 w-4 text-orange-500" />
        <span className="font-medium">{job.title}</span>
        <span className="text-muted-foreground">
          {status === "committed"
            ? i18n.t("scheduled.proposalConfirmed")
            : status === "discarded"
              ? i18n.t("scheduled.proposalDiscarded")
              : i18n.t("scheduled.proposalExpired")}
        </span>
      </div>
    );
  }

  return (
    <section className="mx-auto max-w-2xl rounded-2xl border border-orange-500/25 bg-card p-5 shadow-sm">
      <div className="flex items-start gap-3">
        <div className="rounded-xl bg-orange-500/10 p-2 text-orange-500">
          <CalendarClock className="h-5 w-5" />
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-xs font-semibold uppercase tracking-wide text-orange-500">
            {i18n.t(
              isCreate ? "scheduled.proposalCreateTitle" : "scheduled.proposalCancelTitle",
            )}
          </p>
          <h3 className="mt-1 font-semibold text-foreground">{job.title}</h3>
        </div>
      </div>

      {isCreate && (
        <dl className="mt-4 grid gap-2 rounded-xl bg-muted/40 p-3 text-sm sm:grid-cols-2">
          <div>
            <dt className="text-muted-foreground">{i18n.t("scheduled.proposalCadence")}</dt>
            <dd>{job.schedule.expression}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("scheduled.proposalTimezone")}</dt>
            <dd>{job.schedule.timezone || "UTC"}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("scheduled.proposalEndAt")}</dt>
            <dd>{formatTime(job.schedule.end_at)}</dd>
          </div>
          <div>
            <dt className="text-muted-foreground">{i18n.t("scheduled.proposalDelivery")}</dt>
            <dd>{job.delivery.target_label || i18n.t("scheduled.proposalInApp")}</dd>
          </div>
          {job.delivery.channel === "email" && (
            <div>
              <dt className="text-muted-foreground">{i18n.t("scheduled.deliveryFormatLabel")}</dt>
              <dd>{i18n.t(job.delivery.format === "html"
                ? "scheduled.deliveryFormatHtml"
                : job.delivery.format === "pdf"
                  ? "scheduled.deliveryFormatPdf"
                  : "scheduled.deliveryFormatDefault")}</dd>
            </div>
          )}
        </dl>
      )}

      {error && <p className="mt-3 text-sm text-destructive">{error}</p>}
      <div className="mt-4 flex justify-end gap-2">
        <button
          type="button"
          disabled={busy}
          onClick={() => void decide(false)}
          className="inline-flex items-center rounded-md border px-3 py-1.5 text-sm transition hover:bg-muted disabled:opacity-50"
        >
          <X className="mr-1 h-4 w-4" /> {i18n.t("scheduled.proposalDiscard")}
        </button>
        <button
          type="button"
          disabled={busy}
          onClick={() => void decide(true)}
          className="inline-flex items-center rounded-md bg-primary px-3 py-1.5 text-sm text-primary-foreground transition hover:opacity-90 disabled:opacity-50"
        >
          <Check className="mr-1 h-4 w-4" />{" "}
          {i18n.t(
            isCreate
              ? "scheduled.proposalConfirmCreate"
              : "scheduled.proposalConfirmCancel",
          )}
        </button>
      </div>
    </section>
  );
});
