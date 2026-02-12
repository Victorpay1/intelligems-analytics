// Intelligems Analytics — Test Analysis Proxy
// Supabase Edge Function: fetches data once, computes all 6 single-test analyses.
// Actions: "list-tests" | "analyze-test"

// ── Config ──────────────────────────────────────────────────────────

const API_BASE = "https://api.intelligems.io/v25-10-beta";
const REQUEST_DELAY = 1000;
const MAX_RETRIES = 3;
const RETRY_BASE_DELAY = 5000;

const MIN_CONFIDENCE = 0.80;
const NEUTRAL_LIFT_THRESHOLD = 0.02;
const VERDICT_MIN_RUNTIME = 10;
const VERDICT_MIN_ORDERS = 30;
const MIN_VISITORS = 100;
const ASSUMED_CAC = 40;

const ALLOWED_ORIGIN = "https://victorpay1.github.io";

const CORS_HEADERS = {
  "Access-Control-Allow-Origin": ALLOWED_ORIGIN,
  "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type, Authorization",
  "Content-Type": "application/json",
};

const SEGMENT_TYPES: [string, string][] = [
  ["device_type", "Device"],
  ["visitor_type", "Visitor Type"],
  ["source_channel", "Traffic Source"],
];

const FUNNEL_STAGES: [string, string][] = [
  ["add_to_cart_rate", "Add to Cart"],
  ["checkout_begin_rate", "Begin Checkout"],
  ["checkout_enter_contact_info_rate", "Enter Contact Info"],
  ["checkout_address_submitted_rate", "Submit Address"],
  ["conversion_rate", "Purchase"],
];

const METRIC_LABELS: Record<string, string> = {
  net_revenue_per_visitor: "Revenue / Visitor",
  gross_profit_per_visitor: "Profit / Visitor",
  conversion_rate: "Conversion Rate",
  net_revenue_per_order: "AOV",
};

// ── Types ───────────────────────────────────────────────────────────

interface MetricData {
  value?: number | null;
  uplift?: { value?: number | null; ci_low?: number | null; ci_high?: number | null };
  p2bb?: number | null;
}

interface MetricRow {
  variation_id?: string;
  audience?: string;
  [key: string]: unknown;
}

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
  endedAtTs?: number;
  endedAt?: number;
  variations?: Variation[];
  testTypes?: Record<string, boolean>;
  type?: string;
}

// ── API Client ──────────────────────────────────────────────────────

