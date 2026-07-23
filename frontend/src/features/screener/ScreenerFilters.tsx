import { ChevronDown, ChevronUp, RotateCcw, Search } from "lucide-react";
import type { ReactNode } from "react";
import { SECTOR_FILTER_OPTIONS } from "@/features/bonds/sectorLabels";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { MultiSelect } from "@/components/ui/multi-select";
import { cn } from "@/lib/utils";

const COUPON_OPTIONS = [
  { value: "fixed", label: "Фиксированный" },
  { value: "floating", label: "Плавающий" },
  { value: "variable", label: "Переменный" },
  { value: "unknown", label: "Неизвестен" },
];

const RISK_LEVEL_OPTIONS = [
  { value: "1", label: "Низкий" },
  { value: "2", label: "Умеренный" },
  { value: "3", label: "Высокий" },
  { value: "0", label: "Неизвестен" },
];

export interface ScreenerFiltersProps {
  filtersExpanded: boolean;
  onToggleExpanded: () => void;
  activeFilterCount: number;
  onReset: () => void;

  searchInput: string;
  onSearchChange: (value: string) => void;

  filterBy: "effective" | "maturity";
  onFilterByChange: (value: "effective" | "maturity") => void;

  maxDays: number | "";
  onMaxDaysChange: (value: number | "") => void;

  minVolume: number | "";
  onMinVolumeChange: (value: number | "") => void;
  /** Config default — для бейджа «Дополнительно». */
  defaultMinVolume?: number;

  minYtm: number | "";
  onMinYtmChange: (value: number | "") => void;

  maxLotPrice: number | "";
  onMaxLotPriceChange: (value: number | "") => void;

  couponTypes: string[];
  onCouponTypesChange: (values: string[]) => void;

  riskLevels: number[];
  onRiskLevelsChange: (values: number[]) => void;

  sectors: string[];
  onSectorsChange: (values: string[]) => void;

  hideDefault: boolean;
  onHideDefaultChange: (value: boolean) => void;

  hideSubordinated: boolean;
  onHideSubordinatedChange: (value: boolean) => void;

  advancedOpen: boolean;
  onAdvancedOpenChange: (open: boolean) => void;
}

function FieldLabel({
  htmlFor,
  className,
  children,
}: {
  htmlFor?: string;
  className?: string;
  children: ReactNode;
}) {
  return (
    <label
      htmlFor={htmlFor}
      className={cn("mb-1.5 block text-xs font-medium text-muted-foreground", className)}
    >
      {children}
    </label>
  );
}

