export function assertFiniteNumbers(value: unknown, path = "export"): void {
  if (typeof value === "number") {
    if (!Number.isFinite(value)) throw new Error(`${path} must contain finite numbers`);
    return;
  }
  if (Array.isArray(value)) {
    value.forEach((item, index) => assertFiniteNumbers(item, `${path}[${index}]`));
    return;
  }
  if (value && typeof value === "object") {
    Object.entries(value).forEach(([key, item]) => assertFiniteNumbers(item, `${path}.${key}`));
  }
}

export function csvText(value: string): string {
  const safe = /^\s*[=+\-@]/.test(value) ? `'${value}` : value;
  return /[",\r\n]/.test(safe) ? `"${safe.replace(/"/g, '""')}"` : safe;
}
