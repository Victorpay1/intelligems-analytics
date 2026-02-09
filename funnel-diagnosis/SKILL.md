---
name: intelligems-funnel-diagnosis
description: Stage-by-stage funnel comparison for any Intelligems A/B test. Find exactly where the variant diverges from control — Add to Cart, Checkout, Purchase — with plain-English diagnosis.
---

# /funnel-diagnosis

Stage-by-stage funnel comparison for any A/B test. Find exactly where the variant diverges from control: **Add to Cart → Begin Checkout → Contact Info → Address → Purchase**.

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

**If NO_KEY:** Ask the user:

> "What's your Intelligems API key? You can get one by contacting support@intelligems.io"

Then save it:

```bash
echo "INTELLIGEMS_API_KEY=<user's key>" > ~/intelligems-analytics/.env
```

**Never hardcode or assume an API key.**

---

## Step 2: Copy Funnel Script

Copy the funnel diagnosis script from this skill's references into the workspace:

```bash
cp references/funnel.py ~/intelligems-analytics/funnel.py
```

---

## Step 3: Select Test

The script accepts an optional test ID as an argument.

**If the user already specified a test ID or name:**
- Pass the ID directly: `python3 funnel.py <test_id>`

**If no test was specified:**
- Run the script without arguments — it will list all active experiments and ask the user to pick one.

---

## Step 4: Run Analysis

Execute the funnel script with the workspace virtual environment:

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 funnel.py [optional_test_id]
```

The script will:
1. Fetch overview analytics for the selected test
2. Extract metrics for each funnel stage (Add to Cart → Purchase)
3. Compare control vs. variant at each stage
4. Identify the biggest gain, biggest drop, and breakpoint
5. Print a stage-by-stage comparison with plain-English diagnosis

---

## Step 5: Present Diagnosis

Read the script output and present results conversationally. Structure your response like this:

### 1. Quick Summary

One sentence: where the variant wins and where it struggles.
> "The variant lifts Add to Cart by +8.2%, but loses ground at checkout — conversion only up +1.3%."

### 2. Stage-by-Stage Table

Present the funnel stages as a clear comparison:

| Stage | Control | Variant | Lift | Confidence |
|-------|---------|---------|------|------------|
| Add to Cart | 12.3% | 13.3% | +8.2% | 85% |
| Begin Checkout | ... | ... | ... | ... |
| ... | ... | ... | ... | ... |

### 3. Key Findings

Highlight the most important findings:
- **Biggest gain** — Which stage improved most
- **Biggest drop** — Which stage lost most (if any)
- **Breakpoint** — Where behavior diverges (e.g., "More people add to cart, but they drop off at checkout")

### 4. Diagnosis

Plain-English explanation of what the funnel data means:
> "The variant is great at getting people interested (add to cart), but the checkout experience needs work. Consider testing checkout-specific changes next."

### 5. Next Steps

Specific suggestions based on the funnel findings.

---

## Step 6: Set Up Slack Automation (Optional)

If the user wants funnel diagnoses delivered to Slack:

**1. Get a Slack webhook URL**

> "To send results to Slack, you need an Incoming Webhook URL. Go to https://api.slack.com/apps → Create New App → Incoming Webhooks → Add New Webhook."

**2. Copy the Slack module**

```bash
cp ../intelligems-core/references/ig_slack.py ~/intelligems-analytics/ig_slack.py
```

**3. Test it**

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 funnel.py <test_id> --slack "<webhook_url>"
```

---

## Notes

- **Funnel stages come from overview analytics** — no extra API calls needed beyond the standard overview.
- **Missing stages:** Some tests may not have data for all 5 funnel stages. The script handles this gracefully by showing "No data" for missing stages.
- **COGS awareness:** When COGS data exists, revenue metrics use Gross Profit per Visitor instead of Revenue per Visitor.
- **Slack output:** Uses Slack Block Kit formatting with a clean stage comparison.
