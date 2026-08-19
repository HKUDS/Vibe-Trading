import type { AgentCapabilities, CapabilityItem } from "@/lib/api";

export type SlashKind = "root" | "skills" | "tools" | "commands";
export interface SlashContext { kind: SlashKind; query: string; start: number; }

export function getSlashContext(value: string, cursor: number): SlashContext | null {
  const match = value.slice(0, cursor).match(/(?:^|\s)(\/[^\s]*)$/);
  if (!match) return null;
  const token = match[1];
  const normalized = token.slice(1).toLowerCase();
  const start = cursor - token.length;
  if (!normalized) return { kind: "root", query: "", start };
  if (normalized === "command" || normalized === "commands") return { kind: "commands", query: "", start };
  if (normalized === "skill" || normalized === "skills") return { kind: "skills", query: "", start };
  if (normalized === "tool" || normalized === "tools") return { kind: "tools", query: "", start };
  if (normalized.startsWith("skill/")) return { kind: "skills", query: normalized.slice(6), start };
  if (normalized.startsWith("tool/")) return { kind: "tools", query: normalized.slice(5), start };
  return null;
}

export function filterCapabilities(items: CapabilityItem[], query: string): CapabilityItem[] {
  const lowered = query.trim().toLowerCase();
  if (!lowered) return items;
  return items.filter((item) => `${item.name} ${item.description} ${item.category}`.toLowerCase().includes(lowered));
}

export function capabilityCategoryNames(capabilities: AgentCapabilities | null): string[] {
  return [...new Set((capabilities?.skills ?? []).map((item) => item.category))];
}
