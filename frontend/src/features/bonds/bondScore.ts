import type { Bond } from "@/api/types";

export type BondRiskProfile = "conservative" | "normal" | "aggressive";

export const PROFILE_SCORE_WEIGHTS: Record<
  BondRiskProfile,
  { ytm: number; risk: number; liquidity: number }
> = {
  conservative: { ytm: 0.2, risk: 0.6, liquidity: 0.2 },
  normal: { ytm: 0.3, risk: 0.5, liquidity: 0.2 },
  aggressive: { ytm: 0.6, risk: 0.25, liquidity: 0.15 },
};

export function bondScoreForProfile(
  bond: Bond,
  profile: BondRiskProfile = "normal",
): number | null {
  const profileScore = bond.profile_scores?.[profile];
  if (profileScore != null) return profileScore;
  return bond.score;
}
