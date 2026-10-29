// i18n key for each reasoning effort level; a level missing here has no label.
export const EFFORT_LABEL_KEYS = {
  none: "settings.reasoningEffortNone",
  minimal: "settings.reasoningEffortMinimal",
  ultra: "settings.reasoningEffortUltra",
  persistent: "settings.reasoningEffortPersistent",
  low: "settings.reasoningEffortLow",
  medium: "settings.reasoningEffortMedium",
  high: "settings.reasoningEffortHigh",
  xhigh: "settings.reasoningEffortXhigh",
  max: "settings.reasoningEffortMax",
} as const;

export function effortLabelKey(level: string) {
  return EFFORT_LABEL_KEYS[level as keyof typeof EFFORT_LABEL_KEYS];
}
