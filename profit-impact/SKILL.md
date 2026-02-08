---
name: intelligems-profit-impact
description: Translate A/B test lift percentages into annualized dollar projections. Shows conservative and optimistic revenue impact, break-even analysis, and opportunity cost of waiting.
---

# /intelligems-profit-impact

The CFO tool. Turns "+12% RPV" into "$47K/year" — the language that gets tests shipped.

Takes any Intelligems A/B test and projects the financial impact: conservative, expected, and optimistic annual revenue, break-even analysis, opportunity cost of delays, and a stakeholder-ready summary.

---

## Step 0: Workspace Check

Check if the workspace exists:

```bash
ls ~/intelligems-analytics/venv/bin/activate 2>/dev/null && echo "READY" || echo "NEEDS_SETUP"
```

**If NEEDS_SETUP:** Copy and run the setup script from `intelligems-core/references/`:

```bash
bash ../intelligems-core/references/setup_workspace.sh
```

Then copy the core libraries:

```bash
cp ../intelligems-core/references/ig_client.py ~/intelligems-analytics/
cp ../intelligems-core/references/ig_metrics.py ~/intelligems-analytics/
cp ../intelligems-core/references/ig_helpers.py ~/intelligems-analytics/
cp ../intelligems-core/references/ig_config.py ~/intelligems-analytics/
```

---

## Step 1: Get API Key

Check if the API key is already configured:

```bash
grep -v "your_api_key_here" ~/intelligems-analytics/.env 2>/dev/null | grep "INTELLIGEMS_API_KEY=" | head -1
```

**If no valid key found**, ask the user:

> "What's your Intelligems API key? You can get one by contacting support@intelligems.io"

Then save it:

```bash
echo "INTELLIGEMS_API_KEY=<user's key>" > ~/intelligems-analytics/.env
```

**Never hardcode or assume an API key.**

---

## Step 2: Copy Impact Script

Copy the profit impact script to the workspace:

```bash
cp references/impact.py ~/intelligems-analytics/impact.py
```

Also ensure the core libraries are up to date:

```bash
cp ../intelligems-core/references/ig_client.py ~/intelligems-analytics/
cp ../intelligems-core/references/ig_metrics.py ~/intelligems-analytics/
cp ../intelligems-core/references/ig_helpers.py ~/intelligems-analytics/
cp ../intelligems-core/references/ig_config.py ~/intelligems-analytics/
```

---

## Step 3: Select Test

Run the script. If the user provided a test ID, pass it as an argument:

```bash
source ~/intelligems-analytics/venv/bin/activate && cd ~/intelligems-analytics && python3 impact.py
```

Or with a specific test ID:

```bash
source ~/intelligems-analytics/venv/bin/activate && cd ~/intelligems-analytics && python3 impact.py <test_id>
```

If no test ID is provided, the script lists all active experiments and prompts for selection.

---

## Step 4: Run

The script outputs a full profit impact report to stdout. Let it run to completion.

If the script errors:
- **"No active experiments"** — The store has no running tests. Let the user know.
- **"0 orders"** — The test is too new. Suggest waiting for more data.
- **API errors** — Check the API key is valid.

---

## Step 5: Present Results

Read the script output and present it as a **financial impact report**. Frame everything in business terms:

1. **Lead with dollars** — The annual impact number comes first, front and center
2. **Show the range** — Conservative / Expected / Optimistic so stakeholders see the floor and ceiling
3. **Break-even framing** — "You can afford to lose X% of conversions and still come out ahead"
4. **Urgency** — "Every day you wait costs $X" drives action
5. **Business-case summary** — 2-3 sentences ready to paste into a Slack message or email to leadership

**Tone:** Confident but not overselling. Use the conservative number when making the strongest claims. Lead with the expected number for impact, but always caveat with the range.

**If the lift is negative:** Still present the numbers honestly. Frame as "this variant would cost you $X/year" — knowing this is valuable too.

**If confidence is low:** Flag it prominently. "These projections carry higher uncertainty — the test needs more data before acting."

---

## Step 6: Set Up Slack Automation (Optional)

If the user wants profit impact reports delivered to Slack, set up a Slack integration:

**1. Get a Slack webhook URL**

Ask the user:

> "To send profit impact reports to Slack, you need an Incoming Webhook URL. Go to https://api.slack.com/apps → Create New App → Incoming Webhooks → Add New Webhook. Which channel should reports go to?"

**2. Copy the Slack module**

```bash
cp ../intelligems-core/references/ig_slack.py ~/intelligems-analytics/ig_slack.py
```

**3. Test it**

Run the impact report with the `--slack` flag:

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 impact.py <test_id> --slack "<webhook_url>"
```

Verify the message appears in Slack with dollar projections, ranges, and business case summary.

**4. Schedule it (optional)**

Copy and run the automation setup script:

```bash
cp ../intelligems-core/references/setup_automation.sh ~/intelligems-analytics/
bash ~/intelligems-analytics/setup_automation.sh impact.py "<webhook_url>" 9 0
```

This creates a macOS LaunchAgent that runs the profit impact daily at 9:00 AM and posts to Slack.

---

## Notes

- **Slack output:** When using `--slack`, results are formatted as Slack Block Kit messages with annual impact, monthly breakdown, opportunity cost, and business case summary.
- **Terminal output:** Without `--slack`, the report prints to the terminal as before.
