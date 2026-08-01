export type ManifestTranslation = (
  key: string,
  options?: Record<string, string | number>,
) => string;

export const STATUS_TRANSLATION_KEYS = {
  waiting: "swarm.status.waiting",
  running: "swarm.status.running",
  done: "swarm.status.done",
  failed: "swarm.status.failed",
  blocked: "swarm.status.blocked",
  retry: "swarm.status.retry",
  cancelled: "swarm.status.cancelled",
  pending: "swarm.status.pending",
  completed: "swarm.status.completed",
  unknown: "swarm.status.unknown",
} as const;

const PRESET_WELCOME_KEYS: Record<string, string> = {
  investment_committee: "welcome.examples.investmentCommittee",
  quant_strategy_desk: "welcome.examples.quantStrategyDesk",
  value_investing_committee: "welcome.examples.valueCommittee",
};

export function localizeStatus(
  status: keyof typeof STATUS_TRANSLATION_KEYS,
  t: ManifestTranslation,
): string {
  return t(STATUS_TRANSLATION_KEYS[status]);
}

export function localizePreset(
  preset: string,
  t: ManifestTranslation,
): string {
  const humanized = preset
    .replace(/_/g, " ")
    .replace(/^\p{L}/u, (letter) => letter.toLocaleUpperCase());
  const welcomeKey = PRESET_WELCOME_KEYS[preset];
  const fallback = welcomeKey
    ? t(welcomeKey, { defaultValue: humanized })
    : humanized;

  return t(`swarm.presets.${preset}`, { defaultValue: fallback });
}
