import { memo } from "react";
import { useTranslation } from "react-i18next";
import { Clock3, Loader2, X } from "lucide-react";
import type { QueuedInput } from "@/lib/threadItems";
import type { AgentMessageMeta } from "@/stores/agent";

interface Props {
  inputs: readonly QueuedInput[];
  /** Display form of a message (strips prompt envelopes). */
  display: (content: string) => { content: string; meta?: AgentMessageMeta };
  onDiscard: (inputId: string) => void;
}

/**
 * Messages sent while a turn runs. Each waits here until the conversation
 * takes it (after the current step, or as the next turn), then appears in the
 * transcript in its place.
 */
export const QueuedInputs = memo(function QueuedInputs({ inputs, display, onDiscard }: Props) {
  const { t } = useTranslation();
  return (
    <ul aria-label={t("agent.queue.label" as never)} className="space-y-2">
      {inputs.map((input) => {
        const delivering = input.status === "delivering";
        return (
          <li key={input.inputId} data-queued-input={input.inputId} className="flex justify-end">
            <div className="max-w-[72%] rounded-[18px] border border-dashed border-border/70 bg-muted/40 px-4 py-2.5 text-[15px] leading-relaxed text-muted-foreground">
              <div className="mb-1 flex items-center justify-end gap-1.5 text-[11px]">
                {delivering
                  ? <Loader2 className="h-3 w-3 animate-spin" aria-hidden="true" />
                  : <Clock3 className="h-3 w-3" aria-hidden="true" />}
                <span>{t(delivering ? "agent.queue.delivering" as never : "agent.queue.queued" as never)}</span>
                {!delivering && (
                  <button
                    type="button"
                    onClick={() => onDiscard(input.inputId)}
                    aria-label={t("agent.queue.discard" as never)}
                    title={t("agent.queue.discard" as never)}
                    className="ms-1 rounded-full p-0.5 transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>
              <p dir="auto" className="whitespace-pre-wrap break-words">{display(input.content).content}</p>
            </div>
          </li>
        );
      })}
    </ul>
  );
});
