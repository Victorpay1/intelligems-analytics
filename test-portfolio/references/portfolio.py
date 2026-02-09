"""
Intelligems Analytics — Test Portfolio

Program-level scorecard: win rate, test velocity, coverage gaps,
and what to test next across your entire testing history.

Usage:
    python3 portfolio.py                              # Full scorecard
    python3 portfolio.py --slack <webhook_url>        # Send to Slack
"""

import sys
import os
from datetime import datetime
from collections import defaultdict
from dotenv import load_dotenv

from ig_client import IntelligemsAPI
from ig_slack import (
    parse_slack_args, send_to_slack,
    header_block, section_block, fields_block, divider_block, context_block,
    status_emoji,
)
from ig_metrics import (
    get_metric_uplift,
    get_metric_confidence,
    get_total_visitors,
    get_total_orders,
    has_cogs_data,
    primary_revenue_metric,
)
from ig_helpers import (
    find_control,
    find_variants,
    get_variation_name,
    runtime_days,
    runtime_display,
    fmt_lift,
    fmt_pct,
    fmt_confidence,
    fmt_currency,
    fmt_number,
    detect_test_type,
    daily_visitors,
)
from ig_config import (
    MIN_CONFIDENCE, NEUTRAL_LIFT_THRESHOLD,
    VERDICT_MIN_RUNTIME, VERDICT_MIN_ORDERS, METRIC_LABELS,
)


# ── Constants ────────────────────────────────────────────────────────────

ALL_TEST_TYPES = ["Pricing", "Shipping", "Offer", "Content"]


# ── Helpers ──────────────────────────────────────────────────────────────


def compute_verdict(p2bb, uplift, days, total_orders):
    """Determine verdict for a test."""
    if days < VERDICT_MIN_RUNTIME or total_orders < VERDICT_MIN_ORDERS:
        return "TOO EARLY"
    if p2bb is None or uplift is None:
        return "TOO EARLY"
    if p2bb >= MIN_CONFIDENCE and uplift > NEUTRAL_LIFT_THRESHOLD:
        return "WINNER"
    if (1 - p2bb) >= MIN_CONFIDENCE and uplift < -NEUTRAL_LIFT_THRESHOLD:
        return "LOSER"
    if days >= 21 and abs(uplift) <= NEUTRAL_LIFT_THRESHOLD:
        return "FLAT"
    return "KEEP RUNNING"


def best_variant_metrics(variants, metrics, metric_name):
    """Get the best variant's uplift and confidence."""
    best_uplift = None
    best_conf = None
    for v in variants:
        uplift = get_metric_uplift(metrics, metric_name, v["id"])
        if uplift is not None and (best_uplift is None or uplift > best_uplift):
            best_uplift = uplift
            best_conf = get_metric_confidence(metrics, metric_name, v["id"])
    return best_uplift, best_conf


def get_start_month(experiment):
    """Extract YYYY-MM from experiment start timestamp."""
    ts = experiment.get("startedAtTs") or experiment.get("startedAt")
    if not ts:
        return None
    dt = datetime.fromtimestamp(ts / 1000)
    return dt.strftime("%Y-%m")


