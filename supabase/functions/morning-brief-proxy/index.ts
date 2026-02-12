// Intelligems Analytics — Morning Brief Proxy
// Supabase Edge Function that fetches data from the Intelligems API,
// runs analysis logic, and returns structured JSON for the browser.

// ── Config ──────────────────────────────────────────────────────────

const API_BASE = "https://api.intelligems.io/v25-10-beta";
const REQUEST_DELAY = 1000; // ms between requests
const MAX_RETRIES = 3;
const RETRY_BASE_DELAY = 5000; // ms, doubles each retry
const MIN_RUNTIME_DAYS = 10;
const VERDICT_MIN_ORDERS = 30;
const MAX_EXPERIMENTS = 10;

const ALLOWED_ORIGIN = "https://victorpay1.github.io";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Content-Type": "application/json",
};

// ── API Client ──────────────────────────────────────────────────────

async function apiFetch(
  url: string,
  apiKey: string,
  params?: Record<string, string>
): Promise<Record<string, unknown>> {
  const queryString = params
    ? "?" + new URLSearchParams(params).toString()
    : "";

  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    const res = await fetch(`${url}${queryString}`, {
      headers: {
        "intelligems-access-token": apiKey,
        "Content-Type": "application/json",
      },
    });

    if (res.status === 429) {
      const wait = RETRY_BASE_DELAY * Math.pow(2, attempt);
      await sleep(wait);
      continue;
    }

    if (res.status === 401 || res.status === 403) {
      throw new Error("INVALID_KEY");
    }

    if (!res.ok) {
      throw new Error(`API error: ${res.status}`);
    }

    return await res.json();
  }

  throw new Error("RATE_LIMITED");
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

// ── Metric helpers (ported from ig_metrics.py) ──────────────────────

interface MetricData {
  value?: number | null;
  uplift?: { value?: number | null };
  p2bb?: number | null;
}

interface MetricRow {
  variation_id?: string;
  [key: string]: unknown;
}

function getMetricUplift(
  metrics: MetricRow[],
  metricName: string,
  variationId: string
): number | null {
  for (const m of metrics) {
    if (m.variation_id === variationId) {
      const data = m[metricName] as MetricData | undefined;
      if (data && typeof data === "object" && data.uplift) {
        return data.uplift.value ?? null;
      }
    }
  }
  return null;
}

function getMetricConfidence(
  metrics: MetricRow[],
  metricName: string,
  variationId: string
): number | null {
  for (const m of metrics) {
    if (m.variation_id === variationId) {
      const data = m[metricName] as MetricData | undefined;
      if (data && typeof data === "object") {
        return data.p2bb ?? null;
      }
    }
  }
  return null;
}

function getTotalVisitors(metrics: MetricRow[]): number {
  let total = 0;
  for (const m of metrics) {
    const v = m.n_visitors as MetricData | undefined;
    if (v && typeof v === "object") {
      total += (v.value as number) || 0;
    }
  }
  return Math.floor(total);
}

function getTotalOrders(metrics: MetricRow[]): number {
  let total = 0;
  for (const m of metrics) {
    const o = m.n_orders as MetricData | undefined;
    if (o && typeof o === "object") {
      total += (o.value as number) || 0;
    }
  }
  return Math.floor(total);
}

function hasCOGSData(metrics: MetricRow[]): boolean {
  for (const m of metrics) {
    const pct = m.pct_revenue_with_cogs as MetricData | undefined;
    if (pct && typeof pct === "object") {
      const val = pct.value;
      if (val && val > 0) return true;
    }
  }
  return false;
}

function primaryRevenueMetric(metrics: MetricRow[]): string {
  return hasCOGSData(metrics)
    ? "gross_profit_per_visitor"
    : "net_revenue_per_visitor";
}

// ── Helpers (ported from ig_helpers.py) ─────────────────────────────

interface Variation {
  id: string;
  name?: string;
  isControl?: boolean;
}

interface Experiment {
  id: string;
  name?: string;
  startedAtTs?: number;
  startedAt?: number;
  variations?: Variation[];
  testTypes?: Record<string, boolean>;
  type?: string;
}

function findVariants(variations: Variation[]): Variation[] {
  return variations.filter((v) => !v.isControl);
}