async function apiFetch(
  url: string,
  apiKey: string,
  params?: Record<string, string>
): Promise<Record<string, unknown>> {
  const qs = params ? "?" + new URLSearchParams(params).toString() : "";
  for (let attempt = 0; attempt < MAX_RETRIES; attempt++) {
    const res = await fetch(`${url}${qs}`, {
      headers: {
        "intelligems-access-token": apiKey,
        "Content-Type": "application/json",
      },
    });
    if (res.status === 429) {
      await sleep(RETRY_BASE_DELAY * Math.pow(2, attempt));
      continue;
    }
    if (res.status === 401 || res.status === 403) throw new Error("INVALID_KEY");
    if (!res.ok) throw new Error(`API error: ${res.status}`);
    return await res.json();
  }
  throw new Error("RATE_LIMITED");
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

// ── Metric Helpers ──────────────────────────────────────────────────

function getMetricValue(
  metrics: MetricRow[], name: string, variationId: string
): number | null {
  for (const m of metrics) {
    if (m.variation_id === variationId) {
      const d = m[name] as MetricData | undefined;
      if (d && typeof d === "object") return d.value ?? null;
    }
  }
  return null;
}

function getMetricUplift(
  metrics: MetricRow[], name: string, variationId: string
): number | null {
  for (const m of metrics) {
    if (m.variation_id === variationId) {
      const d = m[name] as MetricData | undefined;
      if (d && typeof d === "object" && d.uplift) return d.uplift.value ?? null;
    }
  }
  return null;
}

function getMetricConfidence(
  metrics: MetricRow[], name: string, variationId: string
): number | null {
  for (const m of metrics) {
    if (m.variation_id === variationId) {
      const d = m[name] as MetricData | undefined;
      if (d && typeof d === "object") return d.p2bb ?? null;
    }
  }
  return null;
}

function getMetricCI(
  metrics: MetricRow[], name: string, variationId: string
): [number | null, number | null] {
  for (const m of metrics) {
    if (m.variation_id === variationId) {
      const d = m[name] as MetricData | undefined;
      if (d && typeof d === "object" && d.uplift) {
        return [d.uplift.ci_low ?? null, d.uplift.ci_high ?? null];
      }
    }
  }
  return [null, null];
}

function getTotalVisitors(metrics: MetricRow[]): number {
  let total = 0;
  for (const m of metrics) {
    const v = m.n_visitors as MetricData | undefined;
    if (v && typeof v === "object") total += (v.value as number) || 0;
  }
  return Math.floor(total);
}

function getTotalOrders(metrics: MetricRow[]): number {
  let total = 0;
  for (const m of metrics) {
    const o = m.n_orders as MetricData | undefined;
    if (o && typeof o === "object") total += (o.value as number) || 0;
  }
  return Math.floor(total);
}

function getVariationVisitors(metrics: MetricRow[], variationId: string): number {
  const val = getMetricValue(metrics, "n_visitors", variationId);
  return val ? Math.floor(val) : 0;
}

function hasCOGSData(metrics: MetricRow[]): boolean {
  for (const m of metrics) {
    const pct = m.pct_revenue_with_cogs as MetricData | undefined;
    if (pct && typeof pct === "object" && pct.value && pct.value > 0) return true;
  }
  return false;
}

function primaryRevenueMetric(metrics: MetricRow[]): string {
  return hasCOGSData(metrics) ? "gross_profit_per_visitor" : "net_revenue_per_visitor";
}

function groupMetricsBySegment(metrics: MetricRow[]): Record<string, MetricRow[]> {
  const groups: Record<string, MetricRow[]> = {};
  for (const m of metrics) {
    const seg = (m.audience as string) || "Unknown";
    if (!groups[seg]) groups[seg] = [];
    groups[seg].push(m);
  }
  return groups;
}

// ── General Helpers ─────────────────────────────────────────────────

function findControl(variations: Variation[]): Variation | null {
  return variations.find((v) => v.isControl) || null;
}

function findVariants(variations: Variation[]): Variation[] {
  return variations.filter((v) => !v.isControl);
}

function getVariationName(variations: Variation[], id: string): string {
  return variations.find((v) => v.id === id)?.name || "Unknown";
}

function runtimeDays(startedTs: number | null | undefined): number {
  if (!startedTs) return 0;
  const days = Math.floor((Date.now() - new Date(startedTs).getTime()) / 86400000);
  return Math.max(days, 0);
}

function runtimeDisplay(startedTs: number | null | undefined): string {
  const d = runtimeDays(startedTs);
  if (d === 0) return "< 1 day";
  if (d === 1) return "1 day";
  return `${d} days`;
}

function detectTestType(exp: Experiment): string {
  const tt = exp.testTypes || {};
  if (tt.hasTestPricing) return "Pricing";
  if (tt.hasTestShipping) return "Shipping";
  if (tt.hasTestCampaign) return "Offer";
  if (
    tt.hasTestContent || tt.hasTestContentAdvanced || tt.hasTestContentTemplate ||
    tt.hasTestContentOnsite || tt.hasTestContentUrl || tt.hasTestContentTheme
  ) return "Content";
  const t = exp.type || "";
  if (t.includes("pricing")) return "Pricing";
  if (t.includes("shipping")) return "Shipping";
  if (t.includes("offer")) return "Offer";
  return "Content";
}

function fmtLift(lift: number | null): string {
  if (lift === null || lift === undefined) return "\u2014";
  return `${lift > 0 ? "+" : ""}${(lift * 100).toFixed(1)}%`;
}

function fmtConfidence(p2bb: number | null): string {
  if (p2bb === null || p2bb === undefined) return "Low data";
  return `${Math.round(p2bb * 100)}%`;
}

function fmtCurrency(amount: number | null): string {
  if (amount === null || amount === undefined) return "\u2014";
  const abs = Math.abs(amount);
  const sign = amount < 0 ? "-" : "";
  if (abs >= 1000000) return `${sign}$${(abs / 1000000).toFixed(1)}M`;
  if (abs >= 1000) return `${sign}$${Math.round(abs).toLocaleString("en-US")}`;
  return `${sign}$${abs.toFixed(2)}`;
}

function fmtNumber(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

function fmtPct(val: number | null): string {
  if (val === null || val === undefined) return "\u2014";
  return `${(val * 100).toFixed(2)}%`;
}

function pickBestVariant(
  variants: Variation[], metrics: MetricRow[], metricName: string
): Variation | null {
  let best: Variation | null = null;
  let bestUplift: number | null = null;
  for (const v of variants) {
    const u = getMetricUplift(metrics, metricName, v.id);
    if (u !== null && (bestUplift === null || u > bestUplift)) {
      best = v;
      bestUplift = u;
    }
  }
  return best;
}

// ── Verdict Logic (from verdict.py) ─────────────────────────────────

function variationVerdict(
  p2bb: number | null, uplift: number | null, days: number
): string {
  if (p2bb === null || uplift === null) return "TOO EARLY";
  if (p2bb >= MIN_CONFIDENCE && uplift > NEUTRAL_LIFT_THRESHOLD) return "WINNER";
  if ((1 - p2bb) >= MIN_CONFIDENCE && uplift < -NEUTRAL_LIFT_THRESHOLD) return "LOSER";
  if (days >= 21 && Math.abs(uplift) <= NEUTRAL_LIFT_THRESHOLD) return "FLAT";
  return "KEEP RUNNING";
}

function suggestNextTest(testType: string, verdict: string): string {
  if (verdict === "TOO EARLY" || verdict === "KEEP RUNNING") {
    return "Just wait. Let the test accumulate more data before planning the next move.";
  }
  const suggestions: Record<string, string> = {
    "Pricing-WINNER": "Try testing a slightly higher price point to find the ceiling. Also consider testing price anchoring or bundle pricing.",
    "Pricing-LOSER": "The price change hurt performance. Try a smaller increment, or test perceived-value tactics (strikethrough pricing, limited-time framing).",
    "Pricing-FLAT": "Price didn't matter here. Test something that changes perceived value instead: urgency messaging, social proof, or bundle offers.",
    "Shipping-WINNER": "Great \u2014 shipping changes moved the needle. Try testing different free-shipping thresholds to optimize the balance between conversion lift and margin.",
    "Shipping-LOSER": "This shipping approach hurt. Consider testing free shipping with a minimum order threshold, or offering shipping as a value-add at checkout.",
    "Shipping-FLAT": "Shipping wasn't the lever. Test something else \u2014 pricing, offer messaging, or checkout flow changes.",
    "Offer-WINNER": "The offer works. Now optimize it: test the discount level, the qualifying threshold, or the way it's communicated.",
    "Offer-LOSER": "This offer didn't land. Try a different discount structure (percentage vs. fixed), or test urgency-based offers.",
    "Offer-FLAT": "The offer didn't move behavior. Test something more visible \u2014 homepage messaging, product page layout, or the checkout experience.",
    "Content-WINNER": "This content change is working. Double down \u2014 test further variations of the winning approach on other pages.",
    "Content-LOSER": "This content didn't resonate. Try a completely different angle or test on a different page in the funnel.",
    "Content-FLAT": "The messaging change isn't moving the needle. Try a bolder change \u2014 layout, imagery, or a fundamentally different value proposition.",
  };
  return suggestions[`${testType}-${verdict}`] ||
    "Consider testing a different lever entirely \u2014 pricing, shipping, offers, or content.";
}

function buildReasoning(
  verdict: string, varName: string, metricLabel: string,
  uplift: number | null, p2bb: number | null, days: number, totalOrders: number
): string {
  const lift = fmtLift(uplift);
  const conf = fmtConfidence(p2bb);
  if (verdict === "TOO EARLY") {
    return `"${varName}" has been running for ${days} day(s) with ${fmtNumber(totalOrders)} orders. There isn't enough data yet to make any call. Let it run longer before drawing conclusions.`;
  }
  if (verdict === "WINNER") {
    return `"${varName}" is beating control by ${lift} on ${metricLabel}, with ${conf} confidence. After ${days} days and ${fmtNumber(totalOrders)} orders, the data supports rolling this out.`;
  }
  if (verdict === "LOSER") {
    return `"${varName}" is underperforming control by ${lift} on ${metricLabel}, with ${conf} confidence that control is better. The data says this change is hurting \u2014 consider ending it.`;
  }
  if (verdict === "FLAT") {
    return `"${varName}" shows ${lift} lift on ${metricLabel} after ${days} days. That's within the noise threshold. There's no meaningful difference \u2014 pick whichever is simpler to maintain.`;
  }
  return `"${varName}" shows ${lift} lift on ${metricLabel} at ${conf} confidence after ${days} days. There are signals here, but not enough conviction yet. Keep running.`;
}

function buildRisk(
  p2bb: number | null, ciLow: number | null, ciHigh: number | null,
  metricLabel: string, profitNote: string | null
): string {
  const parts: string[] = [];
  if (p2bb !== null) {
    const conf = p2bb * 100;
    const risk = 100 - conf;
    if (conf >= 50) {
      parts.push(`At ${conf.toFixed(0)}% confidence, there's a ${risk.toFixed(0)}% chance the control was actually better.`);
    } else {
      parts.push(`At ${conf.toFixed(0)}% confidence, there's a ${(100 - risk).toFixed(0)}% chance this variation is actually better than control.`);
    }
  } else {
    parts.push("Not enough data to calculate confidence yet.");
  }
  if (ciLow !== null && ciHigh !== null) {
    parts.push(`The true ${metricLabel} lift likely falls between ${fmtLift(ciLow)} and ${fmtLift(ciHigh)}.`);
  }
  if (profitNote) parts.push(profitNote);
  return parts.length ? parts.join("\n") : "Insufficient data for risk assessment.";
}

interface VerdictResult {
  overall: string;
  variations: Array<{
    name: string;
    verdict: string;
    uplift: string;
    confidence: string;
    ciLow: string | null;
    ciHigh: string | null;
    rpvUplift: string;
    crUplift: string;
    divergence: string | null;
    profitNote: string | null;
    reasoning: string;
    risk: string;
  }>;
  maturityIssues: string[];
  segments: Array<{
    segment: string;
    verdict: string;
    uplift: string;
    confidence: string;
    visitors: number;
    contradiction: boolean;
  }>;
  nextTest: string;
}

function computeVerdict(
  experiment: Experiment, metrics: MetricRow[],
  deviceMetrics: MetricRow[] | null, revMetric: string,
  revLabel: string, days: number, totalVisitors: number,
  totalOrders: number, hasCogs: boolean
): VerdictResult {
  const variations = experiment.variations || [];
  const control = findControl(variations);
  const variants = findVariants(variations);
  if (!control || !variants.length) {
    return { overall: "TOO EARLY", variations: [], maturityIssues: ["No control or variant found"], segments: [], nextTest: "" };
  }

  // Maturity check
  const maturityIssues: string[] = [];
  if (days < VERDICT_MIN_RUNTIME) maturityIssues.push(`Only ${runtimeDisplay(experiment.startedAtTs || experiment.startedAt)} of runtime (minimum ${VERDICT_MIN_RUNTIME} days)`);
  if (totalOrders < VERDICT_MIN_ORDERS) maturityIssues.push(`Only ${fmtNumber(totalOrders)} orders (minimum ${VERDICT_MIN_ORDERS})`);
  if (totalVisitors < MIN_VISITORS) maturityIssues.push(`Only ${fmtNumber(totalVisitors)} visitors (minimum ${MIN_VISITORS})`);
  const isTooEarly = maturityIssues.length > 0;

  // Analyze each variation
  const variationResults: Array<{
    id: string; name: string; verdict: string;
    p2bb: number | null; uplift: number | null;
    ciLow: number | null; ciHigh: number | null;
    rpvUplift: number | null; crUplift: number | null;
    divergence: string | null; profitNote: string | null;
    reasoning: string; risk: string;
  }> = [];

  for (const variant of variants) {
    const vid = variant.id;
    const vname = getVariationName(variations, vid);
    const p2bb = getMetricConfidence(metrics, revMetric, vid);
    const uplift = getMetricUplift(metrics, revMetric, vid);
    const [ciLow, ciHigh] = getMetricCI(metrics, revMetric, vid);
    const rpvUplift = getMetricUplift(metrics, "net_revenue_per_visitor", vid);
    const crUplift = getMetricUplift(metrics, "conversion_rate", vid);

    // Divergence detection
    let divergence: string | null = null;
    if (rpvUplift !== null && crUplift !== null) {
      const rpvDir = rpvUplift > 0.005 ? "up" : (rpvUplift < -0.005 ? "down" : "flat");
      const crDir = crUplift > 0.005 ? "up" : (crUplift < -0.005 ? "down" : "flat");
      if (rpvDir !== crDir && rpvDir !== "flat" && crDir !== "flat") {
        if (rpvDir === "up" && crDir === "down") {
          divergence = "Revenue is UP but conversion is DOWN \u2014 fewer people are buying, but those who do spend more. Worth monitoring.";
        } else if (rpvDir === "down" && crDir === "up") {
          divergence = "Conversion is UP but revenue is DOWN \u2014 more people are buying, but they're spending less per order. Check if discounting is too aggressive.";
        } else {
          divergence = `Revenue per visitor is ${rpvDir} (${fmtLift(rpvUplift)}) while conversion rate is ${crDir} (${fmtLift(crUplift)}). These signals don't fully align \u2014 investigate further.`;
        }
      }
    }

    // COGS check
    let profitNote: string | null = null;
    if (hasCogs) {
      const gpvU = getMetricUplift(metrics, "gross_profit_per_visitor", vid);
      const rpvU = getMetricUplift(metrics, "net_revenue_per_visitor", vid);
      if (gpvU !== null && rpvU !== null) {
        if ((gpvU > 0) !== (rpvU > 0)) {
          profitNote = `Revenue (${fmtLift(rpvU)}) and profit (${fmtLift(gpvU)}) are moving in opposite directions. COGS are eating into the gains.`;
        } else {
          profitNote = `Revenue (${fmtLift(rpvU)}) and profit (${fmtLift(gpvU)}) are aligned. COGS aren't distorting the picture.`;
        }
      }
    }

    const vVerdict = isTooEarly ? "TOO EARLY" : variationVerdict(p2bb, uplift, days);
    const reasoning = buildReasoning(vVerdict, vname, revLabel, uplift, p2bb, days, totalOrders);
    const risk = buildRisk(p2bb, ciLow, ciHigh, revLabel, profitNote);

    variationResults.push({
      id: vid, name: vname, verdict: vVerdict, p2bb, uplift,
      ciLow, ciHigh, rpvUplift, crUplift, divergence, profitNote,
      reasoning, risk,
    });
  }

  // Sort: best verdict first, then by confidence
  const priority: Record<string, number> = { WINNER: 0, "KEEP RUNNING": 1, FLAT: 2, LOSER: 3, "TOO EARLY": 4 };
  variationResults.sort((a, b) =>
    (priority[a.verdict] ?? 5) - (priority[b.verdict] ?? 5) || -((a.p2bb || 0) - (b.p2bb || 0))
  );
  const best = variationResults[0];

  // Segment quick-check (device)
  const segments: VerdictResult["segments"] = [];
  if (!isTooEarly && deviceMetrics && deviceMetrics.length > 0) {
    const grouped = groupMetricsBySegment(deviceMetrics);
    for (const [segName, segM] of Object.entries(grouped)) {
      const segP2bb = getMetricConfidence(segM, revMetric, best.id);
      const segUplift = getMetricUplift(segM, revMetric, best.id);
      const segVisitors = getVariationVisitors(segM, best.id);
      const segV = segUplift !== null ? variationVerdict(segP2bb, segUplift, days) : "LOW DATA";
      const contradiction = (best.verdict === "WINNER" && segV === "LOSER") ||
        (best.verdict === "LOSER" && segV === "WINNER");
      segments.push({
        segment: segName, verdict: segV,
        uplift: fmtLift(segUplift), confidence: fmtConfidence(segP2bb),
        visitors: segVisitors, contradiction,
      });
    }
  }

  const testType = detectTestType(experiment);
  const nextTest = suggestNextTest(testType, best.verdict);

  return {
    overall: best.verdict,
    variations: variationResults.map((r) => ({
      name: r.name, verdict: r.verdict,
      uplift: fmtLift(r.uplift), confidence: fmtConfidence(r.p2bb),
      ciLow: r.ciLow !== null ? fmtLift(r.ciLow) : null,
      ciHigh: r.ciHigh !== null ? fmtLift(r.ciHigh) : null,
      rpvUplift: fmtLift(r.rpvUplift), crUplift: fmtLift(r.crUplift),
      divergence: r.divergence, profitNote: r.profitNote,
      reasoning: r.reasoning, risk: r.risk,
    })),
    maturityIssues,
    segments,
    nextTest,
  };
}

// ── Profit Impact (from impact.py) ──────────────────────────────────

interface ProfitImpactResult {
  expectedAnnual: number;
  expectedMonthly: number;
  conservativeAnnual: number | null;
  optimisticAnnual: number | null;
  conservativeMonthly: number | null;
  optimisticMonthly: number | null;
  breakEven: string[];
  opportunityCost: { daily: number; weekly: number; monthly: number } | null;
  cacEquivalence: { monthlyCustomers: number; assumedCAC: number } | null;
  summary: string;
}

function computeProfitImpact(
  testName: string, testType: string, variantName: string,
  controlValue: number | null, uplift: number | null,
  confidence: number | null, ciLow: number | null, ciHigh: number | null,
  totalVisitors: number, days: number, revLabel: string,
  crUplift: number | null, rpvUplift: number | null
): ProfitImpactResult {
  const avgDailyVis = days > 0 ? totalVisitors / days : 0;
  const annualVisitors = avgDailyVis * 365;
  const annualBaseline = annualVisitors * (controlValue || 0);

  const expectedAnnual = annualBaseline * (uplift || 0);
  const expectedMonthly = expectedAnnual / 12;

  const conservativeAnnual = ciLow !== null && ciLow > 0 ? annualBaseline * ciLow : (ciLow !== null ? 0 : null);
  const optimisticAnnual = ciHigh !== null ? annualBaseline * ciHigh : null;
  const conservativeMonthly = conservativeAnnual !== null ? conservativeAnnual / 12 : null;
  const optimisticMonthly = optimisticAnnual !== null ? optimisticAnnual / 12 : null;

  // Break-even analysis
  const breakEven: string[] = [];
  if (rpvUplift !== null && rpvUplift > 0 && crUplift !== null && crUplift < 0) {
    const crDrop = Math.abs(crUplift) * 100;
    const rpvGain = rpvUplift * 100;
    breakEven.push(`Revenue per visitor is up ${rpvGain.toFixed(1)}% while conversion rate is down ${crDrop.toFixed(1)}%.`);
    const headroom = rpvGain - crDrop;
    if (headroom > 0) {
      breakEven.push(`You have ${headroom.toFixed(1)}% of headroom \u2014 the revenue gain more than absorbs the conversion dip.`);
    }
    breakEven.push(`You could afford up to ~${rpvGain.toFixed(1)}% conversion drop and still come out ahead on revenue.`);
  }
  if (testType === "Pricing" && uplift !== null && uplift > 0) {
    breakEven.push(`Pricing insight: At this ${fmtLift(uplift)} lift, you would need to lose more than ${(uplift * 100).toFixed(1)}% of your customers to lose money.`);
  }
  if (breakEven.length === 0) {
    if (uplift !== null && uplift > 0) {
      breakEven.push("No metric divergence detected \u2014 revenue and conversion are moving in the same direction.");
    } else if (uplift !== null && uplift < 0) {
      breakEven.push("This variant underperforms the control. No break-even scenario exists.");
    } else {
      breakEven.push("No meaningful difference detected between variants.");
    }
  }

  // Opportunity cost
  const dailyImpact = expectedAnnual / 365;
  const opportunityCost = uplift !== null && uplift > 0 ? {
    daily: Math.abs(dailyImpact),
    weekly: Math.abs(dailyImpact * 7),
    monthly: Math.abs(dailyImpact * 30),
  } : null;

  // CAC equivalence
  const cacEquivalence = expectedMonthly !== 0 ? {
    monthlyCustomers: Math.round(Math.abs(expectedMonthly) / ASSUMED_CAC),
    assumedCAC: ASSUMED_CAC,
  } : null;

  // Business summary
  const confStr = fmtConfidence(confidence);
  const hasHighConf = confidence !== null && confidence >= MIN_CONFIDENCE;
  let summary = "";

  if (uplift !== null && uplift > 0) {
    summary = `The "${variantName}" variant shows a ${fmtLift(uplift)} lift in ${revLabel} (${confStr} confidence).`;
    if (hasHighConf && conservativeAnnual !== null && conservativeAnnual > 0) {
      summary += ` Projected annual impact ranges from ${fmtCurrency(conservativeAnnual)} (conservative) to ${fmtCurrency(optimisticAnnual)} (optimistic), with an expected value of ${fmtCurrency(expectedAnnual)}.`;
    } else if (hasHighConf) {
      summary += ` Expected annual impact: ${fmtCurrency(expectedAnnual)}.`;
    } else {
      summary += ` Estimated annual impact is ${fmtCurrency(expectedAnnual)}, but confidence is below 80% \u2014 more data is needed.`;
    }
    if (hasHighConf && dailyImpact > 0) {
      summary += ` Every day without rolling out costs approximately ${fmtCurrency(dailyImpact)}.`;
    }
  } else if (uplift !== null && uplift < 0) {
    summary = `The "${variantName}" variant shows a ${fmtLift(uplift)} decline in ${revLabel} (${confStr} confidence). If rolled out, it would cost approximately ${fmtCurrency(Math.abs(expectedAnnual))}/year.`;
  } else {
    summary = `The "${variantName}" variant shows no meaningful lift in ${revLabel} (${confStr} confidence).`;
    if (days < VERDICT_MIN_RUNTIME) {
      summary += ` Only ${days} days in \u2014 let it run at least ${VERDICT_MIN_RUNTIME} days.`;
    }
  }

  return {
    expectedAnnual, expectedMonthly,
    conservativeAnnual, optimisticAnnual,
    conservativeMonthly, optimisticMonthly,
    breakEven, opportunityCost, cacEquivalence, summary,
  };
}

// ── Funnel Diagnosis (from funnel.py) ───────────────────────────────

interface FunnelStage {
  label: string;
  control: string;
  variant: string;
  uplift: string;
  confidence: string;
  rawUplift: number | null;
  hasData: boolean;
}

interface FunnelResult {
  stages: FunnelStage[];
  biggestGain: { label: string; uplift: string } | null;
  biggestDrop: { label: string; uplift: string } | null;
  breakpoint: { label: string } | null;
  diagnosis: string;
}

function computeFunnelDiagnosis(
  metrics: MetricRow[], controlId: string, variantId: string,
  testType: string
): FunnelResult {
  const stages: FunnelStage[] = [];
  const activeStages: { label: string; uplift: number | null; confidence: number | null }[] = [];

  for (const [metricName, label] of FUNNEL_STAGES) {
    const ctrlVal = getMetricValue(metrics, metricName, controlId);
    const varVal = getMetricValue(metrics, metricName, variantId);
    const uplift = getMetricUplift(metrics, metricName, variantId);
    const conf = getMetricConfidence(metrics, metricName, variantId);
    const hasData = ctrlVal !== null || varVal !== null;

    stages.push({
      label, control: fmtPct(ctrlVal), variant: fmtPct(varVal),
      uplift: fmtLift(uplift), confidence: fmtConfidence(conf),
      rawUplift: uplift, hasData,
    });
    if (hasData) activeStages.push({ label, uplift, confidence: conf });
  }

  // Find biggest gain, drop, breakpoint
  let biggestGain: { label: string; uplift: number } | null = null;
  let biggestDrop: { label: string; uplift: number } | null = null;

  for (const s of activeStages) {
    if (s.uplift !== null && s.uplift > 0) {
      if (!biggestGain || s.uplift > biggestGain.uplift) {
        biggestGain = { label: s.label, uplift: s.uplift };
      }
    }
    if (s.uplift !== null && s.uplift < 0) {
      if (!biggestDrop || s.uplift < biggestDrop.uplift) {
        biggestDrop = { label: s.label, uplift: s.uplift };
      }
    }
  }

  // Breakpoint: where direction flips
  let breakpoint: { label: string } | null = null;
  let prevDir: string | null = null;
  for (const s of activeStages) {
    if (s.uplift === null) continue;
    const dir = s.uplift > 0.005 ? "up" : (s.uplift < -0.005 ? "down" : "flat");
    if (prevDir && dir !== prevDir && dir !== "flat" && prevDir !== "flat") {
      breakpoint = { label: s.label };
      break;
    }
    if (dir !== "flat") prevDir = dir;
  }

  // Diagnosis text
  const parts: string[] = [];
  if (biggestGain && biggestDrop) {
    parts.push(`The variant improves ${biggestGain.label} (${fmtLift(biggestGain.uplift)}) but hurts ${biggestDrop.label} (${fmtLift(biggestDrop.uplift)}).`);
  } else if (biggestGain && !biggestDrop) {
    parts.push(`The variant lifts ${biggestGain.label} by ${fmtLift(biggestGain.uplift)} with no negative stages \u2014 clean signal across the funnel.`);
  } else if (biggestDrop && !biggestGain) {
    parts.push(`The variant hurts ${biggestDrop.label} by ${fmtLift(biggestDrop.uplift)} with no positive stages \u2014 the change is making things worse.`);
  } else {
    parts.push("No meaningful differences across funnel stages \u2014 the variant isn't moving behavior.");
  }
  if (breakpoint) {
    parts.push(`The breakpoint is at ${breakpoint.label}: behavior diverges here.`);
  }
  if (biggestDrop) {
    const dl = biggestDrop.label.toLowerCase();
    if (dl.includes("cart")) parts.push("Consider testing product page changes to improve add-to-cart conversion.");
    else if (dl.includes("checkout")) parts.push("Checkout is the bottleneck. Test checkout flow simplification or trust signals.");
    else if (dl.includes("contact") || dl.includes("address")) parts.push("Form friction is the issue. Test reducing required fields or adding progress indicators.");
    else if (dl.includes("purchase")) parts.push("The final purchase step is weak. Test payment options, shipping clarity, or urgency messaging.");
  }

  return {
    stages,
    biggestGain: biggestGain ? { label: biggestGain.label, uplift: fmtLift(biggestGain.uplift) } : null,
    biggestDrop: biggestDrop ? { label: biggestDrop.label, uplift: fmtLift(biggestDrop.uplift) } : null,
    breakpoint,
    diagnosis: parts.join(" "),
  };
}

// ── Segment Spotlight (from spotlight.py) ───────────────────────────

interface SegmentRow {
  name: string;
  type: string;
  verdict: string;
  uplift: string;
  rawUplift: number | null;
  confidence: string;
  visitors: number;
  revenueOpportunity: string;
  rawRevOpp: number;
  contradiction: boolean;
}

interface SegmentSpotlightResult {
  segments: SegmentRow[];
  recommendation: { action: string; reason: string };
}

function segmentVerdict(p2bb: number | null, uplift: number | null, days: number): string {
  if (p2bb === null || uplift === null) return "LOW DATA";
  if (p2bb >= MIN_CONFIDENCE && uplift > NEUTRAL_LIFT_THRESHOLD) return "WINNER";
  if ((1 - p2bb) >= MIN_CONFIDENCE && uplift < -NEUTRAL_LIFT_THRESHOLD) return "LOSER";
  if (days >= 21 && Math.abs(uplift) <= NEUTRAL_LIFT_THRESHOLD) return "FLAT";
  return "KEEP RUNNING";
}

function computeSegmentSpotlight(
  allSegmentMetrics: Array<{ type: string; label: string; metrics: MetricRow[] }>,
  revMetric: string, bestId: string, controlId: string,
  controlRpv: number | null, overallUplift: number | null, days: number
): SegmentSpotlightResult {
  const allSegs: Array<{
    name: string; type: string; verdict: string;
    uplift: number | null; confidence: number | null;
    visitors: number; revOpp: number; contradiction: boolean;
  }> = [];

  for (const { label: segLabel, metrics: segMetrics } of allSegmentMetrics) {
    if (!segMetrics.length) continue;
    const grouped = groupMetricsBySegment(segMetrics);
    for (const [segName, segM] of Object.entries(grouped)) {
      const segUplift = getMetricUplift(segM, revMetric, bestId);
      const segConf = getMetricConfidence(segM, revMetric, bestId);
      const segVis = getVariationVisitors(segM, bestId);
      const ctrlVis = getVariationVisitors(segM, controlId);
      const totalSegVis = segVis + ctrlVis;

      const v = segmentVerdict(segConf, segUplift, days);

      // Revenue opportunity
      let revOpp = 0;
      if (segUplift !== null && controlRpv !== null && days > 0 && totalSegVis > 0) {
        const segDaily = totalSegVis / days;
        const rpvDelta = controlRpv * segUplift;
        revOpp = segDaily * rpvDelta * 365;
      }

      // Contradiction
      let contradiction = false;
      if (overallUplift !== null && segUplift !== null) {
        if (overallUplift > NEUTRAL_LIFT_THRESHOLD && segUplift < -NEUTRAL_LIFT_THRESHOLD) contradiction = true;
        else if (overallUplift < -NEUTRAL_LIFT_THRESHOLD && segUplift > NEUTRAL_LIFT_THRESHOLD) contradiction = true;
      }

      allSegs.push({
        name: segName, type: segLabel, verdict: v,
        uplift: segUplift, confidence: segConf,
        visitors: totalSegVis, revOpp, contradiction,
      });
    }
  }

  // Sort by absolute revenue opportunity descending
  allSegs.sort((a, b) => Math.abs(b.revOpp) - Math.abs(a.revOpp));

  // Rollout recommendation
  const winners = allSegs.filter((s) => s.verdict === "WINNER");
  const losers = allSegs.filter((s) => s.verdict === "LOSER");
  const lowData = allSegs.filter((s) => s.verdict === "LOW DATA");
  const total = allSegs.length;

  let recAction = "HOLD";
  let recReason = "Mixed signals. Monitor for another few days before making a call.";

  if (total === 0) {
    recReason = "No segment data available for analysis.";
  } else if (losers.length === 0 && winners.length >= total * 0.5) {
    recAction = "ROLL OUT";
    recReason = "No losing segments. Roll out to all traffic.";
  } else if (losers.length > 0 && winners.length > 0) {
    recAction = "SEGMENT-SPECIFIC";
    const wNames = winners.slice(0, 3).map((s) => s.name).join(", ");
    const lNames = losers.slice(0, 3).map((s) => s.name).join(", ");
    recReason = `Consider rolling out to ${wNames} only. ${lNames} ${losers.length === 1 ? "is" : "are"} underperforming \u2014 exclude or investigate.`;
  } else if (losers.length > 0 && winners.length === 0) {
    recAction = "DON'T ROLL OUT";
    recReason = "No winning segments found. The variant is hurting performance.";
  } else if (lowData.length > total * 0.5) {
    recReason = "Most segments have insufficient data. Let the test run longer.";
  }

  return {
    segments: allSegs.map((s) => ({
      name: s.name, type: s.type, verdict: s.verdict,
      uplift: fmtLift(s.uplift), rawUplift: s.uplift,
      confidence: fmtConfidence(s.confidence),
      visitors: s.visitors,
      revenueOpportunity: fmtCurrency(s.revOpp),
      rawRevOpp: s.revOpp,
      contradiction: s.contradiction,
    })),
    recommendation: { action: recAction, reason: recReason },
  };
}

// ── Test Debrief (from debrief.py) ──────────────────────────────────

interface DebriefResult {
  verdict: string;
  funnelHighlights: Array<{ label: string; control: string; variant: string; uplift: string }>;
  insights: string[];
  nextTests: string[];
}

function generateInsights(
  allSegmentMetrics: Array<{ type: string; label: string; metrics: MetricRow[] }>,
  revMetric: string, bestId: string, overallUplift: number | null
): string[] {
  // Build flat list of segments with data
  const withData: Array<{ name: string; type: string; uplift: number | null }> = [];
  for (const { label: segLabel, metrics: segMetrics } of allSegmentMetrics) {
    if (!segMetrics.length) continue;
    const grouped = groupMetricsBySegment(segMetrics);
    for (const [segName, segM] of Object.entries(grouped)) {
      const u = getMetricUplift(segM, revMetric, bestId);
      withData.push({ name: segName, type: segLabel, uplift: u });
    }
  }

  const valid = withData.filter((s) => s.uplift !== null) as Array<{ name: string; type: string; uplift: number }>;
  if (!valid.length) return [];

  const insights: string[] = [];

  // 1. Strongest segment
  const strongest = valid.reduce((a, b) => (b.uplift > a.uplift ? b : a));
  if (strongest.uplift > NEUTRAL_LIFT_THRESHOLD) {
    insights.push(`${strongest.name} (${strongest.type}) responded strongest at ${fmtLift(strongest.uplift)} lift.`);
  }

  // 2. Weakest (especially contradictions)
  const weakest = valid.reduce((a, b) => (b.uplift < a.uplift ? b : a));
  if (overallUplift !== null && overallUplift > 0 && weakest.uplift < -NEUTRAL_LIFT_THRESHOLD) {
    insights.push(`${weakest.name} (${weakest.type}) is the outlier \u2014 actually negative at ${fmtLift(weakest.uplift)} while overall is positive.`);
  } else if (weakest.uplift < -NEUTRAL_LIFT_THRESHOLD) {
    insights.push(`${weakest.name} (${weakest.type}) is underperforming at ${fmtLift(weakest.uplift)}.`);
  }

  // 3. Device comparison
  const devices = valid.filter((s) => s.type === "Device").sort((a, b) => b.uplift - a.uplift);
  if (devices.length >= 2) {
    const diff = Math.abs(devices[0].uplift - devices[devices.length - 1].uplift);
    if (diff > 0.05) {
      insights.push(`${devices[0].name} outperforms ${devices[devices.length - 1].name} by ${fmtLift(diff)} \u2014 consider device-specific optimization.`);
    }
  }

  // 4. New vs returning
  const visitors = valid.filter((s) => s.type === "Visitor Type");
  const newV = visitors.find((s) => s.name.toLowerCase().includes("new"));
  const retV = visitors.find((s) => s.name.toLowerCase().includes("return"));
  if (newV && retV) {
    const diff = Math.abs(newV.uplift - retV.uplift);
    if (diff > 0.03) {
      if (newV.uplift > retV.uplift) {
        insights.push(`New visitors drove more of the lift (${fmtLift(newV.uplift)}) vs returning (${fmtLift(retV.uplift)}).`);
      } else {
        insights.push(`Returning visitors responded more (${fmtLift(retV.uplift)}) vs new visitors (${fmtLift(newV.uplift)}).`);
      }
    }
  }

  // 5. Traffic source patterns
  const sources = valid.filter((s) => s.type === "Traffic Source");
  const posSources = sources.filter((s) => s.uplift > NEUTRAL_LIFT_THRESHOLD);
  const negSources = sources.filter((s) => s.uplift < -NEUTRAL_LIFT_THRESHOLD);
  if (posSources.length > 0 && negSources.length > 0) {
    const posNames = posSources.slice(0, 2).map((s) => s.name).join(", ");
    const negNames = negSources.slice(0, 2).map((s) => s.name).join(", ");
    insights.push(`Works for ${posNames} traffic but not ${negNames} \u2014 audience intent may differ.`);
  }

  return insights;
}

function debriefNextTests(
  verdict: string, testType: string,
  funnelStages: FunnelStage[],
  segments: Array<{ name: string; type: string; rawUplift: number | null }>
): string[] {
  const suggestions: string[] = [];

  // Funnel-based
  const active = funnelStages.filter((s) => s.hasData && s.rawUplift !== null);
  const drops = active.filter((s) => s.rawUplift! < -NEUTRAL_LIFT_THRESHOLD);
  const gains = active.filter((s) => s.rawUplift! > NEUTRAL_LIFT_THRESHOLD);

  if (drops.length > 0) {
    const worst = drops.reduce((a, b) => (b.rawUplift! < a.rawUplift! ? b : a));
    suggestions.push(`Fix the ${worst.label} stage (${worst.uplift}) \u2014 test changes specifically targeting this step.`);
  }
  if (gains.length > 0) {
    const best = gains.reduce((a, b) => (b.rawUplift! > a.rawUplift! ? b : a));
    suggestions.push(`Double down on ${best.label} (${best.uplift}) \u2014 this stage is working, push it further.`);
  }

  // Segment-based
  const negSegs = segments.filter((s) => s.rawUplift !== null && s.rawUplift < -NEUTRAL_LIFT_THRESHOLD);
  if (negSegs.length > 0) {
    const worstSeg = negSegs.reduce((a, b) => (b.rawUplift! < a.rawUplift! ? b : a));
    suggestions.push(`Investigate why ${worstSeg.name} (${worstSeg.type}) underperforms \u2014 consider a ${worstSeg.name}-specific test.`);
  }

  // Type-based
  const typeSuggestions: Record<string, string> = {
    Pricing: "Test a different price point or pricing display format.",
    Shipping: "Test shipping threshold messaging or delivery speed options.",
    Offer: "Test a different discount structure or qualifying criteria.",
    Content: "Test a completely different messaging angle or visual approach.",
  };
  if ((verdict === "WINNER" || verdict === "FLAT") && typeSuggestions[testType]) {
    suggestions.push(typeSuggestions[testType]);
  }
  if (verdict === "LOSER") {
    suggestions.push("Consider reversing the approach \u2014 test the opposite direction.");
  }
  if (suggestions.length === 0) {
    suggestions.push("Run a broader discovery test to identify the next high-impact lever.");
  }

  return suggestions;
}

function computeTestDebrief(
  verdict: string, funnelResult: FunnelResult,
  segmentResult: SegmentSpotlightResult,
  allSegmentMetrics: Array<{ type: string; label: string; metrics: MetricRow[] }>,
  revMetric: string, bestId: string, overallUplift: number | null,
  testType: string
): DebriefResult {
  // Funnel highlights: only stages with data
  const funnelHighlights = funnelResult.stages
    .filter((s) => s.hasData)
    .map((s) => ({ label: s.label, control: s.control, variant: s.variant, uplift: s.uplift }));

  const insights = generateInsights(allSegmentMetrics, revMetric, bestId, overallUplift);

  const nextTests = debriefNextTests(
    verdict, testType, funnelResult.stages,
    segmentResult.segments.map((s) => ({ name: s.name, type: s.type, rawUplift: s.rawUplift }))
  );

  return { verdict, funnelHighlights, insights, nextTests };
}

// ── Rollout Brief (from rollout.py) ─────────────────────────────────

interface RolloutResult {
  executiveSummary: string;
  financials: {
    expectedAnnual: string;
    expectedMonthly: string;
    conservativeAnnual: string | null;
    optimisticAnnual: string | null;
    dailyCostOfWaiting: string | null;
  };
  segments: Array<{
    name: string; type: string; verdict: string;
    uplift: string; confidence: string; contradiction: boolean;
  }>;
  recommendation: { action: string; reason: string };
  nextSteps: string[];
}

function buildExecutiveSummary(
  testName: string, testType: string, verdict: string,
  revLabel: string, uplift: number | null, confidence: number | null,
  expectedAnnual: number, days: number
): string {
  const parts: string[] = [];
  if (verdict === "WINNER") {
    parts.push(`The "${testName}" ${testType.toLowerCase()} test is a winner \u2014 ${revLabel} is up ${fmtLift(uplift)} with ${fmtConfidence(confidence)} confidence after ${days} days.`);
    if (expectedAnnual > 0) parts.push(`Projected annual impact: ${fmtCurrency(expectedAnnual)}. Recommend rolling out immediately.`);
  } else if (verdict === "LOSER") {
    parts.push(`The "${testName}" ${testType.toLowerCase()} test is underperforming \u2014 ${revLabel} is down ${fmtLift(uplift)} with ${fmtConfidence(confidence)} confidence.`);
    if (expectedAnnual) parts.push(`This variant would cost approximately ${fmtCurrency(Math.abs(expectedAnnual))}/year if rolled out. Recommend ending the test.`);
  } else if (verdict === "FLAT") {
    parts.push(`The "${testName}" ${testType.toLowerCase()} test shows no meaningful difference \u2014 ${revLabel} lift is ${fmtLift(uplift)} after ${days} days.`);
    parts.push("Recommend ending and testing a different lever.");
  } else if (verdict === "KEEP RUNNING") {
    parts.push(`The "${testName}" ${testType.toLowerCase()} test shows ${fmtLift(uplift)} lift at ${fmtConfidence(confidence)} confidence after ${days} days.`);
    parts.push("Not enough data for a confident call yet. Recommend letting it run.");
  } else {
    parts.push(`The "${testName}" ${testType.toLowerCase()} test is too early to evaluate \u2014 insufficient data after ${days} days.`);
    parts.push("Recommend checking back when minimum thresholds are met.");
  }
  return parts.join(" ");
}

function buildRecommendation(
  verdict: string, segmentResults: SegmentSpotlightResult["segments"]
): { action: string; reason: string } {
  const hasContradictions = segmentResults.some((s) => s.contradiction);

  if (verdict === "WINNER") {
    if (hasContradictions) {
      const losers = segmentResults.filter((s) => s.verdict === "LOSER");
      if (losers.length > 0) {
        const names = losers.slice(0, 2).map((s) => s.name).join(", ");
        return {
          action: "ROLL OUT WITH CAUTION",
          reason: `Overall winner, but ${names} underperforming. Consider a segment-specific rollout or investigate the contradiction before full rollout.`,
        };
      }
    }
    return { action: "ROLL OUT", reason: "Strong signal across the board. Roll out to all traffic." };
  }
  if (verdict === "LOSER") return { action: "END TEST", reason: "The variant is hurting performance. End the test and revert to control." };
  if (verdict === "FLAT") return { action: "END TEST \u2014 TRY SOMETHING DIFFERENT", reason: "No meaningful impact. End the test and explore a different lever." };
  if (verdict === "KEEP RUNNING") return { action: "KEEP RUNNING", reason: "Promising signals but not conclusive. Let the test accumulate more data." };
  return { action: "WAIT", reason: "Insufficient data to make any recommendation. Let the test run longer." };
}

function computeRolloutBrief(
  testName: string, testType: string, verdict: string,
  revLabel: string, uplift: number | null, confidence: number | null,
  profitImpact: ProfitImpactResult,
  segmentResult: SegmentSpotlightResult, days: number
): RolloutResult {
  const execSummary = buildExecutiveSummary(
    testName, testType, verdict, revLabel, uplift, confidence,
    profitImpact.expectedAnnual, days
  );

  const dailyCost = verdict === "WINNER" && profitImpact.opportunityCost
    ? fmtCurrency(profitImpact.opportunityCost.daily) : null;

  const recommendation = buildRecommendation(verdict, segmentResult.segments);

  // Next steps
  const nextSteps: string[] = [];
  if (verdict === "WINNER") {
    nextSteps.push("Implement the winning variant across all traffic.");
    if (segmentResult.segments.some((s) => s.contradiction)) {
      nextSteps.push("Investigate segment contradictions before full rollout.");
    }
    nextSteps.push("Plan a follow-up test to optimize further.");
  } else if (verdict === "LOSER") {
    nextSteps.push("Revert to control immediately.");
    nextSteps.push("Document learnings for the team.");
    nextSteps.push("Plan an alternative test with a different approach.");
  } else if (verdict === "FLAT") {
    nextSteps.push("End the test \u2014 no action needed on the variant.");
    nextSteps.push("Explore a different lever (pricing, shipping, offers, content).");
  } else {
    nextSteps.push("Let the test continue running.");
    nextSteps.push("Check back in a few days for updated results.");
  }

  return {
    executiveSummary: execSummary,
    financials: {
      expectedAnnual: fmtCurrency(profitImpact.expectedAnnual),
      expectedMonthly: fmtCurrency(profitImpact.expectedMonthly),
      conservativeAnnual: profitImpact.conservativeAnnual !== null ? fmtCurrency(profitImpact.conservativeAnnual) : null,
      optimisticAnnual: profitImpact.optimisticAnnual !== null ? fmtCurrency(profitImpact.optimisticAnnual) : null,
      dailyCostOfWaiting: dailyCost,
    },
    segments: segmentResult.segments.map((s) => ({
      name: s.name, type: s.type, verdict: s.verdict,
      uplift: s.uplift, confidence: s.confidence, contradiction: s.contradiction,
    })),
    recommendation,
    nextSteps,
  };
}

// ── Main Handler ────────────────────────────────────────────────────

Deno.serve(async (req) => {
  if (req.method === "OPTIONS") {
    return new Response(null, { status: 204, headers: CORS_HEADERS });
  }
  if (req.method !== "POST") {
    return new Response(JSON.stringify({ error: "Use POST" }), { status: 405, headers: CORS_HEADERS });
  }

  try {
    let body: Record<string, unknown>;
    try { body = await req.json(); } catch {
      return new Response(JSON.stringify({ error: "Invalid JSON body." }), { status: 400, headers: CORS_HEADERS });
    }

    const apiKey = body.apiKey as string;
    if (!apiKey || apiKey.trim().length < 10) {
      return new Response(JSON.stringify({ error: "Please provide a valid Intelligems API key." }), { status: 400, headers: CORS_HEADERS });
    }

    const action = body.action as string;

    // ── Action: list-tests ──────────────────────────────────────

    if (action === "list-tests") {
      let expData: Record<string, unknown>;
      try {
        expData = await apiFetch(`${API_BASE}/experiences-list`, apiKey, {
          status: "started", category: "experiment",
        });
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : "";
        if (msg === "INVALID_KEY") return new Response(JSON.stringify({ error: "Invalid API key." }), { status: 401, headers: CORS_HEADERS });
        if (msg === "RATE_LIMITED") return new Response(JSON.stringify({ error: "API is busy, try again in a minute." }), { status: 429, headers: CORS_HEADERS });
        throw e;
      }

      const experiments = ((expData.experiencesList as Experiment[]) || []).slice(0, 20);
      const tests = experiments.map((exp) => {
        const startedTs = exp.startedAtTs || exp.startedAt;
        return {
          id: exp.id,
          name: exp.name || "Unnamed Test",
          type: detectTestType(exp),
          runtimeDays: runtimeDays(startedTs),
          runtimeDisplay: runtimeDisplay(startedTs),
        };
      });

      return new Response(JSON.stringify({ tests }), { status: 200, headers: CORS_HEADERS });
    }

    // ── Action: analyze-test ────────────────────────────────────

    if (action === "analyze-test") {
      const testId = body.testId as string;
      if (!testId) {
        return new Response(JSON.stringify({ error: "Please provide a testId." }), { status: 400, headers: CORS_HEADERS });
      }

      // 1. Fetch experiment detail
      let experiment: Experiment;
      try {
        experiment = await apiFetch(`${API_BASE}/experiences/${testId}`, apiKey) as unknown as Experiment;
      } catch (e: unknown) {
        const msg = e instanceof Error ? e.message : "";
        if (msg === "INVALID_KEY") return new Response(JSON.stringify({ error: "Invalid API key." }), { status: 401, headers: CORS_HEADERS });
        return new Response(JSON.stringify({ error: `Could not find test: ${testId}` }), { status: 404, headers: CORS_HEADERS });
      }

      if (!experiment || !experiment.id) {
        return new Response(JSON.stringify({ error: `Test not found: ${testId}` }), { status: 404, headers: CORS_HEADERS });
      }

      const testName = experiment.name || "Unnamed Test";
      const testType = detectTestType(experiment);
      const variations = experiment.variations || [];
      const control = findControl(variations);
      const variantList = findVariants(variations);

      if (!control || !variantList.length) {
        return new Response(JSON.stringify({ error: "No control/variant found in this test." }), { status: 400, headers: CORS_HEADERS });
      }

      const startedTs = experiment.startedAtTs || experiment.startedAt;
      const days = runtimeDays(startedTs);
      const daysDisplay = runtimeDisplay(startedTs);

      // 2. Fetch overview analytics
      await sleep(REQUEST_DELAY);
      let analytics: Record<string, unknown>;
      try {
        analytics = await apiFetch(`${API_BASE}/analytics/resource/${testId}`, apiKey, { view: "overview" });
      } catch {
        return new Response(JSON.stringify({ error: "Could not fetch analytics data." }), { status: 500, headers: CORS_HEADERS });
      }

      const metrics = (analytics.metrics as MetricRow[]) || [];
      if (!metrics.length) {
        return new Response(JSON.stringify({ error: "No analytics data for this test yet." }), { status: 200, headers: CORS_HEADERS });
      }

      // Common values
      const totalVisitors = getTotalVisitors(metrics);
      const totalOrders = getTotalOrders(metrics);
      const hasCogs = hasCOGSData(metrics);
      const revMetric = primaryRevenueMetric(metrics);
      const revLabel = METRIC_LABELS[revMetric] || revMetric;
      const controlId = control.id;

      const best = pickBestVariant(variantList, metrics, revMetric) || variantList[0];
      const bestId = best.id;
      const bestName = getVariationName(variations, bestId);
      const controlName = getVariationName(variations, controlId);

      const uplift = getMetricUplift(metrics, revMetric, bestId);
      const confidence = getMetricConfidence(metrics, revMetric, bestId);
      const [ciLow, ciHigh] = getMetricCI(metrics, revMetric, bestId);
      const controlRpv = getMetricValue(metrics, revMetric, controlId);
      const crUplift = getMetricUplift(metrics, "conversion_rate", bestId);
      const rpvUplift = getMetricUplift(metrics, "net_revenue_per_visitor", bestId);

      // 3-5. Fetch segment data (3 types)
      const allSegmentMetrics: Array<{ type: string; label: string; metrics: MetricRow[] }> = [];
      let deviceMetrics: MetricRow[] | null = null;

      for (const [segType, segLabel] of SEGMENT_TYPES) {
        await sleep(REQUEST_DELAY);
        try {
          const segData = await apiFetch(`${API_BASE}/analytics/resource/${testId}`, apiKey, {
            view: "audience", audience: segType,
          });
          const segM = (segData.metrics as MetricRow[]) || [];
          allSegmentMetrics.push({ type: segType, label: segLabel, metrics: segM });
          if (segType === "device_type") deviceMetrics = segM;
        } catch {
          allSegmentMetrics.push({ type: segType, label: segLabel, metrics: [] });
        }
      }

      // ── Compute all 6 analyses ───────────────────────────────

      // 1. Verdict
      const verdictResult = computeVerdict(
        experiment, metrics, deviceMetrics, revMetric, revLabel,
        days, totalVisitors, totalOrders, hasCogs
      );

      // 2. Profit Impact
      const profitResult = computeProfitImpact(
        testName, testType, bestName, controlRpv, uplift, confidence,
        ciLow, ciHigh, totalVisitors, days, revLabel, crUplift, rpvUplift
      );

      // 3. Funnel Diagnosis
      const funnelResult = computeFunnelDiagnosis(metrics, controlId, bestId, testType);

      // 4. Segment Spotlight
      const segmentResult = computeSegmentSpotlight(
        allSegmentMetrics, revMetric, bestId, controlId,
        controlRpv, uplift, days
      );

      // 5. Test Debrief
      const debriefResult = computeTestDebrief(
        verdictResult.overall, funnelResult, segmentResult,
        allSegmentMetrics, revMetric, bestId, uplift, testType
      );

      // 6. Rollout Brief
      const rolloutResult = computeRolloutBrief(
        testName, testType, verdictResult.overall, revLabel,
        uplift, confidence, profitResult, segmentResult, days
      );

      // ── Build response ───────────────────────────────────────

      const response = {
        test: {
          name: testName,
          type: testType,
          runtime: days,
          runtimeDisplay: daysDisplay,
          visitors: totalVisitors,
          orders: totalOrders,
          dailyVisitors: days > 0 ? Math.round(totalVisitors / days) : 0,
          dailyOrders: days > 0 ? Math.round(totalOrders / days) : 0,
          bestVariant: bestName,
          controlName,
          primaryMetric: revLabel,
          uplift: fmtLift(uplift),
          confidence: fmtConfidence(confidence),
          ciLow: ciLow !== null ? fmtLift(ciLow) : null,
          ciHigh: ciHigh !== null ? fmtLift(ciHigh) : null,
          hasCOGS: hasCogs,
        },
        verdict: verdictResult,
        profitImpact: {
          expectedAnnual: fmtCurrency(profitResult.expectedAnnual),
          expectedMonthly: fmtCurrency(profitResult.expectedMonthly),
          conservativeAnnual: profitResult.conservativeAnnual !== null ? fmtCurrency(profitResult.conservativeAnnual) : null,
          optimisticAnnual: profitResult.optimisticAnnual !== null ? fmtCurrency(profitResult.optimisticAnnual) : null,
          breakEven: profitResult.breakEven,
          opportunityCost: profitResult.opportunityCost ? {
            daily: fmtCurrency(profitResult.opportunityCost.daily),
            weekly: fmtCurrency(profitResult.opportunityCost.weekly),
            monthly: fmtCurrency(profitResult.opportunityCost.monthly),
          } : null,
          cacEquivalence: profitResult.cacEquivalence,
          summary: profitResult.summary,
        },
        funnelDiagnosis: funnelResult,
        segmentSpotlight: segmentResult,
        testDebrief: debriefResult,
        rolloutBrief: rolloutResult,
      };

      return new Response(JSON.stringify(response), { status: 200, headers: CORS_HEADERS });
    }

    return new Response(
      JSON.stringify({ error: 'Unknown action. Use "list-tests" or "analyze-test".' }),
      { status: 400, headers: CORS_HEADERS }
    );

  } catch (e: unknown) {
    const msg = e instanceof Error ? e.message : "Unknown error";
    console.error("Edge function error:", msg);
    return new Response(
      JSON.stringify({ error: "Something went wrong. Please try again." }),
      { status: 500, headers: CORS_HEADERS }
    );
  }
});
