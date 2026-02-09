---
name: intelligems-segment-spotlight
description: Revenue-opportunity-ranked segment analysis for any Intelligems A/B test. Shows per-segment dollar values, verdicts, and rollout recommendations across device, visitor type, and traffic source.
---

# /segment-spotlight

Revenue-opportunity-ranked segment analysis for any A/B test. Shows per-segment **dollar values**, verdicts, and **rollout recommendations** across device type, visitor type, and traffic source.

Works with both **active** and **ended** tests.

---

## Step 0: Workspace Check

Check if the shared workspace exists and is ready:

```bash
test -d ~/intelligems-analytics/venv && test -f ~/intelligems-analytics/ig_client.py && echo "READY" || echo "NEEDS_SETUP"
```

**If NEEDS_SETUP:** Run the `/intelligems-core` skill first to set up the workspace.

---

## Step 1: Get API Key

Check if an API key is already configured:

```bash
source ~/intelligems-analytics/venv/bin/activate && python3 -c "
from dotenv import load_dotenv; import os
load_dotenv(os.path.expanduser('~/intelligems-analytics/.env'))
key = os.getenv('INTELLIGEMS_API_KEY', '')
print('HAS_KEY' if key and key != 'your_api_key_here' else 'NO_KEY')
"
```

**If NO_KEY:** Ask the user for their API key and save it.

**Never hardcode or assume an API key.**

---

## Step 2: Copy Spotlight Script

```bash
cp references/spotlight.py ~/intelligems-analytics/spotlight.py
```

---

## Step 3: Select Test

The script accepts an optional test ID as an argument.

**If the user already specified a test ID:** Pass it directly.
**If no test was specified:** The script lists active experiments for selection.

---

## Step 4: Run Analysis

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 spotlight.py [optional_test_id]
```

The script will:
1. Fetch overview analytics + all 3 segment types
2. Calculate revenue opportunity per segment
3. Rank segments by dollar value
4. Generate rollout recommendations

---

## Step 5: Present Results

Read the script output and present conversationally:

### 1. Quick Summary
One-line takeaway on segment uniformity or divergence.

### 2. Revenue Opportunity Table
Ranked by annual dollar opportunity:

| Segment | Type | Verdict | Lift | Confidence | Annual Value |
|---------|------|---------|------|------------|-------------|
| Desktop | Device | WINNER | +15% | 92% | $47,000 |
| ... | ... | ... | ... | ... | ... |

### 3. Rollout Recommendation
- **Roll out everywhere** — If all major segments win
- **Segment-specific** — If some win, some lose
- **Hold** — If mixed or insufficient data

### 4. Contradictions
Highlight any segments that contradict the overall result.

---

## Step 6: Set Up Slack Automation (Optional)

Same pattern as other skills — use `--slack <webhook_url>` flag.

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 spotlight.py <test_id> --slack "<webhook_url>"
```

---

## Notes

- **Revenue opportunity** = segment daily visitors × RPV lift × 365. This is the annualized dollar value of the lift in that segment.
- **All 3 segment types** are analyzed: device type, visitor type, traffic source.
- **Low-data segments** show "Low data" for confidence instead of a percentage.
- **COGS awareness:** Uses Gross Profit per Visitor when COGS data exists.