function getVariationName(variations: Variation[], variationId: string): string {
  for (const v of variations) {
    if (v.id === variationId) return v.name || "Unknown";
  }
  return "Unknown";
}

function runtimeDays(startedTs: number | null | undefined): number {
  if (!startedTs) return 0;
  const start = new Date(startedTs);
  const now = new Date();
  const days = Math.floor(
    (now.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)
  );
  return Math.max(days, 0);
}

function runtimeDisplay(startedTs: number | null | undefined): string {
  const days = runtimeDays(startedTs);
  if (days === 0) return "< 1 day";
  if (days === 1) return "1 day";
  return `${days} days`;
}

function fmtLift(lift: number | null): string {
  if (lift === null || lift === undefined) return "\u2014";
  const sign = lift > 0 ? "+" : "";
  return `${sign}${(lift * 100).toFixed(1)}%`;
}

function fmtConfidence(p2bb: number | null): string {
  if (p2bb === null || p2bb === undefined) return "Low data";
  return `${Math.round(p2bb * 100)}%`;
}

function detectTestType(exp: Experiment): string {
  const tt = exp.testTypes || {};
  if (tt.hasTestPricing) return "Pricing";
  if (tt.hasTestShipping) return "Shipping";
  if (tt.hasTestCampaign) return "Offer";
  if (
    tt.hasTestContent ||
    tt.hasTestContentAdvanced ||
    tt.hasTestContentTemplate ||
    tt.hasTestContentOnsite ||
    tt.hasTestContentUrl ||
    tt.hasTestContentTheme
  )
    return "Content";
  const expType = exp.type || "";
  if (expType.includes("pricing")) return "Pricing";
  if (expType.includes("shipping")) return "Shipping";
  if (expType.includes("offer")) return "Offer";
  return "Content";
}

function dailyVisitorsRate(totalVisitors: number, runtime: number): number {
  if (runtime <= 0) return 0;
  return totalVisitors / runtime;
}

function dailyOrdersRate(totalOrders: number, runtime: number): number {
  if (runtime <= 0) return 0;
  return totalOrders / runtime;
}

function daysToTargetOrders(
  currentOrders: number,
  targetOrders: number,
  dailyOrderRate: number
): number | null {
  if (dailyOrderRate <= 0) return null;
  const remaining = targetOrders - currentOrders;
  if (remaining <= 0) return 0;
  return Math.floor(remaining / dailyOrderRate) + 1;
}

// ── Health status (ported from brief.py) ────────────────────────────

function computeHealth(
  runtime: number,
  totalOrders: number,
  dailyVisRate: number,
  bestPrimaryLift: number | null,
  bestPrimaryConf: number | null,
  bestConvLift: number | null,
  bestConvConf: number | null
): { status: string; action: string } {
  if (runtime < 3) {
    return { status: "RED", action: "Just started \u2014 verify test setup is correct" };
  }

  if (runtime >= 3 && totalOrders === 0) {
    return {
      status: "RED",
      action: `Zero orders after ${runtime} days \u2014 check test setup`,
    };
  }

  if (bestConvLift !== null && bestConvConf !== null) {
    if (bestConvLift < -0.2 && bestConvConf >= 0.8) {
      return {
        status: "RED",
        action: `Conversion dropping ${fmtLift(bestConvLift)} \u2014 consider pausing`,
      };
    }
  }

  if (runtime < MIN_RUNTIME_DAYS) {
    return {
      status: "YELLOW",
      action: `Only ${runtime} days in \u2014 needs more data (min ${MIN_RUNTIME_DAYS})`,
    };
  }

  if (bestPrimaryLift !== null && bestPrimaryConf !== null) {
    if (bestPrimaryLift < 0 && bestPrimaryConf >= 0.6 && bestPrimaryConf < 0.8) {
      return {
        status: "YELLOW",
        action: `Trending negative (${fmtLift(bestPrimaryLift)}) \u2014 monitor closely`,
      };
    }
  }

  if (dailyVisRate < 50) {
    return {
      status: "YELLOW",
      action: `Low traffic (${Math.round(dailyVisRate)} visitors/day) \u2014 will take longer`,
    };
  }

  if (
    bestPrimaryConf !== null &&
    bestPrimaryConf >= 0.8 &&
    bestPrimaryLift !== null &&
    bestPrimaryLift > 0.02 &&
    totalOrders >= VERDICT_MIN_ORDERS
  ) {
    return {
      status: "GREEN",
      action: `Strong signal (${fmtLift(bestPrimaryLift)} at ${fmtConfidence(bestPrimaryConf)} confidence) \u2014 close to callable`,
    };
  }

  if (
    bestPrimaryConf !== null &&
    bestPrimaryConf >= 0.6 &&
    bestPrimaryLift !== null &&
    bestPrimaryLift > 0.02
  ) {
    return {
      status: "GREEN",
      action: `Emerging winner (${fmtLift(bestPrimaryLift)}) \u2014 gathering more data`,
    };
  }

  return { status: "GREEN", action: "Gathering data on track" };
}