export function ScreenerFilters({
  filtersExpanded,
  onToggleExpanded,
  activeFilterCount,
  onReset,
  searchInput,
  onSearchChange,
  filterBy,
  onFilterByChange,
  maxDays,
  onMaxDaysChange,
  minVolume,
  onMinVolumeChange,
  defaultMinVolume = 0,
  minYtm,
  onMinYtmChange,
  maxLotPrice,
  onMaxLotPriceChange,
  couponTypes,
  onCouponTypesChange,
  riskLevels,
  onRiskLevelsChange,
  sectors,
  onSectorsChange,
  hideDefault,
  onHideDefaultChange,
  hideSubordinated,
  onHideSubordinatedChange,
  advancedOpen,
  onAdvancedOpenChange,
}: ScreenerFiltersProps) {
  const advancedActiveCount =
    (minVolume !== "" && minVolume !== defaultMinVolume ? 1 : 0) +
    (couponTypes.length > 0 ? 1 : 0) +
    (riskLevels.length > 0 ? 1 : 0) +
    (sectors.length > 0 ? 1 : 0) +
    (maxLotPrice !== "" && maxLotPrice !== 0 ? 1 : 0) +
    (hideSubordinated ? 1 : 0) +
    (!hideDefault ? 1 : 0);

  return (
    <Card data-testid="screener-filters">
      <CardHeader className="space-y-3 pb-3 pt-4">
        <div className="flex items-center justify-between gap-2">
          <button
            type="button"
            className="flex min-h-10 min-w-0 flex-1 items-center gap-2 text-left md:pointer-events-none"
            onClick={onToggleExpanded}
            data-testid="screener-filters-toggle"
            aria-expanded={filtersExpanded}
          >
            <CardTitle className="text-sm font-semibold">Фильтры</CardTitle>
            {!filtersExpanded && activeFilterCount > 0 && (
              <Badge variant="secondary" className="text-xs">
                {activeFilterCount}
              </Badge>
            )}
            <span className="md:hidden" aria-hidden>
              {filtersExpanded ? (
                <ChevronUp className="h-4 w-4 text-muted-foreground" />
              ) : (
                <ChevronDown className="h-4 w-4 text-muted-foreground" />
              )}
            </span>
          </button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onReset}
            className="h-10 shrink-0 gap-1.5 px-3 text-xs"
          >
            <RotateCcw className="h-3.5 w-3.5" />
            Сбросить
          </Button>
        </div>

        {/* Primary row: search + YTM + days/horizon */}
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end">
          <div className="min-w-0 flex-1">
            <FieldLabel htmlFor="screener-search" className="sr-only">
              Поиск
            </FieldLabel>
            <div className="relative">
              <Search
                className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                id="screener-search"
                className="h-10 pl-9"
                placeholder="Поиск по названию, SECID или ISIN…"
                value={searchInput}
                onChange={(e) => onSearchChange(e.target.value)}
                aria-label="Поиск облигаций"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-3 sm:flex sm:shrink-0">
            <div className="min-w-0 sm:w-[7.5rem]">
              <FieldLabel htmlFor="screener-min-ytm">Мин. YTM, %</FieldLabel>
              <Input
                id="screener-min-ytm"
                type="number"
                min={0}
                step={0.1}
                value={minYtm}
                onChange={(e) =>
                  onMinYtmChange(e.target.value === "" ? "" : Number(e.target.value))
                }
                placeholder="0"
                className="h-10"
                aria-label="Мин. YTM нетто"
              />
            </div>

            <div className="min-w-0 sm:w-[15.5rem]">
              <FieldLabel htmlFor="screener-max-days">Макс. дней</FieldLabel>
              <div className="flex h-10 overflow-hidden rounded-md border border-border bg-card shadow-sm focus-within:ring-1 focus-within:ring-ring">
                <Input
                  id="screener-max-days"
                  type="number"
                  min={1}
                  value={maxDays}
                  onChange={(e) =>
                    onMaxDaysChange(e.target.value === "" ? "" : Number(e.target.value))
                  }
                  placeholder="∞"
                  className="h-full min-w-0 flex-1 rounded-none border-0 shadow-none focus-visible:ring-0"
                  aria-label="Макс. дней до погашения"
                />
                <select
                  aria-label="Как считать срок"
                  className="h-full w-[6.75rem] shrink-0 border-0 border-l border-border bg-muted/40 px-2 text-xs focus:outline-none sm:w-[7.5rem] sm:text-sm"
                  value={filterBy}
                  onChange={(e) =>
                    onFilterByChange(e.target.value as "effective" | "maturity")
                  }
                >
                  <option value="effective">До оферты</option>
                  <option value="maturity">До погашения</option>
                </select>
              </div>
            </div>
          </div>
        </div>
      </CardHeader>

      {filtersExpanded && (
        <CardContent className="space-y-3 border-t border-border pt-3">
          <button
            type="button"
            className="flex min-h-10 w-full items-center justify-between gap-2 text-left text-sm"
            onClick={() => onAdvancedOpenChange(!advancedOpen)}
            aria-expanded={advancedOpen}
            data-testid="screener-filters-advanced-toggle"
          >
            <span className="flex items-center gap-2 font-medium">
              Дополнительно
              {advancedActiveCount > 0 && !advancedOpen && (
                <Badge variant="secondary" className="text-[10px] tabular-nums">
                  {advancedActiveCount}
                </Badge>
              )}
            </span>
            {advancedOpen ? (
              <ChevronUp className="h-4 w-4 text-muted-foreground" aria-hidden />
            ) : (
              <ChevronDown className="h-4 w-4 text-muted-foreground" aria-hidden />
            )}
          </button>

          {advancedOpen && (
            <div className="space-y-4">
              {/* Ликвидность / инструмент */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div className="min-w-0">
                  <FieldLabel htmlFor="screener-min-volume">Мин. объём, ₽</FieldLabel>
                  <Input
                    id="screener-min-volume"
                    type="number"
                    min={0}
                    value={minVolume}
                    onChange={(e) =>
                      onMinVolumeChange(e.target.value === "" ? "" : Number(e.target.value))
                    }
                    placeholder="0"
                    className="h-10"
                    aria-label="Мин. объём торгов"
                  />
                </div>
                <div className="min-w-0">
                  <FieldLabel htmlFor="screener-max-lot">Макс. стоимость лота, ₽</FieldLabel>
                  <Input
                    id="screener-max-lot"
                    type="number"
                    min={0}
                    value={maxLotPrice}
                    onChange={(e) =>
                      onMaxLotPriceChange(e.target.value === "" ? "" : Number(e.target.value))
                    }
                    placeholder="0 — без ограничения"
                    className="h-10"
                    aria-label="Макс. стоимость лота"
                  />
                </div>
                <div className="min-w-0 sm:col-span-2 lg:col-span-1">
                  <FieldLabel>Тип купона</FieldLabel>
                  <MultiSelect
                    options={COUPON_OPTIONS}
                    values={couponTypes}
                    onChange={onCouponTypesChange}
                    placeholder="Все типы"
                    aria-label="Тип купона"
                    data-testid="screener-filter-coupon"
                  />
                </div>
                <div className="min-w-0 sm:col-span-2 lg:col-span-1">
                  <FieldLabel>Сектор</FieldLabel>
                  <MultiSelect
                    options={SECTOR_FILTER_OPTIONS}
                    values={sectors}
                    onChange={onSectorsChange}
                    placeholder="Все секторы"
                    searchable
                    searchPlaceholder="Найти сектор…"
                    aria-label="Сектор"
                    data-testid="screener-filter-sector"
                  />
                </div>
              </div>

              {/* Риск / исключения */}
              <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
                <div className="min-w-0">
                  <FieldLabel>Уровень риска</FieldLabel>
                  <MultiSelect
                    options={RISK_LEVEL_OPTIONS}
                    values={riskLevels.map(String)}
                    onChange={(vals) => onRiskLevelsChange(vals.map(Number))}
                    placeholder="Все уровни"
                    aria-label="Уровень риска"
                    data-testid="screener-filter-risk"
                  />
                </div>
                <div className="flex min-w-0 flex-col justify-end">
                  <span className="mb-1.5 block text-xs leading-none opacity-0" aria-hidden>
                    &nbsp;
                  </span>
                  <label className="flex h-10 cursor-pointer items-center gap-2.5 text-sm">
                    <Checkbox
                      checked={hideDefault}
                      onCheckedChange={(c) => onHideDefaultChange(!!c)}
                    />
                    Скрыть дефолтные
                  </label>
                </div>
                <div className="flex min-w-0 flex-col justify-end sm:col-span-2 lg:col-span-1">
                  <span className="mb-1.5 block text-xs leading-none opacity-0" aria-hidden>
                    &nbsp;
                  </span>
                  <label className="flex h-10 cursor-pointer items-center gap-2.5 text-sm">
                    <Checkbox
                      checked={hideSubordinated}
                      onCheckedChange={(c) => onHideSubordinatedChange(!!c)}
                    />
                    Скрыть субординированные
                  </label>
                </div>
              </div>
            </div>
          )}
        </CardContent>
      )}
    </Card>
  );
}