def compute_ended_runtime(experiment):
    """Calculate runtime for an ended experiment."""
    started = experiment.get("startedAtTs") or experiment.get("startedAt")
    ended = experiment.get("endedAtTs") or experiment.get("endedAt")
    if not started:
        return 0
    start_dt = datetime.fromtimestamp(started / 1000)
    if ended:
        end_dt = datetime.fromtimestamp(ended / 1000)
    else:
        end_dt = datetime.now()
    return max((end_dt - start_dt).days, 0)


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env")
    if os.path.exists(env_path):
        load_dotenv(env_path)
    else:
        load_dotenv()

    api_key = os.getenv("INTELLIGEMS_API_KEY")
    if not api_key or api_key == "your_api_key_here":
        print("ERROR: No API key found.")
        sys.exit(1)

    api = IntelligemsAPI(api_key)
    slack_url = parse_slack_args(sys.argv)

    # ── Fetch all experiments ─────────────────────────────────────
    print("Fetching active experiments...")
    active = api.get_active_experiments()
    print("Found {0} active".format(len(active)))

    print("Fetching ended experiments...")
    ended = api.get_ended_experiments()
    print("Found {0} ended".format(len(ended)))

    all_tests = active + ended
    if not all_tests:
        print("\nNo experiments found. Your testing program hasn't started yet!")
        sys.exit(0)

    # ── Analyze ended tests ───────────────────────────────────────
    print("\nAnalyzing ended tests for verdicts...")
    ended_results = []

    for exp in ended:
        name = exp.get("name", "Unnamed")
        exp_id = exp.get("id", "")
        test_type = detect_test_type(exp)
        days = compute_ended_runtime(exp)
        start_month = get_start_month(exp)

        print("  Analyzing: {0}...".format(name[:40]))
        try:
            analytics = api.get_overview_analytics(exp_id)
            metrics = analytics.get("metrics", [])
        except Exception as e:
            print("    Warning: Could not fetch analytics: {0}".format(e))
            ended_results.append({
                "name": name,
                "type": test_type,
                "days": days,
                "month": start_month,
                "verdict": "ERROR",
                "uplift": None,
                "confidence": None,
            })
            continue

        if not metrics:
            ended_results.append({
                "name": name,
                "type": test_type,
                "days": days,
                "month": start_month,
                "verdict": "NO DATA",
                "uplift": None,
                "confidence": None,
            })
            continue

        variations = exp.get("variations", [])
        variant_list = find_variants(variations)
        total_orders = get_total_orders(metrics)
        rev_metric = primary_revenue_metric(metrics)

        uplift, conf = best_variant_metrics(variant_list, metrics, rev_metric)
        verdict = compute_verdict(conf, uplift, days, total_orders)

        ended_results.append({
            "name": name,
            "type": test_type,
            "days": days,
            "month": start_month,
            "verdict": verdict,
            "uplift": uplift,
            "confidence": conf,
        })

    # ── Compute scorecard metrics ─────────────────────────────────

    # Win rate (only count callable tests)
    callable_verdicts = [r for r in ended_results if r["verdict"] in ("WINNER", "LOSER", "FLAT")]
    winners = [r for r in callable_verdicts if r["verdict"] == "WINNER"]
    losers = [r for r in callable_verdicts if r["verdict"] == "LOSER"]
    flat = [r for r in callable_verdicts if r["verdict"] == "FLAT"]
    win_rate = len(winners) / len(callable_verdicts) * 100 if callable_verdicts else 0

    # Average runtime
    all_days = [r["days"] for r in ended_results if r["days"] > 0]
    avg_runtime = sum(all_days) / len(all_days) if all_days else 0

    # Test velocity (tests started per month)
    monthly_counts = defaultdict(int)
    for exp in all_tests:
        month = get_start_month(exp)
        if month:
            monthly_counts[month] += 1
    months_sorted = sorted(monthly_counts.keys())
    if len(months_sorted) >= 2:
        tests_per_month = sum(monthly_counts.values()) / len(months_sorted)
    elif len(months_sorted) == 1:
        tests_per_month = monthly_counts[months_sorted[0]]
    else:
        tests_per_month = 0

    # Coverage map
    type_counts = defaultdict(int)
    for exp in all_tests:
        t = detect_test_type(exp)
        type_counts[t] += 1

    coverage_gaps = [t for t in ALL_TEST_TYPES if t not in type_counts]

    # Active tests summary
    active_summary = []
    for exp in active:
        name = exp.get("name", "Unnamed")
        test_type = detect_test_type(exp)
        ts = exp.get("startedAtTs") or exp.get("startedAt")
        d = runtime_days(ts)
        active_summary.append({
            "name": name,
            "type": test_type,
            "days": d,
        })

    # ── Suggestions ───────────────────────────────────────────────
    suggestions = []

    if coverage_gaps:
        for gap in coverage_gaps:
            reasons = {
                "Pricing": "Pricing tests often have the highest revenue impact per visitor.",
                "Shipping": "Shipping is a major checkout friction point — worth testing thresholds.",
                "Offer": "Offer/discount testing can reveal optimal promotional strategies.",
                "Content": "Content tests help refine messaging and product presentation.",
            }
            suggestions.append("Try {0} testing — {1}".format(gap, reasons.get(gap, "")))

    if win_rate < 30 and len(callable_verdicts) >= 3:
        suggestions.append("Win rate is low ({0:.0f}%). Consider testing bolder changes or different levers.".format(win_rate))

    if tests_per_month < 2 and len(months_sorted) >= 2:
        suggestions.append("Testing velocity is low ({0:.1f}/month). Aim for 2-4 tests per month.".format(tests_per_month))

    if not suggestions:
        suggestions.append("Program is healthy. Keep testing and iterating on winners.")

    # ── Output ────────────────────────────────────────────────────
    if not slack_url:
        print("\n" + "=" * 60)
        print("  TEST PORTFOLIO SCORECARD")
        print("=" * 60)

        # Program summary
        print("\n--- PROGRAM SUMMARY ---")
        print("  Total tests: {0} ({1} ended, {2} active)".format(
            len(all_tests), len(ended), len(active)))
        print("  Win rate: {0:.0f}% ({1} winners / {2} callable)".format(
            win_rate, len(winners), len(callable_verdicts)))
        print("  Average runtime: {0:.0f} days".format(avg_runtime))
        print("  Test velocity: {0:.1f} tests/month".format(tests_per_month))
        print()

        # Win/loss record
        print("--- WIN/LOSS RECORD ---")
        print("  Winners:  {0}".format(len(winners)))
        print("  Losers:   {0}".format(len(losers)))
        print("  Flat:     {0}".format(len(flat)))
        too_early = len([r for r in ended_results if r["verdict"] in ("TOO EARLY", "KEEP RUNNING")])
        if too_early:
            print("  Inconclusive: {0}".format(too_early))
        print()

        # Winners detail
        if winners:
            print("  Top winners:")
            winners_sorted = sorted(winners, key=lambda r: r["uplift"] or 0, reverse=True)
            for w in winners_sorted[:5]:
                print("    {0} ({1}): {2} lift".format(
                    w["name"][:35], w["type"], fmt_lift(w["uplift"])))
            print()

        # Coverage
        print("--- COVERAGE MAP ---")
        for test_type in ALL_TEST_TYPES:
            count = type_counts.get(test_type, 0)
            bar = "#" * min(count, 20)
            status = "  " if count > 0 else "  GAP"
            print("  {0:<10} {1:>3} tests  {2}{3}".format(
                test_type, count, bar, status if count == 0 else ""))
        print()

        if coverage_gaps:
            print("  Gaps: {0}".format(", ".join(coverage_gaps)))
            print()

        # Test velocity by month
        if months_sorted:
            print("--- TEST VELOCITY ---")
            for month in months_sorted[-6:]:  # Last 6 months
                count = monthly_counts[month]
                bar = "#" * count
                print("  {0}  {1:>2} tests  {2}".format(month, count, bar))
            print()

        # Active tests
        if active_summary:
            print("--- ACTIVE TESTS ---")
            for t in active_summary:
                print("  {0} ({1}, {2} days)".format(
                    t["name"][:40], t["type"], t["days"]))
            print()

        # Suggestions
        print("--- WHAT TO TEST NEXT ---")
        for i, s in enumerate(suggestions, 1):
            print("  {0}. {1}".format(i, s))
        print()
        print("=" * 60)

    else:
        # ── Slack output ──────────────────────────────────────
        blocks = []

        blocks.append(header_block("Test Portfolio Scorecard"))

        # Summary fields
        blocks.append(fields_block([
            "*Total Tests:* {0}".format(len(all_tests)),
            "*Win Rate:* {0:.0f}%".format(win_rate),
            "*Avg Runtime:* {0:.0f} days".format(avg_runtime),
            "*Velocity:* {0:.1f}/month".format(tests_per_month),
        ]))

        blocks.append(divider_block())

        # Record
        blocks.append(section_block(
            "*Win/Loss Record*\n"
            "Winners: {0} | Losers: {1} | Flat: {2}".format(
                len(winners), len(losers), len(flat))
        ))

        # Top winners
        if winners:
            winners_sorted = sorted(winners, key=lambda r: r["uplift"] or 0, reverse=True)
            winner_lines = []
            for w in winners_sorted[:3]:
                winner_lines.append("- {0} ({1}): {2}".format(
                    w["name"][:30], w["type"], fmt_lift(w["uplift"])))
            blocks.append(section_block(
                "*Top Winners*\n" + "\n".join(winner_lines)))

        # Coverage
        coverage_lines = []
        for test_type in ALL_TEST_TYPES:
            count = type_counts.get(test_type, 0)
            status = "{0} tests".format(count) if count > 0 else ":warning: GAP"
            coverage_lines.append("*{0}:* {1}".format(test_type, status))
        blocks.append(section_block(
            "*Coverage Map*\n" + "\n".join(coverage_lines)))

        blocks.append(divider_block())

        # Active tests
        if active_summary:
            active_lines = []
            for t in active_summary:
                active_lines.append("- {0} ({1}, {2}d)".format(
                    t["name"][:30], t["type"], t["days"]))
            blocks.append(section_block(
                "*Active Tests ({0})*\n".format(len(active_summary)) +
                "\n".join(active_lines)))

        # Suggestions
        blocks.append(section_block(
            "*What to Test Next*\n" +
            "\n".join("- {0}".format(s) for s in suggestions)
        ))

        blocks.append(context_block("Powered by Intelligems Analytics"))

        success = send_to_slack(slack_url, blocks, "Test Portfolio Scorecard")
        if success:
            print("Sent to Slack ✓")
        else:
            print("Failed to send to Slack.")


if __name__ == "__main__":
    main()
