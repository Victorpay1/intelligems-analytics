---
name: intelligems-test-verdict
description: Analyze any Intelligems A/B test and get a plain-English verdict — should you roll it out, keep running, or kill it? Includes risk assessment, segment nuance, and profit impact.
---

# /test-verdict

Analyze any Intelligems A/B test and deliver a clear verdict: **WINNER**, **LOSER**, **FLAT**, **KEEP RUNNING**, or **TOO EARLY**. Includes risk framing, revenue-vs-conversion analysis, and a device segment quick-check.

Works with both **active** and **ended** tests.

---

## Step 0: Workspace Check

Check if the shared workspace exists and is ready:

```bash
test -d ~/intelligems-analytics/venv && test -f ~/intelligems-analytics/ig_client.py && echo "READY" || echo "NEEDS_SETUP"
```

**If NEEDS_SETUP:** Run the `/intelligems-core` skill first to set up the workspace. This installs the shared Python libraries and virtual environment at `~/intelligems-analytics/`.

Specifically:
1. Copy `setup_workspace.sh` from the `intelligems-core` skill's `references/` folder and run it.
2. Copy all four core Python files (`ig_client.py`, `ig_metrics.py`, `ig_helpers.py`, `ig_config.py`) from `intelligems-core/references/` into `~/intelligems-analytics/`.

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

## Step 2: Copy Verdict Script

Copy the verdict script from this skill's references into the workspace:

```bash
cp references/verdict.py ~/intelligems-analytics/verdict.py
```

---

## Step 3: Select Test

The script accepts an optional test ID as an argument.

**If the user already specified a test ID or name:**
- Pass the ID directly: `python3 verdict.py <test_id>`

**If no test was specified:**
- Run the script without arguments — it will list all active experiments and ask the user to pick one.
- If the user wants to analyze an ended test, they need to provide the test ID directly.

---

## Step 4: Run Analysis

Execute the verdict script with the workspace virtual environment:

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 verdict.py [optional_test_id]
```

The script will:
1. Fetch overview analytics for the selected test
2. Run a maturity check (enough time, visitors, orders?)
3. Compute the verdict based on confidence and uplift
4. Check revenue vs. conversion alignment
5. Fetch device-type segments for a quick contradiction check
6. Print all results in a structured format

---

## Step 5: Present Verdict

Read the script output and present results conversationally. Structure your response like this:

### 1. Big Verdict Headline

Lead with the verdict in bold. Make it unmistakable:
- **WINNER** — "This test is a winner. Roll it out."
- **LOSER** — "This test is hurting performance. Kill it."
- **FLAT** — "No meaningful difference. Your call."
- **KEEP RUNNING** — "Promising signals, but not enough data yet."
- **TOO EARLY** — "Way too early to tell. Check back later."

### 2. Plain-English Reasoning

Explain WHY in one or two sentences. No jargon. Reference the actual numbers.

### 3. Risk Framing

Always frame confidence as risk:
> "At 82% confidence, there's an 18% chance the control was actually better."

If COGS data exists, note whether profit and revenue agree.

### 4. Revenue vs. Conversion Note

If they diverge, explain what it means in plain English:
> "Revenue is up but conversion is down — fewer people are buying, but those who do spend more. That's worth watching."

If aligned, just say: "Revenue and conversion are moving together — clean signal."

### 5. Segment Quick-Check

Highlight the most interesting finding from the device segment check. Especially flag contradictions:
> "Overall this is a winner, but it's actually losing on mobile. Worth investigating before rolling out."

### 6. What to Test Next

Based on the test type and outcome, suggest what to explore next. Examples:
- **Pricing winner:** "Try testing a slightly higher price point to find the ceiling."
- **Shipping loser:** "Consider testing free shipping with a minimum order threshold."
- **Content flat:** "The messaging isn't moving the needle. Try a completely different angle."
- **Too early:** "Just wait. Check back in X days when you'll have enough orders."

---

## Step 6: Set Up Slack Automation (Optional)

If the user wants verdicts delivered to Slack automatically, set up a Slack integration:

**1. Get a Slack webhook URL**

Ask the user:

> "To send verdicts to Slack, you need an Incoming Webhook URL. Go to https://api.slack.com/apps → Create New App → Incoming Webhooks → Add New Webhook. Which channel should verdicts go to?"

**2. Copy the Slack module**

```bash
cp ../intelligems-core/references/ig_slack.py ~/intelligems-analytics/ig_slack.py
```

**3. Test it**

Run the verdict with the `--slack` flag:

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 verdict.py <test_id> --slack "<webhook_url>"
```

Verify the message appears in Slack with the verdict emoji, reasoning, risk, and segments.

**4. Schedule it (optional)**

Copy and run the automation setup script:

```bash
cp ../intelligems-core/references/setup_automation.sh ~/intelligems-analytics/
bash ~/intelligems-analytics/setup_automation.sh verdict.py "<webhook_url>" 9 0
```

This creates a macOS LaunchAgent that runs the verdict daily at 9:00 AM and posts to Slack.

---

## Notes

- **Ended tests:** The skill works with ended tests — just pass the test ID directly. The script handles both active and ended tests.
- **Multi-variation tests:** If a test has multiple variants, the script analyzes each and highlights the best one.
- **COGS data:** When available, the script automatically uses Gross Profit per Visitor (GPV) instead of Revenue per Visitor (RPV) as the primary metric.
- **Slack output:** When using `--slack`, the script formats results as Slack Block Kit messages with verdict emoji, reasoning, risk assessment, and segment insights.
