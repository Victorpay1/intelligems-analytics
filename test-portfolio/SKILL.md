---
name: intelligems-test-portfolio
description: Program-level scorecard for your entire Intelligems testing program. Shows win rate, test velocity, coverage gaps, and suggests what to test next.
---

# /test-portfolio

Program-level scorecard for your entire testing program. **Win rate**, **test velocity**, **coverage gaps**, and **what to test next**.

No test ID needed — this analyzes your full testing history.

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

## Step 2: Copy Portfolio Script

```bash
cp references/portfolio.py ~/intelligems-analytics/portfolio.py
```

---

## Step 3: Run Analysis

No test selection needed — the script analyzes all tests automatically.

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 portfolio.py
```

The script will:
1. Fetch all active AND ended experiments
2. Fetch overview analytics for each ended test to determine outcomes
3. Calculate win rate, test velocity, and coverage
4. Identify gaps and suggest next tests

**Note:** This makes 2 + N API calls (N = number of ended tests). For accounts with many tests, this may take a minute due to rate limiting.

---

## Step 4: Present Scorecard

Read the output and present conversationally:

### 1. Program Summary
Quick stats: total tests, win rate, average test duration.

### 2. Win/Loss Record
How many winners, losers, flat results.

### 3. Test Velocity
Tests per month — are you testing enough?

### 4. Coverage Map
Which test types (Pricing, Shipping, Content, Offer) have been used, with counts.

### 5. Coverage Gaps
What hasn't been tested yet — and why it matters.

### 6. Active Tests
Quick status of currently running tests.

### 7. What to Test Next
Specific suggestions based on gaps and past results.

---

## Step 5: Set Up Slack Automation (Optional)

```bash
cd ~/intelligems-analytics && source venv/bin/activate && python3 portfolio.py --slack "<webhook_url>"
```

---

## Notes

- **API-heavy:** This skill makes many API calls (one per ended test). The built-in throttling handles rate limits automatically.
- **No test ID needed:** This is a program-level view, not a single-test view.
- **Win rate uses the same thresholds** as `/test-verdict`: 80% confidence, ±2% neutral zone, 30 minimum orders.
- **Test velocity:** Calculated from test start dates, grouped by month.
