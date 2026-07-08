const SECRET_KEY_RE = /(api[_-]?key|authorization|bearer|client[_-]?secret|password|passphrase|private[_-]?key|secret|token)/i;
const DANGEROUS_URI_RE = /\b(?:javascript|vbscript|data)\s*:/gi;
const CONTROL_CHARS_RE = /[\u0000-\u0008\u000b\u000c\u000e-\u001f\u007f]/g;

export type AlphaGenesisDecision =
  | "reject"
  | "research_only"
  | "candidate_zoo"
  | "paper_candidate"
  | "forward_track";

export function sanitizeAlphaGenesisText(value: unknown): string {
  return String(value ?? "")
    .replace(CONTROL_CHARS_RE, "")
    .replace(DANGEROUS_URI_RE, (scheme) => scheme.replace(":", "\\:"))
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function sanitizePastedMarkdown(value: string): string {
  return sanitizeAlphaGenesisText(value).replace(/([[\]()])/g, "\\$1");
}

export function redactAlphaGenesisReport<T>(value: T): T {
  if (Array.isArray(value)) {
    return value.map((item) => redactAlphaGenesisReport(item)) as T;
  }
  if (value && typeof value === "object") {
    const result: Record<string, unknown> = {};
    for (const [key, nested] of Object.entries(value)) {
      result[key] = SECRET_KEY_RE.test(key) ? "[redacted]" : redactAlphaGenesisReport(nested);
    }
    return result as T;
  }
  return value;
}

export function sanitizeImagePreviewMetadata(metadata: Record<string, unknown>): Record<string, unknown> {
  const blockedKeys = /(gps|location|ocr|prompt|comment|description|software|path|filename|file_path)/i;
  const result: Record<string, unknown> = {};
  for (const [key, value] of Object.entries(metadata)) {
    if (SECRET_KEY_RE.test(key) || blockedKeys.test(key)) {
      result[key] = "[redacted]";
    } else {
      result[key] = typeof value === "string" ? sanitizeAlphaGenesisText(value) : redactAlphaGenesisReport(value);
    }
  }
  return result;
}

export function alphaGenesisDecisionBadge(decision: AlphaGenesisDecision) {
  const labels: Record<AlphaGenesisDecision, string> = {
    reject: "Reject",
    research_only: "Research Only",
    candidate_zoo: "Candidate Zoo",
    paper_candidate: "Paper Candidate",
    forward_track: "Forward Track",
  };
  return {
    label: labels[decision],
    researchOnly: true,
    liveReady: false,
    productionReady: false,
  };
}

export function shouldCacheAlphaGenesisReport(requestUrl: string, payload?: unknown): boolean {
  if (/\/api\/alpha-genesis\//.test(requestUrl)) return false;
  if (payload && typeof payload === "object") {
    const schema = (payload as { schema_version?: unknown }).schema_version;
    if (typeof schema === "string" && schema.startsWith("alpha_")) return false;
  }
  return true;
}
