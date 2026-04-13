import { getApiKey, removeApiKey } from "./auth";
import type {
  CronConfig,
  CronConfigRequest,
  ScrapeRunRequest,
  WebflowStatus,
} from "./types";

function getHeaders(): Record<string, string> {
  const h: Record<string, string> = { "Content-Type": "application/json" };
  const key = getApiKey();
  if (key) h["x-api-key"] = key;
  return h;
}

export const fetcher = async (url: string) => {
  const res = await fetch(url, { headers: getHeaders() });
  if (res.status === 401 || res.status === 403) {
    removeApiKey();
    window.location.href = "/login";
    return;
  }
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
};

async function post(path: string, body?: unknown) {
  const res = await fetch(path, {
    method: "POST",
    headers: getHeaders(),
    body: body !== undefined ? JSON.stringify(body) : undefined,
  });
  if (res.status === 401 || res.status === 403) {
    removeApiKey();
    window.location.href = "/login";
    return;
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string })?.detail || `Error (${res.status})`);
  }
  return res.json();
}

async function put(path: string, body: unknown) {
  const res = await fetch(path, {
    method: "PUT",
    headers: getHeaders(),
    body: JSON.stringify(body),
  });
  if (res.status === 401 || res.status === 403) {
    removeApiKey();
    window.location.href = "/login";
    return;
  }
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error((detail as { detail?: string })?.detail || `Error (${res.status})`);
  }
  return res.json();
}

// ── Scraper ───────────────────────────────────────────────────────────────────

export const runScraper = (body: ScrapeRunRequest) =>
  post("/api/scraper/run", body);

export const stopScraper = () => post("/api/scraper/stop");

// ── Session ───────────────────────────────────────────────────────────────────

export const renewSession = () => post("/api/session/renew");

export const cancelSession = () => post("/api/session/stop");

// ── Cron ──────────────────────────────────────────────────────────────────────

export const updateCron = (body: CronConfigRequest): Promise<CronConfig> =>
  put("/api/cron", body) as Promise<CronConfig>;

// ── Webflow ───────────────────────────────────────────────────────────────────

export const syncWebflow = (): Promise<WebflowStatus> =>
  post("/api/webflow/sync") as Promise<WebflowStatus>;
