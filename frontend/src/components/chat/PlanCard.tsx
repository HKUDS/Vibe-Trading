import type { FC } from "react";
export const PlanCard: FC<{ steps: Array<{ step: string; status: string }> }> = ({ steps }) => (
  <div className="rounded-lg border border-amber-200 bg-amber-50/60 p-3 text-sm">
    {steps.map((step, index) => <div key={`${index}-${step.step}`} className="flex gap-2 py-1"><span>{step.status === "completed" ? "✓" : step.status === "in_progress" ? "•" : "○"}</span><span>{step.step}</span></div>)}
  </div>
);
