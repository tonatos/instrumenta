import type { BondListParams } from "@/api/types";
import type { SortingState } from "@tanstack/react-table";
import type { ScreenerRiskProfile } from "@/features/screener/screenerRiskProfile";

const SORTABLE_COLUMNS: Record<string, string> = {
  score: "score",
  ytm_net: "ytm_net",
  days_to_maturity: "days_to_maturity",
  volume_rub: "volume",
  name: "name",
};

export function sortByFromTable(sorting: SortingState): Pick<BondListParams, "sort_by" | "sort_desc"> {
  const col = sorting[0];
  if (!col) {
    return { sort_by: "score", sort_desc: true };
  }
  const sortBy = SORTABLE_COLUMNS[col.id] ?? "score";
  return { sort_by: sortBy, sort_desc: col.desc ?? false };
}

export function buildScreenerQueryParams(input: {
  filterBy: "effective" | "maturity";
  maxDays: number | "";
  minVolume: number | "";
  minYtm: number | "";
  maxLotPrice: number | "";
  couponTypes: string[];
  riskLevels: number[];
  sectors: string[];
  hideDefault: boolean;
  hideSubordinated: boolean;
  search: string;
  sorting: SortingState;
  riskProfile: ScreenerRiskProfile;
  page?: number;
  exportAll?: boolean;
}): BondListParams {
  const { sort_by, sort_desc } = sortByFromTable(input.sorting);
  const params: BondListParams = {
    filter_by: input.filterBy,
    hide_default: input.hideDefault,
    hide_subordinated: input.hideSubordinated,
    sort_by,
    sort_desc,
    risk_profile: input.riskProfile,
  };
  if (input.maxDays !== "") params.max_days = input.maxDays;
  if (input.minVolume !== "") params.min_volume_rub = input.minVolume;
  if (input.minYtm !== "") params.min_ytm_net = input.minYtm;
  if (input.maxLotPrice !== "" && input.maxLotPrice > 0) {
    params.max_lot_price_rub = input.maxLotPrice;
  }
  if (input.couponTypes.length > 0) params.coupon_types = input.couponTypes;
  if (input.riskLevels.length > 0) params.risk_levels = input.riskLevels;
  if (input.sectors.length > 0) params.sectors = input.sectors;
  if (input.search.trim()) params.q = input.search.trim();
  if (input.page != null) params.page = input.page;
  if (input.exportAll) params.export = true;
  return params;
}
