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
# Morning Brief only
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-morning-brief

# Test Verdict only
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-test-verdict

# Profit Impact only
npx skills add Victorpay1/intelligems-analytics --skill intelligems-core --skill intelligems-profit-impact
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
| `/test-debrief` | Post-mortem for any test — extract learnings and next tests |
| `/funnel-diagnosis` | Where in the funnel is it winning or losing? |
| `/test-portfolio` | Program-level scorecard: win rate, velocity, coverage gaps |
| `/segment-spotlight` | Revenue-opportunity-ranked segments with dollar values |
| `/rollout-brief` | Stakeholder-ready summary document |

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
├── test-verdict/
│   ├── SKILL.md
│   └── references/
│       └── verdict.py
├── morning-brief/
│   ├── SKILL.md
│   └── references/
│       └── brief.py
└── profit-impact/
    ├── SKILL.md
    └── references/
        └── impact.py
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
