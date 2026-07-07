import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export function formatRub(value: number | null | undefined): string {
  if (value == null || Number.isNaN(value)) return "—";
  return new Intl.NumberFormat("ru-RU", {
    style: "currency",
    currency: "RUB",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatPct(value: number | null | undefined, digits = 2): string {
  if (value == null || Number.isNaN(value)) return "—";
  return `${value.toFixed(digits)}%`;
}

const RU_MONTHS_GENITIVE = [
  "",
  "января",
  "февраля",
  "марта",
  "апреля",
  "мая",
  "июня",
  "июля",
  "августа",
  "сентября",
  "октября",
  "ноября",
  "декабря",
] as const;

function parseIsoDate(value: string): { year: number; month: number; day: number } | null {
  const match = /^(\d{4})-(\d{2})-(\d{2})/.exec(value);
  if (!match) return null;
  return {
    year: Number(match[1]),
    month: Number(match[2]),
    day: Number(match[3]),
  };
}

/** Local calendar date as YYYY-MM-DD (no timezone shift). */
export function todayIsoDate(referenceDate: Date = new Date()): string {
  return dateToIso(referenceDate);
}

export function isoToDate(value: string | null | undefined): Date | undefined {
  const parsed = value ? parseIsoDate(value) : null;
  if (!parsed) return undefined;
  return new Date(parsed.year, parsed.month - 1, parsed.day);
}

export function dateToIso(date: Date): string {
  const year = date.getFullYear();
  const month = String(date.getMonth() + 1).padStart(2, "0");
  const day = String(date.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

/** Human-readable Russian date: «28 июля» or «28 июля 2027». */
export function formatDate(
  value: string | null | undefined,
  referenceDate: Date = new Date(),
): string {
  if (!value) return "—";
  const parsed = parseIsoDate(value);
  if (!parsed) return value;
  const monthName = RU_MONTHS_GENITIVE[parsed.month];
  if (!monthName) return value;
  if (parsed.year === referenceDate.getFullYear()) {
    return `${parsed.day} ${monthName}`;
  }
  return `${parsed.day} ${monthName} ${parsed.year}`;
}
