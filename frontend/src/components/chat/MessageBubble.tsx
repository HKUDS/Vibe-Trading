import i18n from '@/i18n';
import { Component, memo, useState, useCallback, type ReactNode } from "react";
import { XCircle, RefreshCw, Copy, Check, Paperclip, Users, Target, Clock3 } from "lucide-react";
import ReactMarkdown, { type Options as ReactMarkdownOptions } from "react-markdown";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import rehypeHighlight from "rehype-highlight";
import rehypeKatex from "rehype-katex";
import "katex/dist/katex.min.css";
import { toast } from "sonner";
import { normalizeMathDelimiters } from "@/lib/markdown";
import type { AgentMessage } from "@/types/agent";
import type { StoredAgentMessage } from "@/stores/agent";
import { AgentAvatar } from "./AgentAvatar";
import { RunCompleteCard } from "./RunCompleteCard";

// singleDollarTextMath off: dollar amounts ("$150 to $120") must never parse as
// formulas; LLM \(...\)/\[...\] delimiters are normalized to $$ before render.
const remarkPlugins: ReactMarkdownOptions["remarkPlugins"] = [
  remarkGfm,
  [remarkMath, { singleDollarTextMath: false }],
];
const rehypePlugins: ReactMarkdownOptions["rehypePlugins"] = [rehypeHighlight, rehypeKatex];
const markdownComponents: ReactMarkdownOptions["components"] = {
  table: ({ node, ...props }) => {
    void node;
    return (
      <div className="overflow-x-auto">
        <table {...props} />
      </div>
    );
  },
  a: ({ node, ...props }) => {
    void node;
    return <a {...props} target="_blank" rel="noopener noreferrer" />;
  },
};
const proseClassName = "prose prose-sm dark:prose-invert max-w-none text-[15px] leading-relaxed prose-p:font-serif prose-p:text-[15.5px] prose-p:leading-[1.75] prose-li:font-serif prose-li:text-[15.5px] prose-li:leading-[1.75] prose-headings:font-sans prose-table:font-sans prose-code:font-mono prose-blockquote:font-sans [&_blockquote_p]:font-sans prose-table:border prose-table:border-border/50 prose-th:bg-muted/30 prose-th:px-3 prose-th:py-1.5 prose-td:px-3 prose-td:py-1.5 prose-th:text-left prose-th:text-xs prose-th:font-medium prose-td:text-xs prose-hr:hidden";

interface MarkdownErrorBoundaryProps {
  content: string;
  children: ReactNode;
}

interface MarkdownErrorBoundaryState {
  failed: boolean;
}

class MarkdownErrorBoundary extends Component<MarkdownErrorBoundaryProps, MarkdownErrorBoundaryState> {
  state: MarkdownErrorBoundaryState = { failed: false };

  static getDerivedStateFromError(): MarkdownErrorBoundaryState {
    return { failed: true };
  }

  componentDidUpdate(previous: MarkdownErrorBoundaryProps) {
    if (this.state.failed && previous.content !== this.props.content) {
      this.setState({ failed: false });
    }
  }

  render() {
    if (this.state.failed) {
      return <span className="whitespace-pre-wrap">{this.props.content}</span>;
    }
    return this.props.children;
  }
}

interface MarkdownContentProps {
  content: string;
  streaming?: boolean;
  showCursor?: boolean;
}

export const MarkdownContent = memo(function MarkdownContent({
  content,
  streaming = false,
  showCursor = false,
}: MarkdownContentProps) {
  let normalized = content;
  try {
    normalized = normalizeMathDelimiters(content);
  } catch {
    normalized = content;
  }

  return (
    <div className={proseClassName}>
      <MarkdownErrorBoundary content={content}>
        <ReactMarkdown
          remarkPlugins={remarkPlugins}
          rehypePlugins={streaming ? [] : rehypePlugins}
          components={markdownComponents}
        >
          {normalized}
        </ReactMarkdown>
      </MarkdownErrorBoundary>
      {showCursor && (
        <span className="inline-block w-0.5 h-4 bg-primary ml-0.5 animate-pulse align-middle" />
      )}
    </div>
  );
});

async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard?.writeText) {
      await navigator.clipboard.writeText(text);
      return true;
    }
  } catch {
    // Fall through to the selection-based compatibility path.
  }

  const textarea = document.createElement("textarea");
  textarea.value = text;
  textarea.setAttribute("readonly", "");
  textarea.style.position = "fixed";
  textarea.style.opacity = "0";
  document.body.appendChild(textarea);
  textarea.select();
  let copied = false;
  try {
    copied = document.execCommand("copy");
  } catch {
    copied = false;
  } finally {
    textarea.remove();
  }
  return copied;
}

function CopyButton({ text }: { text: string }) {
  const [copied, setCopied] = useState(false);
  const handleCopy = useCallback(async () => {
    if (await copyText(text)) {
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
      return;
    }
    toast.error(i18n.t("messageBubble.copyFailed"));
  }, [text]);
  const label = copied ? i18n.t("messageBubble.copied") : i18n.t("messageBubble.copy");

  return (
    <button
      onClick={handleCopy}
      className="absolute top-2 right-2 p-1.5 rounded-md bg-muted/80 hover:bg-muted text-muted-foreground hover:text-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100 transition-opacity"
      aria-label={label}
      title={label}
    >
      {copied ? <Check className="h-3.5 w-3.5 text-success" /> : <Copy className="h-3.5 w-3.5" />}
      {copied && (
        <span className="sr-only" role="status">
          {i18n.t("messageBubble.copied")}
        </span>
      )}
    </button>
  );
}

