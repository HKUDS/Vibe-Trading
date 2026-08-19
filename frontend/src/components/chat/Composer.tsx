import {
  forwardRef,
  memo,
  useCallback,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type ChangeEvent,
  type FormEvent,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import {
  Download,
  Landmark,
  Loader2,
  Paperclip,
  Plus,
  Send,
  Square,
  Target,
  Users,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { api } from "@/lib/api";
import type { AgentCapabilities, CapabilityItem, MessageSelection, ToolCapability } from "@/lib/api";
import { filterCapabilities, getSlashContext } from "@/lib/slashCommands";
import type { AgentActivity } from "@/stores/agent";
import {
  LiveRuntimeControl,
  LiveRuntimeStatus,
} from "@/components/chat/LiveRuntimePanel";

const CONNECTOR_CHECK_PROMPT =
  "List my trading connector profiles, show which one is selected, then check that selected connector. If it is not ready, tell me exactly what setup step is missing. Do not place or modify orders.";
const CONNECTOR_PORTFOLIO_PROMPT =
  "Use the selected trading connector profile to summarize my account, positions, concentration, cash, and portfolio risk. Do not place or modify orders.";

const ACCEPTED_FILE_TYPES =
  ".pdf,.docx,.xlsx,.xls,.pptx,.csv,.tsv,.txt,.md,.log,.json,.yaml,.yml,.toml,.html,.xml,.rst,.png,.jpg,.jpeg,.gif,.bmp,.webp,.tiff";

export interface ComposerAttachment {
  filename: string;
  filePath: string;
}

export interface ComposerHandle {
  fill(prompt: string): void;
  focus(): void;
  submit(prompt: string): void;
}

type SlashOption = {
  kind: "category" | "capability" | "command";
  value: string;
  label: string;
  description: string;
  category?: string;
  capability?: CapabilityItem | ToolCapability;
};

interface Props {
  streaming: boolean;
  activityVerb?: AgentActivity["verb"];
  hasCompletedTurn: boolean;
  showExport: boolean;
  canExport: boolean;
  goalComposerActive: boolean;
  swarmPreset: { name: string; title: string } | null;
  panels?: ReactNode;
  capabilities?: AgentCapabilities | null;
  onSubmit: (prompt: string, attachment: ComposerAttachment | null, selection?: MessageSelection) => void;
  onCancel: () => void;
  onExport: () => void;
  onStartGoal: () => void;
  onCancelGoal: () => void;
  onStartSwarm: () => void;
  onCancelSwarm: () => void;
}

export const Composer = memo(forwardRef<ComposerHandle, Props>(function Composer({
  streaming,
  activityVerb,
  hasCompletedTurn,
  showExport,
  canExport,
  goalComposerActive,
  swarmPreset,
  panels,
  onSubmit,
  onCancel,
  onExport,
  onStartGoal,
  onCancelGoal,
  onStartSwarm,
  onCancelSwarm,
  capabilities = null,
}, ref) {
  const { t } = useTranslation();
  const [input, setInput] = useState("");
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const isComposingRef = useRef(false);
  const lastCompositionEndRef = useRef(0);
  const [attachment, setAttachment] = useState<ComposerAttachment | null>(null);
  const [uploading, setUploading] = useState(false);
  const [showUploadMenu, setShowUploadMenu] = useState(false);
  const [selectedSkills, setSelectedSkills] = useState<string[]>([]);
  const [selectedTools, setSelectedTools] = useState<string[]>([]);
  const [slashContext, setSlashContext] = useState<ReturnType<typeof getSlashContext>>(null);
  const [slashIndex, setSlashIndex] = useState(0);
  const slashOptionRefs = useRef<Record<string, HTMLButtonElement | null>>({});
  const uploadMenuRef = useRef<HTMLDivElement>(null);
  const uploadMenuTriggerRef = useRef<HTMLButtonElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const selection = useCallback((): MessageSelection => ({
    selected_skills: selectedSkills,
    selected_tools: selectedTools,
    tool_mode: selectedTools.length > 0 ? "restricted" : "auto",
    force_tool: selectedTools.length === 1 ? selectedTools[0] : null,
  }), [selectedSkills, selectedTools]);

  const localized = useCallback((item: CapabilityItem | ToolCapability, field: "name" | "description") => {
    const key = `agent.capabilities.${item.name}.${field}`;
    return t(key as never, { defaultValue: field === "name" ? item.name : item.description });
  }, [t]);

  const slashOptions = useCallback((): SlashOption[] => {
    if (!slashContext) return [];
    if (slashContext.kind === "root") {
      return [
        { kind: "category", value: "skills", label: t("agent.slash.skills"), description: t("agent.slash.skillCategory") },
        { kind: "category", value: "tools", label: t("agent.slash.tools"), description: t("agent.slash.toolCategory") },
        { kind: "category", value: "commands", label: t("agent.slash.commands"), description: t("agent.slash.chooseCapability") },
      ];
    }
    if (slashContext.kind === "commands") {
      return [
        { kind: "command", value: "goal", label: t("agent.researchGoal"), description: t("agent.describeGoal") },
        { kind: "command", value: "swarm", label: t("agent.agentSwarm"), description: t("agent.runSwarmTeam") },
        { kind: "command", value: "connector", label: t("agent.checkConnector"), description: t("agent.checkConnector") },
      ];
    }
    const source = slashContext.kind === "skills" ? capabilities?.skills ?? [] : capabilities?.tools ?? [];
    return filterCapabilities(source, slashContext.query).sort((a, b) => a.category.localeCompare(b.category) || a.name.localeCompare(b.name)).map((item) => ({
      kind: "capability",
      value: item.name,
      label: localized(item, "name"),
      description: localized(item, "description"),
      category: item.category,
      capability: item,
    }));
  }, [capabilities, localized, slashContext, t]);

  const options = slashOptions();

  useEffect(() => {
    if (!slashContext || options.length === 0) return;
    const option = options[slashIndex];
    if (!option) return;
    const element = slashOptionRefs.current[`${option.kind}-${option.value}`];
    if (element && typeof element.scrollIntoView === "function") {
      element.scrollIntoView({ block: "nearest" });
    }
  }, [options, slashContext, slashIndex]);

  const focus = useCallback(() => {
    inputRef.current?.focus({ preventScroll: true });
  }, []);

  const submitPrompt = useCallback((prompt: string) => {
    if (!prompt.trim() || streaming) return;
    setInput("");
    if (inputRef.current) inputRef.current.style.height = "auto";
    const submittedAttachment = attachment;
    if (!goalComposerActive) setAttachment(null);
    const selected = selection();
    if (selected.selected_skills.length || selected.selected_tools.length) {
      onSubmit(prompt.trim(), submittedAttachment, selected);
    } else {
      onSubmit(prompt.trim(), submittedAttachment);
    }
    setSelectedSkills([]);
    setSelectedTools([]);
    inputRef.current?.focus();
  }, [attachment, goalComposerActive, onSubmit, selection, streaming]);

  const chooseSlashOption = useCallback((option: SlashOption) => {
    if (!slashContext) return;
    if (option.kind === "category") {
      const prefix = option.value === "skills" ? "/skills " : option.value === "tools" ? "/tools " : "/commands ";
      const cursor = inputRef.current?.selectionStart ?? input.length;
      setInput((value) => value.slice(0, slashContext.start) + prefix + value.slice(cursor));
      if (option.value === "skills" || option.value === "tools" || option.value === "commands") {
        setSlashContext({ kind: option.value, query: "", start: slashContext.start });
      }
      requestAnimationFrame(() => inputRef.current?.focus());
      return;
    }
    if (option.kind === "command") {
      setSlashContext(null);
      if (option.value === "goal") onStartGoal();
      else if (option.value === "swarm") onStartSwarm();
      else submitPrompt(CONNECTOR_CHECK_PROMPT);
      return;
    }
    const isSkill = slashContext.kind === "skills";
    if (isSkill) setSelectedSkills((items) => items.includes(option.value) ? items : [...items, option.value]);
    else setSelectedTools((items) => items.includes(option.value) ? items : [...items, option.value]);
    const cursor = inputRef.current?.selectionStart ?? input.length;
    setInput((value) => value.slice(0, slashContext.start) + value.slice(cursor));
    setSlashContext(null);
    requestAnimationFrame(() => inputRef.current?.focus());
  }, [input.length, onStartGoal, onStartSwarm, slashContext, submitPrompt]);

  const updateSlashContext = useCallback((value: string) => {
    const cursor = inputRef.current?.selectionStart ?? value.length;
    const next = getSlashContext(value, cursor);
    setSlashContext(next);
    setSlashIndex(0);
  }, []);

  useImperativeHandle(ref, () => ({
    fill(prompt: string) {
      setInput(prompt);
      requestAnimationFrame(() => {
        const composer = inputRef.current;
        if (!composer) return;
        composer.focus({ preventScroll: true });
        composer.style.height = "auto";
        composer.style.height = `${composer.scrollHeight}px`;
      });
    },
    focus,
    submit: submitPrompt,
  }), [focus, submitPrompt]);

  const handleSubmit = useCallback((event: FormEvent) => {
    event.preventDefault();
    submitPrompt(input);
  }, [input, submitPrompt]);

  const handleFileSelect = useCallback(async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (!file) return;
    event.target.value = "";
    const blockedExts = [
      ".exe", ".msi", ".bat", ".cmd", ".com", ".scr", ".app", ".dmg",
      ".so", ".dll", ".dylib",
      ".zip", ".rar", ".7z", ".tar", ".gz", ".tgz", ".bz2", ".xz",
    ];
    const lowered = file.name.toLowerCase();
    if (blockedExts.some((ext) => lowered.endsWith(ext))) {
      toast.error(t("agent.executablesNotAllowed"));
      return;
    }
    if (file.size > 50 * 1024 * 1024) {
      toast.error(t("agent.fileSizeExceeds"));
      return;
    }
    setUploading(true);
    setShowUploadMenu(false);
    try {
      const result = await api.uploadFile(file);
      setAttachment({ filename: result.filename, filePath: result.file_path });
      toast.success(t("agent.uploaded", { filename: result.filename }));
    } catch (error) {
      toast.error(t("agent.uploadFailed", {
        error: error instanceof Error ? error.message : "Unknown error",
      }));
    } finally {
      setUploading(false);
    }
  }, [t]);

  useEffect(() => {
    const handleClickOutside = (event: MouseEvent) => {
      if (uploadMenuRef.current && !uploadMenuRef.current.contains(event.target as Node)) {
        setShowUploadMenu(false);
      }
    };
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      setShowUploadMenu(false);
      uploadMenuTriggerRef.current?.focus();
    };
    if (showUploadMenu) {
      document.addEventListener("mousedown", handleClickOutside);
      document.addEventListener("keydown", handleEscape);
      return () => {
        document.removeEventListener("mousedown", handleClickOutside);
        document.removeEventListener("keydown", handleEscape);
      };
    }
  }, [showUploadMenu]);

  return (
    <form onSubmit={handleSubmit} className="space-y-2">
      {swarmPreset && (
        <div className="flex items-center gap-1">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-primary/10 text-primary text-xs font-medium">
            <Users className="h-3 w-3" />
            {swarmPreset.title}
            <button type="button" onClick={onCancelSwarm} className="hover:text-destructive transition-colors">
              <X className="h-3 w-3" />
            </button>
          </span>
        </div>
      )}
      {goalComposerActive && (
        <div className="flex items-center gap-1">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-primary/10 text-primary text-xs font-medium">
            <Target className="h-3 w-3" />
            {t("agent.newResearchGoal")}
            <button type="button" onClick={onCancelGoal} className="hover:text-destructive transition-colors">
              <X className="h-3 w-3" />
            </button>
          </span>
        </div>
      )}
      {panels}
      <LiveRuntimeStatus />
      {attachment && (
        <div className="flex items-center gap-1">
          <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-lg bg-primary/10 text-primary text-xs font-medium">
            <Paperclip className="h-3 w-3" />
            {attachment.filename}
            <button type="button" onClick={() => setAttachment(null)} className="hover:text-destructive transition-colors">
              <X className="h-3 w-3" />
            </button>
          </span>
        </div>
      )}
      {uploading && (
        <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <Loader2 className="h-3 w-3 animate-spin" />
          {t("agent.uploading")}
        </div>
      )}
      {(selectedSkills.length > 0 || selectedTools.length > 0) && (
        <div className="flex flex-wrap items-center gap-1">
          {selectedSkills.map((name) => (
            <span
              key={`skill-${name}`}
              className="group relative inline-flex items-center gap-1 rounded-lg border border-sky-200/70 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 shadow-[0_2px_8px_rgba(14,165,233,0.14)] dark:border-sky-400/20 dark:bg-sky-400/10 dark:text-sky-200"
              title={capabilities?.skills.find((item) => item.name === name)?.description}
            >
              {t("agent.slash.selectedSkill")}: {name}
              <button type="button" aria-label={`Remove ${name}`} onClick={() => setSelectedSkills((items) => items.filter((item) => item !== name))}>
                <X className="h-3 w-3" />
              </button>
              {capabilities?.skills.find((item) => item.name === name)?.description && (
                <span className="pointer-events-none invisible absolute bottom-full right-0 z-50 mb-2 w-64 rounded-lg border border-sky-200/70 bg-background px-3 py-2 text-left text-xs font-normal leading-relaxed text-muted-foreground opacity-0 shadow-lg transition-opacity group-hover:visible group-hover:opacity-100 dark:border-sky-400/20">
                  {capabilities.skills.find((item) => item.name === name)?.description}
                </span>
              )}
            </span>
          ))}
          {selectedTools.map((name) => (
            <span
              key={`tool-${name}`}
              className="group relative inline-flex items-center gap-1 rounded-lg border border-sky-200/70 bg-sky-50 px-2.5 py-1 text-xs font-medium text-sky-700 shadow-[0_2px_8px_rgba(14,165,233,0.14)] dark:border-sky-400/20 dark:bg-sky-400/10 dark:text-sky-200"
              title={capabilities?.tools.find((item) => item.name === name)?.description}
            >
              {t("agent.slash.selectedTool")}: {name}
              <button type="button" aria-label={`Remove ${name}`} onClick={() => setSelectedTools((items) => items.filter((item) => item !== name))}>
                <X className="h-3 w-3" />
              </button>
              {capabilities?.tools.find((item) => item.name === name)?.description && (
                <span className="pointer-events-none invisible absolute bottom-full right-0 z-50 mb-2 w-64 rounded-lg border border-sky-200/70 bg-background px-3 py-2 text-left text-xs font-normal leading-relaxed text-muted-foreground opacity-0 shadow-lg transition-opacity group-hover:visible group-hover:opacity-100 dark:border-sky-400/20">
                  {capabilities.tools.find((item) => item.name === name)?.description}
                </span>
              )}
            </span>
          ))}
        </div>
      )}
      <LiveRuntimeControl />
      <div className="relative flex items-end gap-2 rounded-2xl border border-border/60 bg-background p-1.5 shadow-[0_1px_2px_rgba(0,0,0,0.03),0_8px_24px_-12px_rgba(0,0,0,0.12)] transition-shadow focus-within:ring-2 focus-within:ring-primary/25 dark:bg-card">
        <div className="relative" ref={uploadMenuRef}>
          <button
            ref={uploadMenuTriggerRef}
            type="button"
            onClick={() => setShowUploadMenu((previous) => !previous)}
            disabled={streaming || uploading}
            aria-haspopup="menu"
            aria-expanded={showUploadMenu}
            aria-controls="agent-more-options-menu"
            className="w-10 h-10 rounded-full border flex items-center justify-center text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-40 shrink-0"
            title={t("agent.moreOptions")}
          >
            <Plus className="h-4 w-4" />
          </button>
          {showUploadMenu && (
            <div
              id="agent-more-options-menu"
              role="menu"
              className="absolute bottom-full left-0 mb-2 w-52 rounded-xl border bg-background/95 backdrop-blur-sm shadow-lg py-1 z-50"
            >
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  fileInputRef.current?.click();
                  setShowUploadMenu(false);
                }}
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors flex items-center gap-2"
              >
                <Paperclip className="h-4 w-4" />
                {t("agent.uploadPdf")}
              </button>
              <div className="border-t my-1" />
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setShowUploadMenu(false);
                  onStartGoal();
                  inputRef.current?.focus();
                }}
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors flex items-center gap-2"
              >
                <Target className="h-4 w-4" />
                {t("agent.researchGoal")}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setShowUploadMenu(false);
                  onStartSwarm();
                  inputRef.current?.focus();
                }}
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors flex items-center gap-2"
              >
                <Users className="h-4 w-4" />
                {t("agent.agentSwarm")}
              </button>
              <div className="border-t my-1" />
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setShowUploadMenu(false);
                  submitPrompt(CONNECTOR_CHECK_PROMPT);
                }}
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors flex items-center gap-2"
              >
                <Landmark className="h-4 w-4" />
                {t("agent.checkConnector")}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => {
                  setShowUploadMenu(false);
                  submitPrompt(CONNECTOR_PORTFOLIO_PROMPT);
                }}
                className="w-full px-3 py-2 text-left text-sm hover:bg-muted transition-colors flex items-center gap-2"
              >
                <Landmark className="h-4 w-4" />
                {t("agent.analyzePortfolio")}
              </button>
            </div>
          )}
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept={ACCEPTED_FILE_TYPES}
          onChange={handleFileSelect}
          className="hidden"
        />
        {slashContext && (
          <div role="listbox" aria-label={t("agent.slash.chooseCapability")} className="absolute bottom-full left-12 right-12 z-50 mb-2 max-h-72 overflow-y-auto rounded-xl border bg-background/95 p-1 shadow-lg backdrop-blur-sm">
            <div className="px-3 py-2 text-xs text-muted-foreground">{t("agent.slash.chooseCapability")}</div>
            {options.length === 0 ? (
              <div className="px-3 py-3 text-sm text-muted-foreground">{t("agent.slash.noResults")}</div>
            ) : options.map((option, index) => (
              <div key={`${option.kind}-${option.value}`}>
                {option.category && (index === 0 || option.category !== options[index - 1]?.category) && (
                  <div className="px-3 pb-1 pt-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground/70">
                    {t(`agent.slash.categories.${option.category}` as never, { defaultValue: option.category })}
                  </div>
                )}
                <button
                  type="button"
                  role="option"
                  ref={(element) => {
                    slashOptionRefs.current[`${option.kind}-${option.value}`] = element;
                  }}
                  aria-selected={index === slashIndex}
                  onMouseDown={(event) => event.preventDefault()}
                  onClick={() => chooseSlashOption(option)}
                  className={`flex w-full items-start gap-2 rounded-lg px-3 py-2 text-left text-sm transition-colors ${index === slashIndex ? "bg-muted" : "hover:bg-muted/70"}`}
                >
                  <span className="shrink-0 font-medium text-foreground">{option.label}</span>
                  <span className="line-clamp-2 text-muted-foreground/70" title={option.description}>{option.description}</span>
                </button>
              </div>
            ))}
          </div>
        )}
        <textarea
          ref={inputRef}
          value={input}
          rows={1}
          onChange={(e) => {
            setInput(e.target.value);
            updateSlashContext(e.target.value);
          }}
          onCompositionStart={() => {
            isComposingRef.current = true;
          }}
          onCompositionEnd={() => {
            isComposingRef.current = false;
            lastCompositionEndRef.current = Date.now();
          }}
          onInput={(e) => {
            const el = e.target as HTMLTextAreaElement;
            el.style.height = "auto";
            el.style.height = el.scrollHeight + "px";
          }}
          onKeyDown={(e) => {
            if (slashContext && options.length > 0 && (e.key === "ArrowDown" || e.key === "ArrowUp" || e.key === "Enter" || e.key === "Escape")) {
              e.preventDefault();
              if (e.key === "ArrowDown") setSlashIndex((index) => (index + 1) % options.length);
              else if (e.key === "ArrowUp") setSlashIndex((index) => (index - 1 + options.length) % options.length);
              else if (e.key === "Enter") chooseSlashOption(options[slashIndex]);
              else setSlashContext(null);
              return;
            }
            if (slashContext && e.key === "Escape") {
              e.preventDefault();
              setSlashContext(null);
              return;
            }
            if (e.key === "Enter" && !e.shiftKey) {
              const nativeEvent = e.nativeEvent as KeyboardEvent & { isComposing?: boolean };
              const justFinishedComposing = Date.now() - lastCompositionEndRef.current < 80;
              if (isComposingRef.current || nativeEvent.isComposing || nativeEvent.keyCode === 229) {
                return;
              }
              if (justFinishedComposing) {
                e.preventDefault();
                return;
              }
              e.preventDefault();
              submitPrompt(input);
            }
          }}
          placeholder={
            streaming
              ? t(`agent.activity.verbs.${activityVerb ?? "working"}` as never)
              : goalComposerActive
              ? t("agent.describeGoal")
              : hasCompletedTurn
              ? t("agent.followUpPlaceholder" as never)
              : t("agent.placeholder")
          }
          aria-label={t("agent.messageInputLabel")}
          aria-readonly={streaming}
          className={[
            "min-h-[52px] flex-1 resize-none overflow-y-auto bg-transparent px-3 py-3 text-sm outline-none max-h-32",
            streaming ? "cursor-not-allowed text-muted-foreground/70" : "",
          ].join(" ")}
          readOnly={streaming}
        />
        {showExport && (
          <button
            type="button"
            onClick={onExport}
            disabled={!canExport}
            className="h-10 px-3 rounded-xl border text-muted-foreground hover:text-foreground hover:bg-muted transition-colors disabled:opacity-30 disabled:pointer-events-none"
            title={t("agent.exportChat")}
          >
            <Download className="h-4 w-4" />
          </button>
        )}
        {streaming ? (
          <button
            type="button"
            onClick={onCancel}
            className="h-10 px-4 rounded-xl bg-destructive text-destructive-foreground text-sm font-medium hover:opacity-90 transition-opacity"
            title={t("agent.stopGeneration")}
          >
            <Square className="h-4 w-4" />
          </button>
        ) : (
          <button
            type="submit"
            disabled={goalComposerActive ? !input.trim() : (!input.trim() && !attachment)}
            className="h-10 px-4 rounded-xl bg-primary text-primary-foreground text-sm font-medium disabled:opacity-40 hover:opacity-90 transition-opacity"
            title={t("agent.send")}
            aria-label={t("agent.send")}
          >
            <Send className="h-4 w-4" />
          </button>
        )}
      </div>
      <p className="px-1 text-[11px] text-muted-foreground">{t("agent.inputHint")}</p>
    </form>
  );
}));
