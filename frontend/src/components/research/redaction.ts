export const REDACTED = "[REDACTED]";

const SECRET_KEY_FRAGMENTS = [
  "secret",
  "token",
  "api_key",
  "apikey",
  "password",
  "credential",
  "broker",
  "authorization",
  "cookie",
  "session",
  "private_key",
  "refresh_token",
  "access_token",
];

const BEARER_RE = /^\s*bearer\s+[A-Za-z0-9._~+/=-]{8,}\s*$/i;
const INLINE_BEARER_RE = /\bauthorization\s*:\s*bearer\s+[^\s,;]+|\bbearer\s+[A-Za-z0-9._~+/=-]{8,}/i;
const ENV_ASSIGNMENT_SECRET_RE = /\b[A-Z0-9_]*(?:SECRET|TOKEN|API_KEY|ACCESS_KEY|PRIVATE_KEY)[A-Z0-9_]*\s*=\s*[^\s,;]+/i;
const KEY_PREFIX_RE = /^\s*(sk|rk|pk|ghp|gho|ghu|github_pat)-[A-Za-z0-9_-]{8,}\s*$/i;

export function redactDisplayText(value: string): string {
  return isSecretLikeText(value) ? REDACTED : value;
}

export function redactDisplayValue(value: unknown): unknown {
  if (typeof value === "string") {
    return redactDisplayText(value);
  }
  if (Array.isArray(value)) {
    return value.map(redactDisplayValue);
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => {
        if (isSecretLikeText(key)) {
          return [REDACTED, REDACTED];
        }
        return [key, redactDisplayValue(item)];
      }),
    );
  }
  return value;
}

function isSecretLikeText(value: string): boolean {
  const lowered = value.toLowerCase();
  return (
    SECRET_KEY_FRAGMENTS.some((fragment) => lowered.includes(fragment)) ||
    BEARER_RE.test(value) ||
    INLINE_BEARER_RE.test(value) ||
    ENV_ASSIGNMENT_SECRET_RE.test(value) ||
    KEY_PREFIX_RE.test(value)
  );
}
