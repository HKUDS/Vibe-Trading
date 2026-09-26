import { useEffect, useId, useMemo, useState, type FormEvent, type KeyboardEvent } from "react";
import {
  CheckCircle2,
  ChevronRight,
  ExternalLink,
  KeyRound,
  Loader2,
  PlugZap,
  Save,
  ShieldAlert,
  X,
  XCircle,
} from "lucide-react";
import type { TFunction } from "i18next";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";
import {
  ApiError,
  api,
  type ChannelConfigEntry,
  type ChannelFieldHint,
  type ChannelPutBody,
  type ChannelTestBody,
  type ChannelTestResult,
} from "@/lib/api";

const fieldClass =
  "w-full rounded-md border bg-background px-3 py-2 text-sm outline-none transition focus:border-primary focus:ring-2 focus:ring-primary/20 disabled:cursor-not-allowed disabled:opacity-60";
const labelClass = "text-sm font-medium";
const hintClass = "text-xs text-muted-foreground";

type FormValue = string | boolean | string[];

interface ApiFailure {
  status: number | null;
  code: string | null;
  message: string;
}

/** Read a failed request into status/code/message without trusting its shape. */
function describeApiFailure(error: unknown): ApiFailure {
  const status = error instanceof ApiError ? error.status : null;
  const message = error instanceof Error ? error.message : "";
  const code = error instanceof ApiError && error.code ? error.code : null;
  return { status, code, message };
}

/** Normalize one stored value into the shape its widget edits. */
function fieldValue(field: ChannelFieldHint, values: Record<string, unknown>): FormValue {
  const raw = values[field.key];
  if (field.type === "bool") return Boolean(raw);
  if (field.type === "list") return Array.isArray(raw) ? raw.map(String) : [];
  return raw === null || raw === undefined ? "" : String(raw);
}

function initialFormValues(entry: ChannelConfigEntry): Record<string, FormValue> {
  const next: Record<string, FormValue> = {};
  for (const field of entry.fields) {
    if (field.secret) continue;
    next[field.key] = fieldValue(field, entry.values);
  }
  return next;
}

interface ChannelGuide {
  title: string;
  intro: string;
  steps: string[];
  docsUrl: string;
  docsLabel: string;
}

/**
 * Per-channel setup guide registry: adding a channel is one entry here plus its
 * i18n keys. `build` must use literal t() keys — typed i18n rejects
 * interpolated ones — and receives `t` so the copy re-resolves on language
 * change instead of being frozen at module load.
 */
const GUIDE_DEFS: Record<
  string,
  { docsUrl: string; build: (t: TFunction) => Omit<ChannelGuide, "docsUrl"> } | undefined
> = {
  dingtalk: {
    docsUrl: "https://open-dev.dingtalk.com/",
    build: (t) => ({
      title: t("settings.channels.guides.dingtalk.title"),
      intro: t("settings.channels.guides.dingtalk.intro"),
      steps: [
        t("settings.channels.guides.dingtalk.step1"),
        t("settings.channels.guides.dingtalk.step2"),
        t("settings.channels.guides.dingtalk.step3"),
        t("settings.channels.guides.dingtalk.step4"),
        t("settings.channels.guides.dingtalk.step5"),
      ],
      docsLabel: t("settings.channels.guides.dingtalk.docsLabel"),
    }),
  },
  qq: {
    docsUrl: "https://q.qq.com/",
    build: (t) => ({
      title: t("settings.channels.guides.qq.title"),
      intro: t("settings.channels.guides.qq.intro"),
      steps: [
        t("settings.channels.guides.qq.step1"),
        t("settings.channels.guides.qq.step2"),
        t("settings.channels.guides.qq.step3"),
        t("settings.channels.guides.qq.step4"),
        t("settings.channels.guides.qq.step5"),
      ],
      docsLabel: t("settings.channels.guides.qq.docsLabel"),
    }),
  },
  email: {
    docsUrl: "https://vibetrading.wiki/docs/",
    build: (t) => ({
      title: t("settings.channels.guides.email.title"),
      intro: t("settings.channels.guides.email.intro"),
      steps: [
        t("settings.channels.guides.email.step1"),
        t("settings.channels.guides.email.step2"),
        t("settings.channels.guides.email.step3"),
        t("settings.channels.guides.email.step4"),
        t("settings.channels.guides.email.step5"),
      ],
      docsLabel: t("settings.channels.guides.email.docsLabel"),
    }),
  },
  websocket: {
    docsUrl: "https://vibetrading.wiki/docs/",
    build: (t) => ({
      title: t("settings.channels.guides.websocket.title"),
      intro: t("settings.channels.guides.websocket.intro"),
      steps: [
        t("settings.channels.guides.websocket.step1"),
        t("settings.channels.guides.websocket.step2"),
        t("settings.channels.guides.websocket.step3"),
        t("settings.channels.guides.websocket.step4"),
        t("settings.channels.guides.websocket.step5"),
      ],
      docsLabel: t("settings.channels.guides.websocket.docsLabel"),
    }),
  },
  feishu: {
    docsUrl: "https://open.feishu.cn/",
    build: (t) => ({
      title: t("settings.channels.guides.feishu.title"),
      intro: t("settings.channels.guides.feishu.intro"),
      steps: [
        t("settings.channels.guides.feishu.step1"),
        t("settings.channels.guides.feishu.step2"),
        t("settings.channels.guides.feishu.step3"),
        t("settings.channels.guides.feishu.step4"),
        t("settings.channels.guides.feishu.step5"),
      ],
      docsLabel: t("settings.channels.guides.feishu.docsLabel"),
    }),
  },
};

