---
name: intelligems-test-debrief
description: Post-mortem analysis for any Intelligems A/B test. Extracts learnings from funnel data, segment patterns, and customer behavior — then suggests what to test next based on findings.
---

# /test-debrief

Post-mortem analysis for any A/B test outcome. Extracts **learnings**, **customer behavior insights**, and **specific next-test suggestions** from funnel data and segment patterns.

Works with both **active** and **ended** tests. Most useful for tests that have reached a verdict.

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

## Step 2: Copy Debrief Script

```bash
cp references/debrief.py ~/intelligems-analytics/debrief.py
```

---

## Step 3: Select Test

Pass a test ID directly or let the script list active experiments.

For debriefs on ended tests (the most common use), the user should provide the test ID:
```bash
python3 debrief.py <test_id>
```

---

## Step 4: Run Analysis

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 debrief.py [optional_test_id]
```

The script will:
1. Fetch test details + overview analytics
2. Fetch all 3 segment types (device, visitor, source)
3. Analyze funnel stages for patterns
4. Generate customer behavior insights from segment data
5. Build a structured post-mortem with actionable next steps

---

## Step 5: Present Debrief

Read the output and present conversationally. Structure:

### 1. What Happened
The verdict and key metrics — one paragraph summary of the test outcome.

### 2. Why It Happened — Funnel Analysis
Which funnel stages drove the result? Where did behavior diverge?

### 3. Why It Happened — Segment Patterns
Which segments responded differently? Any contradictions?

### 4. Customer Behavior Insights
Auto-generated observations. Present these as **insights**, not raw data:
- "Mobile users responded 3x stronger than desktop"
- "New visitors drove most of the lift — returning visitors were flat"
- "Direct traffic saw no effect, but organic search visitors loved it"

### 5. What to Test Next
Specific, actionable suggestions based on the debrief findings — not generic advice.

---

## Step 6: Set Up Slack Automation (Optional)

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 debrief.py <test_id> --slack "<webhook_url>"
```

---

## Notes

- **Best for ended tests** — Most debriefs happen after a test concludes, but it works for active tests too.
- **5 API calls** — 1 detail + 1 overview + 3 segment types.
- **Insights are auto-generated** — The script compares segment performance to find noteworthy patterns without manual inspection.
- **COGS awareness:** Uses Gross Profit per Visitor when COGS data exists.