// ── Best variant finder (ported from brief.py) ──────────────────────

function findBestVariant(
  metrics: MetricRow[],
  variations: Variation[],
  metricName: string
): { name: string | null; lift: number | null; confidence: number | null } {
  const variants = findVariants(variations);
  if (!variants.length) return { name: null, lift: null, confidence: null };

  let bestName: string | null = null;
  let bestLift: number | null = null;
  let bestConf: number | null = null;

  for (const v of variants) {
    const lift = getMetricUplift(metrics, metricName, v.id);
    const conf = getMetricConfidence(metrics, metricName, v.id);

    if (lift === null) continue;

    if (bestLift === null || lift > bestLift) {
      bestLift = lift;
      bestConf = conf;
      bestName = getVariationName(variations, v.id);
    }
  }

  return { name: bestName, lift: bestLift, confidence: bestConf };
}

// ── Main handler ────────────────────────────────────────────────────

interface TestCard {
  name: string;
  status: string;
  action: string;
  type: string;
  runtimeDisplay: string;
  visitors: number;
  orders: number;
  dailyVisitors: number;
  dailyOrders: number;
  bestVariant: string | null;
  primaryMetricLabel: string;
  primaryLift: string | null;
  primaryConfidence: string | null;
  convLift: string | null;
  convConfidence: string | null;
  daysToVerdict: number | null;
}

const STATUS_ORDER: Record<string, number> = { RED: 0, YELLOW: 1, GREEN: 2 };

