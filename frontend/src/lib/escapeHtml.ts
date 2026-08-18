/**
 * Escape a string for safe interpolation into an HTML context.
 *
 * ECharts injects the string returned by a custom tooltip `formatter` via
 * `innerHTML` WITHOUT escaping (the default tooltip renderer escapes via
 * `encodeHTML`, but custom formatter return values are injected verbatim).
 * Artifact-derived strings — positions.csv column headers, date cells, factor
 * directory names, equity timestamps — are attacker-influenceable via crafted
 * run directories, and the API key lives in localStorage, so an XSS in a chart
 * tooltip escalates to full API control. Every such value interpolated into a
 * tooltip/label formatter must pass through this helper first.
 *
 * `&` MUST be replaced first, otherwise the entities introduced by the later
 * replacements would be double-escaped.
 */
export function escapeHtml(value: string): string {
  return value
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}
