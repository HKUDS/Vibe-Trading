import { memo, useCallback, useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Check, ChevronDown, Pencil, Play, Target, X } from "lucide-react";
import { toast } from "sonner";
import { api, type GoalSnapshot } from "@/lib/api";

function isCriterionStatusMet(status: string): boolean {
  return !["", "pending", "open", "unsatisfied"].includes(status.toLowerCase());
}

function criterionEvidenceCount(snapshot: GoalSnapshot, criterionId: string): number {
  return snapshot.evidence.filter((item) => item.criterion_id === criterionId).length;
}

function criterionCovered(snapshot: GoalSnapshot, criterion: GoalSnapshot["criteria"][number]): boolean {
  return isCriterionStatusMet(criterion.status) || criterionEvidenceCount(snapshot, criterion.criterion_id) > 0;
}

function getGoalProgress(snapshot: GoalSnapshot): {
  met: number;
  total: number;
  label: string;
  metLabel: string;
  evidenceTotal: number;
} {
  const total = snapshot.criteria.length;
  const met = snapshot.criteria.filter((item) => criterionCovered(snapshot, item)).length;
  const evidenceTotal = snapshot.evidence_count;
  return {
    met,
    total,
    label: total > 0 ? `${met}/${total}` : "",
    metLabel: total > 0 ? `${met}/${total} met` : "",
    evidenceTotal,
  };
}

function statusLabel(status: string): string {
  return status.replace(/_/g, " ");
}

function criterionIndexLabel(index: number): string {
  return String(index + 1);
}

function latestGoalEvidence(snapshot: GoalSnapshot) {
  return [...snapshot.evidence]
    .sort((a, b) => new Date(b.created_at).getTime() - new Date(a.created_at).getTime())
    .slice(0, 2);
}

interface Props {
  snapshot: GoalSnapshot;
  sessionId: string | null;
  streaming: boolean;
  openRequest: number;
  onSnapshotChange: (snapshot: GoalSnapshot | null) => void;
  onContinue: () => void;
}