Deno.serve(async (req) => {
  // Handle CORS preflight
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }

  if (req.method !== "POST") {
    return new Response(
      JSON.stringify({ error: "Use POST with your API key" }),
      { status: 405, headers: CORS_HEADERS }
    );
  }

  try {
    const body = await req.json();
    const apiKey = body.apiKey;

    if (!apiKey || typeof apiKey !== "string" || apiKey.trim().length === 0) {
      return new Response(
        JSON.stringify({ error: "Please provide your Intelligems API key." }),
        { status: 400, headers: CORS_HEADERS }
      );
    }

    if (apiKey.trim().length < 10) {
      return new Response(
        JSON.stringify({ error: "That doesn't look like a valid API key. Check your key in the Intelligems dashboard under Settings \u2192 API." }),
        { status: 400, headers: CORS_HEADERS }
      );
    }

    // 1. Fetch active experiments
    let expData: Record<string, unknown>;
    try {
      expData = await apiFetch(`${API_BASE}/experiences-list`, apiKey, {
        status: "started",
        category: "experiment",
      });
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "";
      if (msg === "INVALID_KEY") {
        return new Response(
          JSON.stringify({
            error:
              "Invalid API key. Check your key in the Intelligems dashboard under Settings \u2192 API.",
          }),
          { status: 401, headers: CORS_HEADERS }
        );
      }
      if (msg === "RATE_LIMITED") {
        return new Response(
          JSON.stringify({ error: "API is busy, try again in a minute." }),
          { status: 429, headers: CORS_HEADERS }
        );
      }
      throw e;
    }

    const experiments = (
      (expData.experiencesList as Experiment[]) || []
    ).slice(0, MAX_EXPERIMENTS);

    if (experiments.length === 0) {
      return new Response(
        JSON.stringify({ error: "No active experiments found. All quiet!" }),
        { status: 200, headers: CORS_HEADERS }
      );
    }

    // 2. Analyze each test
    const testCards: TestCard[] = [];

    for (let i = 0; i < experiments.length; i++) {
      const exp = experiments[i];

      // Throttle between requests (skip first)
      if (i > 0) await sleep(REQUEST_DELAY);

      let analytics: Record<string, unknown>;
      try {
        analytics = await apiFetch(
          `${API_BASE}/analytics/resource/${exp.id}`,
          apiKey,
          { view: "overview" }
        );
      } catch {
        testCards.push({
          name: exp.name || "Unnamed Test",
          status: "RED",
          action: "Could not fetch analytics",
          type: detectTestType(exp),
          runtimeDisplay: "Unknown",
          visitors: 0,
          orders: 0,
          dailyVisitors: 0,
          dailyOrders: 0,
          bestVariant: null,
          primaryMetricLabel: "RPV",
          primaryLift: null,
          primaryConfidence: null,
          convLift: null,
          convConfidence: null,
          daysToVerdict: null,
        });
        continue;
      }

      const metrics = (analytics.metrics as MetricRow[]) || [];
      const variations = (exp.variations as Variation[]) || [];

      // Runtime
      const startedTs = exp.startedAtTs || exp.startedAt;
      const days = runtimeDays(startedTs);
      const daysDisplay = runtimeDisplay(startedTs);

      // Totals
      const totalVis = getTotalVisitors(metrics);
      const totalOrd = getTotalOrders(metrics);

      // Daily rates
      const dVis = dailyVisitorsRate(totalVis, days);
      const dOrd = dailyOrdersRate(totalOrd, days);

      // Primary metric
      const revMetric = primaryRevenueMetric(metrics);
      const primaryLabel = revMetric === "gross_profit_per_visitor" ? "GPV" : "RPV";

      // Best variant on primary metric
      const bestPrimary = findBestVariant(metrics, variations, revMetric);

      // Best variant on conversion
      const bestConv = findBestVariant(metrics, variations, "conversion_rate");

      // Health status
      const health = computeHealth(
        days,
        totalOrd,
        dVis,
        bestPrimary.lift,
        bestPrimary.confidence,
        bestConv.lift,
        bestConv.confidence
      );

      // Days to verdict
      let dtv: number | null = null;
      if (totalOrd < VERDICT_MIN_ORDERS) {
        dtv = daysToTargetOrders(totalOrd, VERDICT_MIN_ORDERS, dOrd);
      }

      testCards.push({
        name: exp.name || "Unnamed Test",
        status: health.status,
        action: health.action,
        type: detectTestType(exp),
        runtimeDisplay: daysDisplay,
        visitors: totalVis,
        orders: totalOrd,
        dailyVisitors: Math.round(dVis),
        dailyOrders: Math.round(dOrd),
        bestVariant: bestPrimary.name,
        primaryMetricLabel: primaryLabel,
        primaryLift: fmtLift(bestPrimary.lift),
        primaryConfidence: fmtConfidence(bestPrimary.confidence),
        convLift: fmtLift(bestConv.lift),
        convConfidence: fmtConfidence(bestConv.confidence),
        daysToVerdict: dtv,
      });
    }

    // Sort by priority: RED first, then YELLOW, then GREEN
    testCards.sort(
      (a, b) => (STATUS_ORDER[a.status] ?? 99) - (STATUS_ORDER[b.status] ?? 99)
    );

    // Program Pulse
    const totalDailyVis = testCards.reduce((s, c) => s + c.dailyVisitors, 0);
    const totalDailyOrd = testCards.reduce((s, c) => s + c.dailyOrders, 0);
    const readyCount = testCards.filter(
      (c) => c.daysToVerdict === null || c.daysToVerdict === 0
    ).length;

    const response = {
      date: new Date().toISOString().split("T")[0],
      tests: testCards,
      pulse: {
        activeTests: testCards.length,
        dailyVisitors: totalDailyVis,
        dailyOrders: totalDailyOrd,
        readyToCall: readyCount,
        needMoreTime: testCards.length - readyCount,
      },
    };

    return new Response(JSON.stringify(response), {
      status: 200,
      headers: CORS_HEADERS,
    });
  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    console.error("Edge function error:", msg);
    return new Response(
      JSON.stringify({ error: "Something went wrong. Please try again." }),
      { status: 500, headers: CORS_HEADERS }
    );
  }
});
