import { useQuery } from "@tanstack/react-query";
import { api } from "@/api/client";
import { STALE } from "@/features/portfolio/hooks/queryConfig";

export function useAccountOperations(
  portfolioId: string | null | undefined,
  enabled: boolean,
) {
  return useQuery({
    queryKey: ["account-operations", portfolioId],
    queryFn: () => api.getAccountOperations(portfolioId!),
    enabled: Boolean(portfolioId) && enabled,
    staleTime: STALE.accountOperations,
    refetchOnWindowFocus: false,
  });
}