export const GoalPanel = memo(function GoalPanel({
  snapshot,
  sessionId,
  streaming,
  openRequest,
  onSnapshotChange,
  onContinue,
}: Props) {
  const { t } = useTranslation();
  const [detailsOpen, setDetailsOpen] = useState(openRequest > 0);
  const [editActive, setEditActive] = useState(false);
  const [editValue, setEditValue] = useState("");
  const goalProgress = useMemo(() => getGoalProgress(snapshot), [snapshot]);

  useEffect(() => {
    if (openRequest > 0) setDetailsOpen(true);
  }, [openRequest]);

  const handleCancel = useCallback(async () => {
    if (!sessionId) return;
    try {
      await api.updateGoalStatus(sessionId, {
        goal_id: snapshot.goal.goal_id,
        expected_goal_id: snapshot.goal.goal_id,
        status: "cancelled",
        recap: "Cancelled from Web UI.",
      });
      onSnapshotChange(null);
      setDetailsOpen(false);
      toast.success(t("agent.researchGoalCancelled"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("agent.failedToCancelGoal"));
    }
  }, [onSnapshotChange, sessionId, snapshot, t]);

  const handleStartEdit = useCallback(() => {
    setEditValue(snapshot.goal.objective);
    setEditActive(true);
  }, [snapshot]);

  const handleSaveEdit = useCallback(async () => {
    const objective = editValue.trim();
    if (!sessionId || !objective) return;
    try {
      const response = await api.updateGoal(sessionId, {
        goal_id: snapshot.goal.goal_id,
        expected_goal_id: snapshot.goal.goal_id,
        objective,
      });
      onSnapshotChange(response.snapshot);
      setEditActive(false);
      toast.success(t("agent.researchGoalUpdated"));
    } catch (error) {
      toast.error(error instanceof Error ? error.message : t("agent.failedToUpdateGoal"));
    }
  }, [editValue, onSnapshotChange, sessionId, snapshot, t]);

  return (
    <div className="grid gap-2">
      <button
        type="button"
        onClick={() => setDetailsOpen((open) => !open)}
        className="inline-flex max-w-full items-center gap-1.5 justify-self-start rounded-lg bg-primary/10 px-2.5 py-1 text-left text-xs font-medium text-primary transition-colors hover:bg-primary/15"
        title={snapshot.goal.objective}
        aria-label={t("agent.activeResearchGoal")}
        aria-expanded={detailsOpen}
      >
        <Target className="h-3 w-3 shrink-0" />
        <span className="shrink-0">{t("agent.goal")}</span>
        <span className="truncate text-muted-foreground">
          {snapshot.goal.ui_summary || snapshot.goal.objective}
        </span>
        {goalProgress.metLabel && (
          <span className="shrink-0 font-mono text-[11px] text-emerald-600 dark:text-emerald-400">
            {goalProgress.metLabel}
          </span>
        )}
        {goalProgress.evidenceTotal > 0 && (
          <span
            className="shrink-0 rounded bg-background px-1 font-mono text-[10px] text-primary"
            title={t("agent.evidenceCollectedTitle")}
          >
            {t("agent.evidenceCount", { count: goalProgress.evidenceTotal })}
          </span>
        )}
        <ChevronDown
          className={[
            "h-3 w-3 shrink-0 transition-transform",
            detailsOpen ? "rotate-180" : "",
          ].join(" ")}
          aria-hidden="true"
        />
      </button>
      {detailsOpen && (
        <div className="grid gap-3 rounded-xl border border-primary/20 bg-background/95 p-3 text-xs shadow-sm">
          {editActive ? (
            <div className="grid gap-2">
              <textarea
                value={editValue}
                onChange={(event) => setEditValue(event.target.value)}
                rows={3}
                aria-label={t("agent.editGoalObjectiveLabel")}
                className="w-full rounded-lg border bg-background px-3 py-2 text-xs leading-relaxed text-foreground outline-none focus:ring-2 focus:ring-primary/30"
              />
              <div className="flex justify-end gap-2">
                <button
                  type="button"
                  onClick={() => setEditActive(false)}
                  className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground"
                >
                  <X className="h-3 w-3" />
                  {t("agent.cancel")}
                </button>
                <button
                  type="button"
                  onClick={handleSaveEdit}
                  disabled={!editValue.trim()}
                  className="inline-flex items-center gap-1 rounded-lg bg-primary px-2 py-1 text-[11px] font-medium text-primary-foreground transition-opacity disabled:opacity-40"
                >
                  <Check className="h-3 w-3" />
                  {t("agent.save")}
                </button>
              </div>
            </div>
          ) : (
            <div className="rounded-lg border bg-muted/20 px-3 py-2 text-[11px] leading-relaxed text-muted-foreground">
              {snapshot.goal.objective}
            </div>
          )}
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded-lg border bg-muted/20 p-2.5">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {t("agent.criteria")}
              </div>
              <div className="mt-1 font-mono text-base font-semibold text-foreground">
                {goalProgress.label || "0/0"}
              </div>
            </div>
            <div className="rounded-lg border bg-muted/20 p-2.5">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {t("agent.evidence")}
              </div>
              <div className="mt-1 font-mono text-base font-semibold text-foreground">
                {goalProgress.evidenceTotal}
              </div>
            </div>
          </div>
          <div className="grid gap-1.5">
            {snapshot.criteria.map((criterion, index) => {
              const evidenceCount = criterionEvidenceCount(snapshot, criterion.criterion_id);
              const displayStatus = criterionCovered(snapshot, criterion) && !isCriterionStatusMet(criterion.status)
                ? "covered"
                : statusLabel(criterion.status);
              return (
                <div
                  key={criterion.criterion_id}
                  className="grid grid-cols-[1.25rem_minmax(0,1fr)_auto] items-start gap-2 rounded-lg border bg-muted/20 p-2"
                >
                  <span className="flex h-5 w-5 items-center justify-center rounded-full bg-muted text-[10px] text-muted-foreground">
                    {criterionIndexLabel(index)}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate font-medium text-foreground">{criterion.text}</span>
                    <span className="block text-[11px] text-muted-foreground">
                      {displayStatus}
                    </span>
                  </span>
                  <span className="rounded-full border px-1.5 py-0.5 font-mono text-[10px] text-muted-foreground">
                    {evidenceCount} ev
                  </span>
                </div>
              );
            })}
          </div>
          {snapshot.evidence.length > 0 && (
            <div className="grid gap-1.5 border-t pt-2">
              <div className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
                {t("agent.recentEvidence")}
              </div>
              {latestGoalEvidence(snapshot).map((item) => (
                <div key={item.evidence_id} className="rounded-lg bg-muted/20 px-2 py-1.5">
                  <div className="mb-0.5 flex items-center justify-between gap-2 text-[10px] text-muted-foreground">
                    <span className="truncate">{item.source_provider || "evidence"}</span>
                    <span>{statusLabel(item.verification_status)}</span>
                  </div>
                  <div className="line-clamp-2 text-[11px] leading-relaxed text-foreground">
                    {item.text}
                  </div>
                </div>
              ))}
            </div>
          )}
          <div className="flex flex-wrap justify-end gap-2 border-t pt-2">
            <button
              type="button"
              onClick={onContinue}
              disabled={streaming}
              className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
            >
              <Play className="h-3 w-3" />
              {t("agent.continue")}
            </button>
            <button
              type="button"
              onClick={handleStartEdit}
              disabled={editActive}
              className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:text-foreground disabled:opacity-40"
            >
              <Pencil className="h-3 w-3" />
              {t("agent.edit")}
            </button>
            <button
              type="button"
              onClick={handleCancel}
              className="inline-flex items-center gap-1 rounded-lg border px-2 py-1 text-[11px] font-medium text-muted-foreground transition-colors hover:border-destructive/40 hover:text-destructive"
            >
              <X className="h-3 w-3" />
              {t("agent.cancelGoal")}
            </button>
          </div>
        </div>
      )}
    </div>
  );
});
