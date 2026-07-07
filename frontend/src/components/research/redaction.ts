const SECRET_VALUE_PATTERN =
  /(sk-[a-z0-9_-]+|bearer\s+[a-z0-9._~+/=-]+|(api[_-]?key|token|password|credential|secret|authorization|broker[_-]?password)\s*[:=]\s*[^,\s]+)/i;

const SECRET_KEY_PATTERN = /(api[_-]?key|token|password|credential|secret|authorization|broker[_-]?password)/i;

export function redactResearchText(value: unknown): string {
  const text = String(value ?? "");
  return SECRET_VALUE_PATTERN.test(text) ? "[REDACTED]" : text;
}

export function redactResearchPayload(value: unknown): unknown {
  if (Array.isArray(value)) {
    return value.map((item) => redactResearchPayload(item));
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(
      Object.entries(value as Record<string, unknown>).map(([key, item]) => [
        key,
        SECRET_KEY_PATTERN.test(key) ? "[REDACTED]" : redactResearchPayload(item),
      ]),
    );
  }
  if (typeof value === "string") {
    return redactResearchText(value);
  }
  return value;
}

export function researchPayloadToMarkdown(value: unknown): string {
  return toMarkdown(redactResearchPayload(value));
}

function toMarkdown(value: unknown, depth = 0): string {
  const prefix = "  ".repeat(depth);
  if (Array.isArray(value)) {
    return value.map((item) => `${prefix}- ${inlineMarkdown(item, depth + 1)}`).join("\n");
  }
  if (value && typeof value === "object") {
    return Object.entries(value as Record<string, unknown>)
      .map(([key, item]) => `${prefix}${key}: ${inlineMarkdown(item, depth + 1)}`)
      .join("\n");
  }
  return `${prefix}${String(value ?? "")}`;
}

function inlineMarkdown(value: unknown, depth: number): string {
  if (Array.isArray(value) || (value && typeof value === "object")) {
    return `\n${toMarkdown(value, depth)}`;
  }
  return String(value ?? "");
}
