const SECRET_VALUE_PATTERN =
  /(sk-[a-z0-9_-]+|bearer\s+[a-z0-9._-]+|api[_-]?key\s*[:=]\s*[^,\s]+|token\s*[:=]\s*[^,\s]+|password\s*[:=]\s*[^,\s]+)/i;

export function redactResearchText(value: unknown): string {
  const text = String(value ?? "");
  return SECRET_VALUE_PATTERN.test(text) ? "[REDACTED]" : text;
}
