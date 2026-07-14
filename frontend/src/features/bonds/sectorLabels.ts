export const SECTOR_LABELS: Record<string, string> = {
  unknown: "Неизвестно",
  financial: "Финансы",
  real_estate: "Недвижимость",
  utilities: "Коммунальные",
  it: "IT",
  telecom: "Телеком",
  consumer: "Потребительский",
  materials: "Материалы",
  industrials: "Промышленность",
  energy: "Энергетика",
  government: "Государственные",
  health_care: "Здравоохранение",
  other: "Прочее",
  corp: "Корпоративный",
};

export function normalizeSectorKey(raw: string | null | undefined): string {
  const s = (raw ?? "").trim().toLowerCase();
  return s.length > 0 ? s : "unknown";
}

export function sectorLabel(raw: string | null | undefined): string {
  const trimmed = (raw ?? "").trim();
  if (!trimmed) return "—";
  const key = trimmed.toLowerCase();
  return SECTOR_LABELS[key] ?? trimmed;
}

export const SECTOR_FILTER_OPTIONS = Object.entries(SECTOR_LABELS)
  .filter(([value]) => value !== "unknown")
  .map(([value, label]) => ({ value, label }))
  .sort((a, b) => a.label.localeCompare(b.label, "ru"));
