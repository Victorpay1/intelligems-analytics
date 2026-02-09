# Intelligems Analytics

**Turn A/B test data into business decisions.**

[View Landing Page](https://victorpay1.github.io/intelligems-analytics/) | [GitHub](https://github.com/Victorpay1/intelligems-analytics)

Intelligems Analytics is a skill library for [Claude Code](https://claude.ai/code) that transforms raw Intelligems API data into plain-English business intelligence. Instead of staring at dashboards, get clear verdicts, financial projections, and prioritized action items.

---

## Install

```bash
# All skills (recommended)
npx skills add Victorpay1/intelligems-analytics
```

Or install just what you need (always include `intelligems-core`):

```bash
# Individual skills (include core for Python-based skills)
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-test-verdict
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-morning-brief
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-profit-impact
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-funnel-diagnosis
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-segment-spotlight
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-test-debrief
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-test-portfolio
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-rollout-brief

# API Docs only (no core needed)
npx skills add Victorpay1/intelligems-analytics --skill intelligems-api
```

This installs skills into your `.claude/skills/` directory.

---

## Skills

### 01 — Test Verdict

> "Should I roll this out?"

Analyzes a single test and gives a plain-English verdict: **WINNER**, **LOSER**, **FLAT**, **KEEP RUNNING**, or **TOO EARLY**. Includes risk assessment, segment nuance, and what to test next.

```
/test-verdict
```

**What you get:**
- Clear verdict with reasoning
- Risk framing ("At 82% confidence, 18% chance control was better")
- Revenue vs. conversion divergence detection
- Segment quick-check for hidden risks
- Next-test suggestion based on outcome

**API calls:** 2–3 | **Runtime:** ~5 seconds

---

### 02 — Morning Brief

> "What's happening with my tests?"

One-glance prioritized summary of all active tests. Red/yellow/green health status with action items — designed for daily use.

```
/morning-brief
```

**What you get:**
- Per-test health cards sorted by priority (RED → YELLOW → GREEN)
- Daily run rates and estimated days to verdict
- Specific action items per test
- Program pulse: total traffic, tests ready to call

**API calls:** 1 + N (N = active tests) | **Runtime:** ~15 seconds

---

### 03 — Profit Impact

> "What is this test worth in dollars?"

Translates lift percentages into annualized dollar projections. "+12% RPV" means nothing — "$47K/year" means everything.

```
/profit-impact
```

**What you get:**
- Annualized revenue impact (conservative / expected / optimistic)
- Confidence-adjusted range using CI bounds
- Break-even analysis
- Opportunity cost of waiting ("every day costs $X")
- Stakeholder-ready business case summary

**API calls:** 2 | **Runtime:** ~5 seconds

---

### 04 — API Docs

> "What endpoints does Intelligems have?"

Loads the full Intelligems External API documentation — endpoints, metrics, Python examples, health check formulas, and rate limiting strategies. The foundation for building custom integrations.

```
/intelligems-api
```

**What you get:**
- Complete API reference (experiences-list, experiences/{id}, analytics)
- 30+ available metrics with descriptions
- Ready-to-use Python code examples
- Health check formulas and thresholds
- Rate limiting strategies and gotchas

**Note:** This is a documentation skill — no Python setup required.

---

### 05 — Funnel Diagnosis

> "Where in the funnel does the variant diverge?"

Stage-by-stage funnel comparison: Add to Cart → Begin Checkout → Contact Info → Address → Purchase. Find exactly where the variant wins or loses.

```
/funnel-diagnosis
```

**What you get:**
- 5-stage funnel comparison (control vs. variant)
- Biggest gain and biggest drop identification
- Breakpoint detection where behavior flips direction
- Plain-English diagnosis with specific next steps

**API calls:** 2 | **Runtime:** ~5 seconds

---

### 06 — Segment Spotlight

> "Which segments should I target or exclude?"

Revenue-opportunity-ranked segment analysis across device type, visitor type, and traffic source. Shows per-segment dollar values and rollout recommendations.

```
/segment-spotlight
```

**What you get:**
- Revenue opportunity in annual dollars per segment
- Per-segment verdicts with confidence levels
- Contradiction detection vs. overall result
- Rollout recommendation: full, segment-specific, or hold

**API calls:** 5 | **Runtime:** ~15 seconds

---

### 07 — Test Debrief

> "What happened and what did we learn?"

Post-mortem analysis combining funnel data, segment patterns, and auto-generated customer behavior insights. Extracts learnings and suggests specific next tests.

```
/test-debrief
```

**What you get:**
- Structured post-mortem: What Happened, Why, Insights, Next
- Auto-generated customer behavior observations
- Funnel + segment pattern analysis
- Specific next-test suggestions based on findings

**API calls:** 5 | **Runtime:** ~15 seconds

---

### 08 — Test Portfolio

> "How is our testing program doing?"

Program-level scorecard across your entire testing history. No test ID needed — analyzes all active and ended experiments.

```
/test-portfolio
```

**What you get:**
- Win/loss record across all ended tests
- Test velocity tracking by month
- Coverage map: Pricing, Shipping, Offer, Content
- Gap analysis with specific recommendations

**API calls:** 2 + N (N = ended tests) | **Runtime:** varies

---

### 09 — Rollout Brief

> "Give me a doc I can share with my team."

Stakeholder-ready summary document combining verdict, financial impact, segment analysis, and recommendations. Copy-paste to Slack, email, or present in a meeting.

```
/rollout-brief
```

**What you get:**
- Executive summary with business case
- Financial projections (annual + monthly)
- Segment analysis with contradiction flags
- Clear recommendation and next steps

**API calls:** 5 | **Runtime:** ~15 seconds

---

## Slack Automation

Every skill supports `--slack <webhook_url>` to send results directly to Slack instead of the terminal. This is the recommended way to use these skills — set them up once and get daily insights delivered automatically.

### Quick setup

1. Create a Slack Incoming Webhook at https://api.slack.com/apps
2. Run any skill with the `--slack` flag to test:

```bash
# Morning brief → Slack
python3 brief.py --slack "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Test verdict → Slack
python3 verdict.py <test_id> --slack "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"

# Profit impact → Slack
python3 impact.py <test_id> --slack "https://hooks.slack.com/services/YOUR/WEBHOOK/URL"
```

3. Schedule daily delivery with the included automation script:

```bash
bash setup_automation.sh brief.py "https://hooks.slack.com/services/YOUR/WEBHOOK/URL" 8 0
```

This creates a macOS LaunchAgent that runs at your chosen time (default 8:00 AM) and posts to Slack automatically.

### What each skill looks like in Slack

- **Morning Brief** — Per-test cards with health status emoji, daily rates, and a program pulse summary
- **Test Verdict** — Verdict headline with emoji, reasoning, risk assessment, and segment insights
- **Profit Impact** — Dollar projections with ranges, opportunity cost, and business case summary

---

## Coming Soon

| Skill | What it does |
|-------|-------------|
| `/trend-tracker` | Day-by-day performance trends, seasonality, and ramp-up effects |
| `/test-comparison` | Head-to-head comparison of two tests side-by-side |
| `/landing-page-analysis` | Page-level performance breakdown by landing page |

---

## Requirements

- [Claude Code](https://claude.ai/code) (Pro, Max, Teams, or Enterprise)
- Python 3.8+
- Intelligems API key ([request access](https://portal.usepylon.com/intelligems/forms/intelligems-support-request))

---

## How It Works

Each skill is a Claude Code instruction file that guides the AI through a specific analysis workflow. Under the hood:

1. **Shared core library** (`intelligems-core`) handles API communication, metric extraction, and rate limiting
2. **Skill-specific scripts** perform the analysis and output structured results
3. **Claude interprets the output** and presents it in plain English with business context

The workspace lives at `~/intelligems-analytics/` with a Python virtual environment. First run sets everything up automatically.

---

## Architecture

```
intelligems-analytics/
├── intelligems-core/          Shared Python library
│   ├── SKILL.md
│   └── references/
│       ├── ig_client.py       API client + retry logic
│       ├── ig_metrics.py      Metric extraction helpers
│       ├── ig_helpers.py      Formatting + utilities
│       ├── ig_config.py       Thresholds + constants
│       ├── ig_slack.py        Slack Block Kit formatting
│       ├── setup_workspace.sh Workspace setup script
│       └── setup_automation.sh LaunchAgent scheduler
├── test-verdict/              01 — Single test verdict
│   ├── SKILL.md
│   └── references/verdict.py
├── morning-brief/             02 — Daily summary
│   ├── SKILL.md
│   └── references/brief.py
├── profit-impact/             03 — Financial projections
│   ├── SKILL.md
│   └── references/impact.py
├── intelligems-api/           04 — API documentation
│   ├── SKILL.md
│   └── references/external-api.md
├── funnel-diagnosis/          05 — Funnel comparison
│   ├── SKILL.md
│   └── references/funnel.py
├── segment-spotlight/         06 — Segment analysis
│   ├── SKILL.md
│   └── references/spotlight.py
├── test-debrief/              07 — Post-mortem
│   ├── SKILL.md
│   └── references/debrief.py
├── test-portfolio/            08 — Program scorecard
│   ├── SKILL.md
│   └── references/portfolio.py
├── rollout-brief/             09 — Stakeholder doc
│   ├── SKILL.md
│   └── references/rollout.py
└── docs/index.html            Landing page
```

---

## Thresholds

These follow the Intelligems philosophy: **80% confidence is enough.** We're not making cancer medicine.

| Threshold | Value | Meaning |
|-----------|-------|---------|
| Confidence | 80% | Probability to beat baseline needed to call a winner |
| Min runtime | 10 days | Don't issue verdicts before this |
| Min orders | 30 | Not enough data below this |
| Flat zone | ±2% | Lift within this range = effectively flat |

---

## Rate Limiting

The Intelligems API allows ~4 requests before a 25–60 second cooldown. All skills handle this automatically with exponential backoff retry. No action needed on your end.

---

## License

MIT

---

Built for the [Intelligems](https://intelligems.io) community by [Victorpay1](https://github.com/Victorpay1).
