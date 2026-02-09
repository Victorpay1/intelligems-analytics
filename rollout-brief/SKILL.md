---
name: intelligems-rollout-brief
description: Stakeholder-ready summary document for any Intelligems A/B test. Combines verdict, financial impact, segment analysis, and recommendations into a single shareable brief.
---

# /rollout-brief

Stakeholder-ready summary document for any A/B test. Combines **verdict**, **financial impact**, **segment analysis**, and **recommendations** into a single shareable brief.

Copy-paste to Slack, email, or present in a meeting.

Works with both **active** and **ended** tests.

---

## Step 0: Workspace Check

```bash
test -d ~/intelligems-analytics/venv && test -f ~/intelligems-analytics/ig_client.py && echo "READY" || echo "NEEDS_SETUP"
```

**If NEEDS_SETUP:** Run the `/intelligems-core` skill first.

---

## Step 1: Get API Key

Check for existing key and ask if missing. Same pattern as other skills.

---

## Step 2: Copy Rollout Script

```bash
cp references/rollout.py ~/intelligems-analytics/rollout.py
```

---

## Step 3: Select Test

Pass a test ID directly or let the script list active experiments.

---

## Step 4: Run Analysis

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 rollout.py [optional_test_id]
```

The script will:
1. Fetch test details + overview analytics + 3 segment types
2. Compute verdict, financial projections, and segment analysis
3. Generate a structured stakeholder brief

---

## Step 5: Present Brief

The output is already formatted as a stakeholder document. Present it directly — it's designed to be shared as-is.

Sections:
1. **Executive Summary** — 2-3 sentence verdict + business case
2. **Test Details** — Name, type, runtime, traffic
3. **Results** — Primary metric with verdict
4. **Financial Impact** — Projected annual/monthly impact
5. **Segment Analysis** — Key segments with rollout implications
6. **Recommendation** — Clear action with reasoning
7. **Next Steps** — Concrete follow-up actions

---

## Step 6: Set Up Slack Automation (Optional)

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 rollout.py <test_id> --slack "<webhook_url>"
```

---

## Notes

- **5 API calls** — 1 detail + 1 overview + 3 segment types.
- **Designed for sharing** — The terminal output reads like a document, not a data dump.
- **Combines other skills' logic** — Uses verdict, profit impact, and segment analysis in one output.
- **Slack output** — Comprehensive Block Kit message with all sections.