export interface ChannelConfigPanelProps {
  name: string;
  entry: ChannelConfigEntry;
  writable: boolean;
  configPath?: string;
  /** Called after a successful PUT so the parent can refresh status + config. */
  onChanged: () => void | Promise<void>;
}

/**
 * Generic channel configuration form driven by the backend's `fields`
 * metadata: text, password (masked secrets), bool and list (tag) widgets.
 *
 * Secrets are accepted but never rendered — a stored secret is only ever
 * shown as its masked placeholder, and typing replaces it while leaving the
 * field empty keeps the stored value.
 */
export function ChannelConfigPanel({
  name,
  entry,
  writable,
  configPath,
  onChanged,
}: ChannelConfigPanelProps) {
  const { t } = useTranslation();
  const idPrefix = useId();
  const [values, setValues] = useState<Record<string, FormValue>>(() => initialFormValues(entry));
  const [secretDrafts, setSecretDrafts] = useState<Record<string, string>>({});
  const [clears, setClears] = useState<Record<string, boolean>>({});
  const [listDrafts, setListDrafts] = useState<Record<string, string>>({});
  const [guideOpen, setGuideOpen] = useState(false);
  const [testing, setTesting] = useState(false);
  const [saving, setSaving] = useState(false);
  const [toggling, setToggling] = useState(false);
  const [testResult, setTestResult] = useState<ChannelTestResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [errorDetail, setErrorDetail] = useState<string | null>(null);
  const [enableAnyway, setEnableAnyway] = useState(false);

  useEffect(() => {
    // A freshly fetched entry re-seeds non-secret fields (typed secret drafts
    // survive a refresh until they are saved or cleared).
    setValues(initialFormValues(entry));
    setTestResult(null);
    setError(null);
    setErrorDetail(null);
    setEnableAnyway(false);
  }, [entry]);

  const enabled = Boolean(entry.values.enabled);
  const busy = saving || toggling || testing;
  const formDisabled = !writable || saving || testing;

  // Literal i18n calls per known backend help_key (typed i18n rejects
  // interpolated keys); the raw config key is the fallback label for any
  // channel metadata this build does not know yet.
  const fieldText = useMemo<Record<string, { label: string; help: string }>>(
    () => ({
      "settings.channels.fields.dingtalk.client_id": { label: t("settings.channels.fields.dingtalk.client_id.label"), help: t("settings.channels.fields.dingtalk.client_id.help") },
      "settings.channels.fields.dingtalk.client_secret": { label: t("settings.channels.fields.dingtalk.client_secret.label"), help: t("settings.channels.fields.dingtalk.client_secret.help") },
      "settings.channels.fields.dingtalk.allow_from": { label: t("settings.channels.fields.dingtalk.allow_from.label"), help: t("settings.channels.fields.dingtalk.allow_from.help") },
      "settings.channels.fields.dingtalk.allow_remote_media_redirects": { label: t("settings.channels.fields.dingtalk.allow_remote_media_redirects.label"), help: t("settings.channels.fields.dingtalk.allow_remote_media_redirects.help") },
      "settings.channels.fields.dingtalk.remote_media_redirect_allowed_hosts": { label: t("settings.channels.fields.dingtalk.remote_media_redirect_allowed_hosts.label"), help: t("settings.channels.fields.dingtalk.remote_media_redirect_allowed_hosts.help") },
      "settings.channels.fields.dingtalk.group_user_isolation": { label: t("settings.channels.fields.dingtalk.group_user_isolation.label"), help: t("settings.channels.fields.dingtalk.group_user_isolation.help") },
      "settings.channels.fields.dingtalk.force_ipv4": { label: t("settings.channels.fields.dingtalk.force_ipv4.label"), help: t("settings.channels.fields.dingtalk.force_ipv4.help") },
      "settings.channels.fields.qq.app_id": { label: t("settings.channels.fields.qq.app_id.label"), help: t("settings.channels.fields.qq.app_id.help") },
      "settings.channels.fields.qq.secret": { label: t("settings.channels.fields.qq.secret.label"), help: t("settings.channels.fields.qq.secret.help") },
      "settings.channels.fields.qq.allow_from": { label: t("settings.channels.fields.qq.allow_from.label"), help: t("settings.channels.fields.qq.allow_from.help") },
      "settings.channels.fields.qq.msg_format": { label: t("settings.channels.fields.qq.msg_format.label"), help: t("settings.channels.fields.qq.msg_format.help") },
      "settings.channels.fields.qq.ack_message": { label: t("settings.channels.fields.qq.ack_message.label"), help: t("settings.channels.fields.qq.ack_message.help") },
      "settings.channels.fields.qq.media_dir": { label: t("settings.channels.fields.qq.media_dir.label"), help: t("settings.channels.fields.qq.media_dir.help") },
      "settings.channels.fields.qq.download_chunk_size": { label: t("settings.channels.fields.qq.download_chunk_size.label"), help: t("settings.channels.fields.qq.download_chunk_size.help") },
      "settings.channels.fields.qq.download_max_bytes": { label: t("settings.channels.fields.qq.download_max_bytes.label"), help: t("settings.channels.fields.qq.download_max_bytes.help") },
      "settings.channels.fields.email.consent_granted": { label: t("settings.channels.fields.email.consent_granted.label"), help: t("settings.channels.fields.email.consent_granted.help") },
      "settings.channels.fields.email.imap_host": { label: t("settings.channels.fields.email.imap_host.label"), help: t("settings.channels.fields.email.imap_host.help") },
      "settings.channels.fields.email.imap_port": { label: t("settings.channels.fields.email.imap_port.label"), help: t("settings.channels.fields.email.imap_port.help") },
      "settings.channels.fields.email.imap_username": { label: t("settings.channels.fields.email.imap_username.label"), help: t("settings.channels.fields.email.imap_username.help") },
      "settings.channels.fields.email.imap_password": { label: t("settings.channels.fields.email.imap_password.label"), help: t("settings.channels.fields.email.imap_password.help") },
      "settings.channels.fields.email.imap_mailbox": { label: t("settings.channels.fields.email.imap_mailbox.label"), help: t("settings.channels.fields.email.imap_mailbox.help") },
      "settings.channels.fields.email.imap_use_ssl": { label: t("settings.channels.fields.email.imap_use_ssl.label"), help: t("settings.channels.fields.email.imap_use_ssl.help") },
      "settings.channels.fields.email.imap_use_tls": { label: t("settings.channels.fields.email.imap_use_tls.label"), help: t("settings.channels.fields.email.imap_use_tls.help") },
      "settings.channels.fields.email.smtp_host": { label: t("settings.channels.fields.email.smtp_host.label"), help: t("settings.channels.fields.email.smtp_host.help") },
      "settings.channels.fields.email.smtp_port": { label: t("settings.channels.fields.email.smtp_port.label"), help: t("settings.channels.fields.email.smtp_port.help") },
      "settings.channels.fields.email.smtp_username": { label: t("settings.channels.fields.email.smtp_username.label"), help: t("settings.channels.fields.email.smtp_username.help") },
      "settings.channels.fields.email.smtp_password": { label: t("settings.channels.fields.email.smtp_password.label"), help: t("settings.channels.fields.email.smtp_password.help") },
      "settings.channels.fields.email.smtp_use_tls": { label: t("settings.channels.fields.email.smtp_use_tls.label"), help: t("settings.channels.fields.email.smtp_use_tls.help") },
      "settings.channels.fields.email.smtp_use_ssl": { label: t("settings.channels.fields.email.smtp_use_ssl.label"), help: t("settings.channels.fields.email.smtp_use_ssl.help") },
      "settings.channels.fields.email.verify_tls": { label: t("settings.channels.fields.email.verify_tls.label"), help: t("settings.channels.fields.email.verify_tls.help") },
      "settings.channels.fields.email.from_address": { label: t("settings.channels.fields.email.from_address.label"), help: t("settings.channels.fields.email.from_address.help") },
      "settings.channels.fields.email.auto_reply_enabled": { label: t("settings.channels.fields.email.auto_reply_enabled.label"), help: t("settings.channels.fields.email.auto_reply_enabled.help") },
      "settings.channels.fields.email.poll_interval_seconds": { label: t("settings.channels.fields.email.poll_interval_seconds.label"), help: t("settings.channels.fields.email.poll_interval_seconds.help") },
      "settings.channels.fields.email.mark_seen": { label: t("settings.channels.fields.email.mark_seen.label"), help: t("settings.channels.fields.email.mark_seen.help") },
      "settings.channels.fields.email.post_action": { label: t("settings.channels.fields.email.post_action.label"), help: t("settings.channels.fields.email.post_action.help") },
      "settings.channels.fields.email.post_action_move_mailbox": { label: t("settings.channels.fields.email.post_action_move_mailbox.label"), help: t("settings.channels.fields.email.post_action_move_mailbox.help") },
      "settings.channels.fields.email.post_action_expunge": { label: t("settings.channels.fields.email.post_action_expunge.label"), help: t("settings.channels.fields.email.post_action_expunge.help") },
      "settings.channels.fields.email.post_action_ignore_skipped": { label: t("settings.channels.fields.email.post_action_ignore_skipped.label"), help: t("settings.channels.fields.email.post_action_ignore_skipped.help") },
      "settings.channels.fields.email.max_body_chars": { label: t("settings.channels.fields.email.max_body_chars.label"), help: t("settings.channels.fields.email.max_body_chars.help") },
      "settings.channels.fields.email.subject_prefix": { label: t("settings.channels.fields.email.subject_prefix.label"), help: t("settings.channels.fields.email.subject_prefix.help") },
      "settings.channels.fields.email.allow_from": { label: t("settings.channels.fields.email.allow_from.label"), help: t("settings.channels.fields.email.allow_from.help") },
      "settings.channels.fields.email.verify_dkim": { label: t("settings.channels.fields.email.verify_dkim.label"), help: t("settings.channels.fields.email.verify_dkim.help") },
      "settings.channels.fields.email.verify_spf": { label: t("settings.channels.fields.email.verify_spf.label"), help: t("settings.channels.fields.email.verify_spf.help") },
      "settings.channels.fields.email.allowed_attachment_types": { label: t("settings.channels.fields.email.allowed_attachment_types.label"), help: t("settings.channels.fields.email.allowed_attachment_types.help") },
      "settings.channels.fields.email.max_attachment_size": { label: t("settings.channels.fields.email.max_attachment_size.label"), help: t("settings.channels.fields.email.max_attachment_size.help") },
      "settings.channels.fields.email.max_attachments_per_email": { label: t("settings.channels.fields.email.max_attachments_per_email.label"), help: t("settings.channels.fields.email.max_attachments_per_email.help") },
      "settings.channels.fields.websocket.host": { label: t("settings.channels.fields.websocket.host.label"), help: t("settings.channels.fields.websocket.host.help") },
      "settings.channels.fields.websocket.port": { label: t("settings.channels.fields.websocket.port.label"), help: t("settings.channels.fields.websocket.port.help") },
      "settings.channels.fields.websocket.unix_socket_path": { label: t("settings.channels.fields.websocket.unix_socket_path.label"), help: t("settings.channels.fields.websocket.unix_socket_path.help") },
      "settings.channels.fields.websocket.path": { label: t("settings.channels.fields.websocket.path.label"), help: t("settings.channels.fields.websocket.path.help") },
      "settings.channels.fields.websocket.token": { label: t("settings.channels.fields.websocket.token.label"), help: t("settings.channels.fields.websocket.token.help") },
      "settings.channels.fields.websocket.token_issue_path": { label: t("settings.channels.fields.websocket.token_issue_path.label"), help: t("settings.channels.fields.websocket.token_issue_path.help") },
      "settings.channels.fields.websocket.token_issue_secret": { label: t("settings.channels.fields.websocket.token_issue_secret.label"), help: t("settings.channels.fields.websocket.token_issue_secret.help") },
      "settings.channels.fields.websocket.token_ttl_s": { label: t("settings.channels.fields.websocket.token_ttl_s.label"), help: t("settings.channels.fields.websocket.token_ttl_s.help") },
      "settings.channels.fields.websocket.websocket_requires_token": { label: t("settings.channels.fields.websocket.websocket_requires_token.label"), help: t("settings.channels.fields.websocket.websocket_requires_token.help") },
      "settings.channels.fields.websocket.allow_from": { label: t("settings.channels.fields.websocket.allow_from.label"), help: t("settings.channels.fields.websocket.allow_from.help") },
      "settings.channels.fields.websocket.streaming": { label: t("settings.channels.fields.websocket.streaming.label"), help: t("settings.channels.fields.websocket.streaming.help") },
      "settings.channels.fields.websocket.max_message_bytes": { label: t("settings.channels.fields.websocket.max_message_bytes.label"), help: t("settings.channels.fields.websocket.max_message_bytes.help") },
      "settings.channels.fields.websocket.ping_interval_s": { label: t("settings.channels.fields.websocket.ping_interval_s.label"), help: t("settings.channels.fields.websocket.ping_interval_s.help") },
      "settings.channels.fields.websocket.ping_timeout_s": { label: t("settings.channels.fields.websocket.ping_timeout_s.label"), help: t("settings.channels.fields.websocket.ping_timeout_s.help") },
      "settings.channels.fields.websocket.ssl_certfile": { label: t("settings.channels.fields.websocket.ssl_certfile.label"), help: t("settings.channels.fields.websocket.ssl_certfile.help") },
      "settings.channels.fields.websocket.ssl_keyfile": { label: t("settings.channels.fields.websocket.ssl_keyfile.label"), help: t("settings.channels.fields.websocket.ssl_keyfile.help") },
      "settings.channels.fields.feishu.app_id": { label: t("settings.channels.fields.feishu.app_id.label"), help: t("settings.channels.fields.feishu.app_id.help") },
      "settings.channels.fields.feishu.app_secret": { label: t("settings.channels.fields.feishu.app_secret.label"), help: t("settings.channels.fields.feishu.app_secret.help") },
      "settings.channels.fields.feishu.encrypt_key": { label: t("settings.channels.fields.feishu.encrypt_key.label"), help: t("settings.channels.fields.feishu.encrypt_key.help") },
      "settings.channels.fields.feishu.verification_token": { label: t("settings.channels.fields.feishu.verification_token.label"), help: t("settings.channels.fields.feishu.verification_token.help") },
      "settings.channels.fields.feishu.allow_from": { label: t("settings.channels.fields.feishu.allow_from.label"), help: t("settings.channels.fields.feishu.allow_from.help") },
      "settings.channels.fields.feishu.react_emoji": { label: t("settings.channels.fields.feishu.react_emoji.label"), help: t("settings.channels.fields.feishu.react_emoji.help") },
      "settings.channels.fields.feishu.done_emoji": { label: t("settings.channels.fields.feishu.done_emoji.label"), help: t("settings.channels.fields.feishu.done_emoji.help") },
      "settings.channels.fields.feishu.tool_hint_prefix": { label: t("settings.channels.fields.feishu.tool_hint_prefix.label"), help: t("settings.channels.fields.feishu.tool_hint_prefix.help") },
      "settings.channels.fields.feishu.group_policy": { label: t("settings.channels.fields.feishu.group_policy.label"), help: t("settings.channels.fields.feishu.group_policy.help") },
      "settings.channels.fields.feishu.reply_to_message": { label: t("settings.channels.fields.feishu.reply_to_message.label"), help: t("settings.channels.fields.feishu.reply_to_message.help") },
      "settings.channels.fields.feishu.streaming": { label: t("settings.channels.fields.feishu.streaming.label"), help: t("settings.channels.fields.feishu.streaming.help") },
      "settings.channels.fields.feishu.domain": { label: t("settings.channels.fields.feishu.domain.label"), help: t("settings.channels.fields.feishu.domain.help") },
      "settings.channels.fields.feishu.topic_isolation": { label: t("settings.channels.fields.feishu.topic_isolation.label"), help: t("settings.channels.fields.feishu.topic_isolation.help") },
    }),
    [t],
  );

  const testCodeText = useMemo<Record<ChannelTestResult["code"], string>>(
    () => ({
      ok: t("settings.channels.config.testCodeOk"),
      invalid_credentials: t("settings.channels.config.testCodeInvalidCredentials"),
      network: t("settings.channels.config.testCodeNetwork"),
      unsupported: t("settings.channels.config.testCodeUnsupported"),
    }),
    [t],
  );

  const guide = useMemo(() => {
    const definition = GUIDE_DEFS[name];
    if (!definition) return null;
    return { ...definition.build(t), docsUrl: definition.docsUrl };
  }, [name, t]);

  const setValue = (key: string, value: FormValue) => {
    setValues((current) => ({ ...current, [key]: value }));
  };

  const commitListDraft = (key: string) => {
    const parts = (listDrafts[key] ?? "").split(",").map((part) => part.trim()).filter(Boolean);
    if (!parts.length) return;
    setValues((current) => {
      const existing = Array.isArray(current[key]) ? (current[key] as string[]) : [];
      const merged = [...existing];
      for (const part of parts) if (!merged.includes(part)) merged.push(part);
      return { ...current, [key]: merged };
    });
    setListDrafts((current) => ({ ...current, [key]: "" }));
  };

  const removeListValue = (key: string, value: string) => {
    setValues((current) => {
      const existing = Array.isArray(current[key]) ? (current[key] as string[]) : [];
      return { ...current, [key]: existing.filter((item) => item !== value) };
    });
  };

  const onListKeyDown = (event: KeyboardEvent<HTMLInputElement>, key: string) => {
    if (event.key !== "Enter" && event.key !== ",") return;
    event.preventDefault();
    commitListDraft(key);
  };

  /** Non-secret fields always carry their current value; secret fields only a typed replacement. */
  const buildPatch = (): Record<string, unknown> => {
    const patch: Record<string, unknown> = {};
    for (const field of entry.fields) {
      if (field.secret) {
        const draft = (secretDrafts[field.key] ?? "").trim();
        if (draft) patch[field.key] = draft;
        continue;
      }
      const value = values[field.key];
      if (field.type === "list") patch[field.key] = Array.isArray(value) ? value : [];
      else if (field.type === "bool") patch[field.key] = Boolean(value);
      else patch[field.key] = typeof value === "string" ? value : "";
    }
    return patch;
  };

  const isDirty = useMemo(() => {
    const secretDraft = entry.fields.some(
      (field) => field.secret && (secretDrafts[field.key] ?? "").trim() !== "",
    );
    const clearPending = entry.fields.some((field) => clears[field.key]);
    const changed = entry.fields.some((field) => {
      if (field.secret) return false;
      const current = values[field.key];
      const original = fieldValue(field, entry.values);
      return JSON.stringify(current) !== JSON.stringify(original);
    });
    return secretDraft || clearPending || changed;
  }, [clears, entry, secretDrafts, values]);

  const showError = (message: string, detail?: string | null) => {
    setError(message);
    setErrorDetail(detail || null);
  };

  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setSaving(true);
    setError(null);
    setErrorDetail(null);
    setEnableAnyway(false);
    const body: ChannelPutBody = { config: buildPatch() };
    for (const field of entry.fields) {
      if (field.secret && clears[field.key]) body[`clear_${field.key}`] = true;
    }
    try {
      await api.putChannelConfig(name, body);
      setSecretDrafts({});
      setClears({});
      toast.success(t("settings.channels.config.saved"));
      await onChanged();
    } catch (saveError) {
      const failure = describeApiFailure(saveError);
      const message = failure.code === "config_not_writable" || failure.status === 400
        ? t("settings.channels.config.notWritable", { path: configPath ?? "" })
        : t("settings.channels.config.saveFailed", {
          message: failure.message || t("settings.unknownError"),
        });
      showError(message);
      toast.error(message);
    } finally {
      setSaving(false);
    }
  };

  const runTest = async () => {
    if (!entry.supports_test) return;
    setTesting(true);
    setError(null);
    setErrorDetail(null);
    setTestResult(null);
    try {
      // Pristine forms exercise the saved config (empty body); a dirty form
      // tests exactly what is on screen, including a typed-but-unsaved secret.
      const body: ChannelTestBody = { config: buildPatch() };
      for (const field of entry.fields) {
        if (field.secret && clears[field.key]) body[`clear_${field.key}`] = true;
      }
      const result = await api.testChannel(name, isDirty ? body : undefined);
      setTestResult(result);
      if (result.ok) toast.success(t("settings.channels.config.testOk"));
      else toast.error(testCodeText[result.code]);
    } catch (testError) {
      const failure = describeApiFailure(testError);
      showError(t("settings.channels.config.testFailed", {
        message: failure.message || t("settings.unknownError"),
      }));
    } finally {
      setTesting(false);
    }
  };

  const setEnabled = async (next: boolean, options?: { skipVerify?: boolean }) => {
    setToggling(true);
    setError(null);
    setErrorDetail(null);
    setEnableAnyway(false);
    try {
      await api.putChannelConfig(name, {
        config: { enabled: next },
        skip_verify: options?.skipVerify,
      });
      toast.success(
        next
          ? t("settings.channels.config.enabledToast")
          : t("settings.channels.config.disabledToast"),
      );
      await onChanged();
    } catch (toggleError) {
      const failure = describeApiFailure(toggleError);
      if (next && failure.status === 422) {
        // Credential verification blocked the enable transition; the user can
        // override with skip_verify after seeing the honest failure.
        showError(t("settings.channels.config.enableRejected"), failure.message);
        setEnableAnyway(true);
      } else if (failure.code === "config_not_writable" || failure.status === 400) {
        showError(t("settings.channels.config.notWritable", { path: configPath ?? "" }));
      } else {
        const message = next
          ? t("settings.channels.config.enableFailed", {
            message: failure.message || t("settings.unknownError"),
          })
          : t("settings.channels.config.disableFailed", {
            message: failure.message || t("settings.unknownError"),
          });
        showError(message);
        toast.error(message);
      }
    } finally {
      setToggling(false);
    }
  };

  const renderField = (field: ChannelFieldHint) => {
    const text = fieldText[field.help_key ?? ""] ?? {
      label: field.key.split("_").join(" "),
      help: "",
    };
    const inputId = `${idPrefix}-${field.key}`;
    const disabled = formDisabled || Boolean(field.secret && clears[field.key]);

    if (field.type === "bool") {
      return (
        <div key={field.key} className="grid gap-2">
          <label className="flex items-center justify-between gap-3 rounded-md border bg-muted/20 px-3 py-2">
            <span className={labelClass}>{text.label}</span>
            <input
              id={inputId}
              type="checkbox"
              checked={Boolean(values[field.key])}
              onChange={(event) => setValue(field.key, event.target.checked)}
              className="h-4 w-4 accent-primary"
              disabled={formDisabled}
            />
          </label>
          {text.help ? <span className={hintClass}>{text.help}</span> : null}
        </div>
      );
    }

    if (field.type === "list") {
      const items = Array.isArray(values[field.key]) ? (values[field.key] as string[]) : [];
      return (
        <div key={field.key} className="grid gap-2">
          <label className={labelClass} htmlFor={inputId}>{text.label}</label>
          <div className={`${fieldClass} flex min-h-10 flex-wrap items-center gap-1.5`}>
            {items.map((item) => (
              <span
                key={item}
                className="inline-flex items-center gap-1 rounded-full bg-muted px-2 py-0.5 text-xs"
              >
                {item}
                <button
                  type="button"
                  onClick={() => removeListValue(field.key, item)}
                  disabled={formDisabled}
                  aria-label={t("settings.channels.config.removeValue", { value: item })}
                  className="rounded-full text-muted-foreground transition hover:text-foreground disabled:opacity-50"
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            <input
              id={inputId}
              value={listDrafts[field.key] ?? ""}
              onChange={(event) => setListDrafts((current) => ({ ...current, [field.key]: event.target.value }))}
              onKeyDown={(event) => onListKeyDown(event, field.key)}
              onBlur={() => commitListDraft(field.key)}
              className="min-w-24 flex-1 bg-transparent text-sm outline-none"
              placeholder={items.length ? "" : t("settings.channels.config.listPlaceholder")}
              disabled={formDisabled}
            />
          </div>
          {text.help ? <span className={hintClass}>{text.help}</span> : null}
        </div>
      );
    }

    const secret = entry.secrets[field.key];
    const placeholder = field.secret
      ? secret?.set
        ? t("settings.channels.config.keepCurrent", { masked: secret.masked })
        : t("settings.channels.config.secretNotSet")
      : "";
    return (
      <div key={field.key} className="grid gap-2">
        <label className={labelClass} htmlFor={inputId}>
          {text.label}
          {field.required ? (
            <span className="ms-1 text-destructive" aria-hidden="true">*</span>
          ) : null}
        </label>
        <div className="relative">
          {field.secret ? (
            <KeyRound className="pointer-events-none absolute start-3 top-2.5 h-4 w-4 text-muted-foreground" />
          ) : null}
          <input
            id={inputId}
            type={field.secret ? "password" : "text"}
            value={field.secret ? (secretDrafts[field.key] ?? "") : (values[field.key] as string ?? "")}
            onChange={(event) => {
              if (field.secret) {
                setSecretDrafts((current) => ({ ...current, [field.key]: event.target.value }));
              } else {
                setValue(field.key, event.target.value);
              }
            }}
            className={`${fieldClass}${field.secret ? " ps-9" : ""}`}
            placeholder={placeholder}
            autoComplete={field.secret ? "new-password" : "off"}
            disabled={disabled}
          />
        </div>
        <div className="flex items-start justify-between gap-3">
          <span className={hintClass}>
            {text.help}
            {field.required ? ` ${t("settings.channels.config.required")}` : ""}
          </span>
          {field.secret && secret?.set ? (
            <label className="flex shrink-0 items-center gap-2 text-xs text-muted-foreground">
              <input
                type="checkbox"
                checked={Boolean(clears[field.key])}
                onChange={(event) => {
                  const checked = event.target.checked;
                  setClears((current) => ({ ...current, [field.key]: checked }));
                  if (checked) setSecretDrafts((current) => ({ ...current, [field.key]: "" }));
                }}
                className="h-3.5 w-3.5 accent-primary"
                disabled={formDisabled}
              />
              {t("settings.channels.config.clearSecret")}
            </label>
          ) : null}
        </div>
      </div>
    );
  };

  return (
    <div className="grid gap-4">
      {!writable ? (
        <div className="rounded-md border border-warning/40 bg-warning/10 px-3 py-2 text-sm text-warning-foreground">
          {t("settings.channels.config.notWritable", { path: configPath ?? "" })}
        </div>
      ) : null}

      {!entry.sdk_available ? (
        <div className="inline-flex w-fit items-center gap-2 rounded-full bg-warning/10 px-2.5 py-1 text-xs text-warning-foreground">
          <ShieldAlert className="h-3.5 w-3.5" />
          {entry.install_hint
            ? t("settings.channels.config.sdkMissing", { hint: entry.install_hint })
            : t("settings.channels.config.sdkMissingNoHint")}
        </div>
      ) : null}

      <div className="flex flex-wrap items-center justify-between gap-3 rounded-md border bg-muted/20 px-3 py-2">
        <div>
          <div className={labelClass}>{t("settings.channels.config.enable")}</div>
          <div className={hintClass}>{t("settings.channels.config.enableHint")}</div>
        </div>
        <div className="flex items-center gap-2">
          <span className={`rounded-full px-2 py-0.5 text-xs ${enabled ? "bg-success/10 text-success" : "bg-muted text-muted-foreground"}`}>
            {enabled ? t("settings.channels.enabled") : t("settings.channels.disabled")}
          </span>
          {toggling ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" /> : null}
          <input
            type="checkbox"
            checked={enabled}
            onChange={(event) => void setEnabled(event.target.checked)}
            className="h-4 w-4 accent-primary"
            aria-label={t("settings.channels.config.enable")}
            disabled={!writable || toggling}
          />
        </div>
      </div>

      {enableAnyway ? (
        <div className="flex flex-wrap items-center gap-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <span className="min-w-0 flex-1">{error}</span>
          <button
            type="button"
            onClick={() => void setEnabled(true, { skipVerify: true })}
            disabled={toggling}
            className="inline-flex shrink-0 items-center gap-2 rounded-md border border-destructive/40 px-3 py-1.5 text-sm transition hover:bg-destructive/10 disabled:cursor-not-allowed disabled:opacity-60"
          >
            {t("settings.channels.config.enableAnyway")}
          </button>
          {errorDetail ? (
            <span className="w-full text-xs">
              {t("settings.channels.config.enableRejectedDetail", { detail: errorDetail })}
            </span>
          ) : null}
          <span className="w-full text-xs">{t("settings.channels.config.enableAnywayHint")}</span>
        </div>
      ) : error ? (
        <div className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive">
          <div>{error}</div>
          {errorDetail ? (
            <div className="mt-1 text-xs">
              {t("settings.channels.config.enableRejectedDetail", { detail: errorDetail })}
            </div>
          ) : null}
        </div>
      ) : null}

      <form onSubmit={submit} className="grid gap-4">
        {entry.fields.length ? (
          entry.fields.map(renderField)
        ) : (
          <p className="text-sm text-muted-foreground">
            {t("settings.channels.config.noFields")}
          </p>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <button
            type="button"
            onClick={() => void runTest()}
            disabled={!entry.supports_test || busy}
            className="inline-flex items-center justify-center gap-2 rounded-md border px-4 py-2 text-sm text-muted-foreground transition hover:bg-muted hover:text-foreground disabled:cursor-not-allowed disabled:opacity-60"
          >
            {testing ? <Loader2 className="h-4 w-4 animate-spin" /> : <PlugZap className="h-4 w-4" />}
            {testing ? t("settings.channels.config.testing") : t("settings.channels.config.test")}
          </button>
          <button
            type="submit"
            disabled={formDisabled || !isDirty}
            className="inline-flex items-center justify-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition hover:opacity-90 disabled:cursor-not-allowed disabled:opacity-70"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saving ? t("settings.saving") : t("settings.channels.config.save")}
          </button>
          <span className={hintClass}>{t("settings.channels.config.hotApply")}</span>
        </div>
      </form>

      {testResult ? (
        <div
          role="status"
          className={`rounded-md border px-3 py-2 text-sm ${
            testResult.ok
              ? "border-success/30 bg-success/5 text-success"
              : "border-warning/40 bg-warning/10 text-warning-foreground"
          }`}
        >
          <div className="flex items-center gap-2">
            {testResult.ok
              ? <CheckCircle2 className="h-4 w-4 shrink-0" />
              : <XCircle className="h-4 w-4 shrink-0" />}
            <span className="font-medium">{testCodeText[testResult.code]}</span>
          </div>
          {testResult.detail ? (
            <div className="mt-1 text-xs">{testResult.detail}</div>
          ) : null}
          <div className="mt-1 text-xs">
            {testResult.tested_saved_config
              ? t("settings.channels.config.testedSavedConfig")
              : t("settings.channels.config.testedDraftConfig")}
          </div>
        </div>
      ) : null}

      {guide ? (
        <div className="rounded-md border">
          <button
            type="button"
            onClick={() => setGuideOpen((current) => !current)}
            aria-expanded={guideOpen}
            className="flex w-full items-center gap-2 px-3 py-2 text-sm font-medium"
          >
            <ChevronRight
              className={`h-4 w-4 text-muted-foreground transition-transform ${guideOpen ? "rotate-90" : ""}`}
            />
            {guide.title}
          </button>
          {guideOpen ? (
            <div className="border-t px-3 py-3">
              <p className={hintClass}>{guide.intro}</p>
              <ol className="mt-2 grid list-decimal gap-1.5 ps-5 text-sm">
                {guide.steps.map((step) => <li key={step}>{step}</li>)}
              </ol>
              <a
                href={guide.docsUrl}
                target="_blank"
                rel="noreferrer"
                className="mt-3 inline-flex items-center gap-1.5 text-xs text-primary transition hover:underline"
              >
                <ExternalLink className="h-3.5 w-3.5" />
                {guide.docsLabel}
              </a>
            </div>
          ) : null}
        </div>
      ) : null}
    </div>
  );
}