function getRetryHint(content: string): string {
  const lower = content.toLowerCase();
  if (lower.includes("timeout") || lower.includes("timed out")) {
    return i18n.t("messageBubble.timeoutHint");
  }
  if (lower.includes("api") || lower.includes("rate limit") || lower.includes("429") || lower.includes("500") || lower.includes("502") || lower.includes("503")) {
    return i18n.t("messageBubble.apiFailedHint");
  }
  return i18n.t("messageBubble.executionFailedHint");
}

interface Props {
  msg: StoredAgentMessage;
  onRetry?: (msg: AgentMessage) => void;
}

function formatElapsed(elapsedMs: number): string {
  if (elapsedMs < 1000) return `${Math.max(1, Math.round(elapsedMs))} ms`;
  const seconds = elapsedMs / 1000;
  if (seconds < 60) return `${seconds < 10 ? seconds.toFixed(1) : Math.round(seconds)} s`;
  const minutes = Math.floor(seconds / 60);
  return `${minutes}m ${Math.round(seconds % 60)}s`;
}

export const MessageBubble = memo(function MessageBubble({ msg, onRetry }: Props) {
  if (msg.type === "user") {
    const meta = msg.meta;
    return (
      <div className="flex justify-end group">
        <div className="max-w-[72%] max-h-[40vh] overflow-y-auto break-words rounded-[18px] bg-muted px-4 py-3 text-[15px] text-foreground leading-relaxed whitespace-pre-wrap">
          {meta && (meta.attachment || meta.swarmMode || meta.goalMode) && (
            <div className="mb-1.5 flex flex-wrap justify-end gap-1.5 text-[10px] leading-none text-muted-foreground">
              {meta.attachment && (
                <span
                  className="inline-flex max-w-full items-center gap-1 rounded-full bg-background/60 px-2 py-1 text-muted-foreground"
                  title={i18n.t("agent.attachmentChip" as never)}
                >
                  <Paperclip className="h-3 w-3 shrink-0" />
                  <span className="sr-only">{i18n.t("agent.attachmentChip" as never)}: </span>
                  <span className="truncate">{meta.attachment.filename}</span>
                </span>
              )}
              {meta.swarmMode && (
                <span className="inline-flex items-center gap-1 rounded-full bg-background/60 px-2 py-1 text-muted-foreground">
                  <Users className="h-3 w-3" />
                  {i18n.t("agent.swarmModeChip" as never)}
                </span>
              )}
              {meta.goalMode && (
                <span className="inline-flex items-center gap-1 rounded-full bg-background/60 px-2 py-1 text-muted-foreground">
                  <Target className="h-3 w-3" />
                  {i18n.t("agent.goalModeChip" as never)}
                </span>
              )}
            </div>
          )}
          {msg.content}
        </div>
      </div>
    );
  }

  if (msg.type === "answer") {
    return (
      <div className="flex gap-3 group relative">
        <AgentAvatar />
        <div className="flex-1 min-w-0 space-y-1.5">
          <CopyButton text={msg.content} />
          <MarkdownContent content={msg.content} />
          {msg.elapsed_ms != null && (
            <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground/55">
              <span className="inline-flex items-center gap-1 tabular-nums" title={i18n.t("messageBubble.elapsedTime")}>
                <Clock3 className="h-3 w-3" aria-hidden="true" />
                {formatElapsed(msg.elapsed_ms)}
              </span>
            </div>
          )}
        </div>
      </div>
    );
  }

  if (msg.type === "run_complete" && msg.runId) {
    return <RunCompleteCard msg={msg} />;
  }

  if (msg.type === "error") {
    const hint = getRetryHint(msg.content);
    return (
      <div className="flex gap-3">
        <AgentAvatar />
        <div className="space-y-2">
          <div className="flex items-start gap-2 rounded-xl border border-danger/30 bg-danger/5 px-4 py-3">
            <XCircle className="h-4 w-4 text-danger shrink-0 mt-0.5" />
            <p className="text-sm text-danger leading-relaxed">{msg.content}</p>
          </div>
          {onRetry && (
            <div className="space-y-1.5">
              <p className="text-xs leading-relaxed text-muted-foreground">{hint}</p>
              <button
                onClick={() => onRetry(msg)}
                className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-xs text-muted-foreground hover:text-foreground hover:bg-muted/80 border border-transparent hover:border-border transition-all"
                title={i18n.t("messageBubble.retry" as never)}
              >
                <RefreshCw className="h-3 w-3" />
                <span>{i18n.t("messageBubble.retry" as never)}</span>
              </button>
            </div>
          )}
        </div>
      </div>
    );
  }

  // Fallback: show content for any unhandled message type
  if (msg.content) {
    return (
      <div className="flex gap-3">
        <AgentAvatar />
        <p className="text-sm text-muted-foreground leading-relaxed">{msg.content}</p>
      </div>
    );
  }

  return null;
});
