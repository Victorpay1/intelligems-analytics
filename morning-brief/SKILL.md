---
name: intelligems-morning-brief
description: Get a prioritized morning summary of all your active Intelligems tests. Shows health status, action items, emerging winners, and daily run rates — designed for daily use.
---

# /morning-brief

One-glance prioritized summary of ALL active tests. Red/yellow/green health status, action items, emerging signals. The CEO Morning Brief.

---

## Step 0: Workspace Check

Check if `~/intelligems-analytics/` exists with the core libraries and virtual environment.

```bash
ls ~/intelligems-analytics/venv/bin/activate && ls ~/intelligems-analytics/ig_client.py
```

**If the workspace does not exist**, run the `/intelligems-core` skill first to set it up. Copy the core libraries from `intelligems-core/references/` and run `setup_workspace.sh`.

---

## Step 1: Get API Key

Check if the `.env` file has a real API key (not the placeholder):

```bash
source ~/intelligems-analytics/venv/bin/activate
python3 -c "
from dotenv import load_dotenv
import os
load_dotenv(os.path.expanduser('~/intelligems-analytics/.env'))
key = os.getenv('INTELLIGEMS_API_KEY', '')
if not key or key == 'your_api_key_here':
    print('NEED_KEY')
else:
    print('OK')
"
```

If `NEED_KEY`, ask the user:

> "What's your Intelligems API key? You can get one by contacting support@intelligems.io"

Then save it:

```bash
echo "INTELLIGEMS_API_KEY=<user's key>" > ~/intelligems-analytics/.env
```

**Never hardcode or assume an API key.**

---

## Step 2: Copy brief.py

Copy the morning brief script from this skill's references into the workspace:

```bash
cp references/brief.py ~/intelligems-analytics/brief.py
```

---

## Step 3: Run

Execute the brief script in the workspace using the virtual environment:

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 brief.py
```

The script prints progress messages as it fetches data, then outputs the full morning brief.

---

## Step 4: Present

Read the script output and present it to the user as a clean, scannable morning brief:

1. **Date and time header** — "Morning Brief — {date}"
2. **Per-test cards sorted by priority** — RED tests first (need attention), then YELLOW (watch), then GREEN (healthy)
3. **Each card shows:**
   - Test name and type
   - Runtime, visitors, orders with daily rates
   - Best variant performance (primary metric + conversion)
   - Health status with color indicator and action item
   - Estimated days to verdict (or "Ready to call")
4. **Action items called out prominently** — anything RED or YELLOW gets a clear callout
5. **Program Pulse summary at the end** — total active tests, daily run rates, how many are ready to call

**Formatting guidance:**
- Use bold for test names and status labels
- Use emoji sparingly: only for status (red/yellow/green circles)
- Keep it scannable — this is meant for a quick morning read
- Lead with what needs attention, close with the overall pulse

---

## Step 5: Set Up Slack Automation (Recommended)

The morning brief is designed for daily delivery to Slack. This is the recommended way to use it.

**1. Get a Slack webhook URL**

Ask the user:

> "To get your morning brief in Slack every day, you need an Incoming Webhook URL. Go to https://api.slack.com/apps → Create New App → Incoming Webhooks → Add New Webhook. Which channel should the brief go to?"

**2. Copy the Slack module**

```bash
cp ../intelligems-core/references/ig_slack.py ~/intelligems-analytics/ig_slack.py
```

**3. Test it**

Run the brief with the `--slack` flag:

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 brief.py --slack "<webhook_url>"
```

Verify the message appears in Slack with per-test cards, status indicators, and program pulse.

**4. Schedule daily delivery**

Copy and run the automation setup script:

```bash
cp ../intelligems-core/references/setup_automation.sh ~/intelligems-analytics/
bash ~/intelligems-analytics/setup_automation.sh brief.py "<webhook_url>" 8 0
```

This creates a macOS LaunchAgent that runs the morning brief every day at 8:00 AM and posts to Slack.

Ask the user what time they'd like it (default 8 AM). Adjust the hour parameter accordingly.

---

## Notes

- **Slack output:** When using `--slack`, results are formatted as Slack Block Kit messages with per-test cards sorted by priority, status emoji, and a program pulse summary.
- **Terminal output:** Without `--slack`, the brief prints to the terminal as before — useful for on-demand checks.
