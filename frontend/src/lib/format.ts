import type { MetricCard } from "./api";

export function metricText(card: Pick<MetricCard, "value" | "value_state">): string {
  if (card.value_state === "missing") return "No data";
  if (card.value_state === "zero_denominator") return "Undefined";
  if (card.value === null || card.value === undefined) return "—";
  return String(card.value);
}

export function roleLabel(role: string): string {
  return role.replaceAll("_", " ");
}
