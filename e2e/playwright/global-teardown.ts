import { request } from "@playwright/test";
import { cleanupE2ePortfolios } from "./tests/live/api-helpers";

export default async function globalTeardown(): Promise<void> {
  const baseURL = process.env.BASE_URL || "http://localhost:5173";
  const api = await request.newContext({ baseURL });
  try {
    await cleanupE2ePortfolios(api);
  } finally {
    await api.dispose();
  }
}
