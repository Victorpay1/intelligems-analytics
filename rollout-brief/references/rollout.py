"""
Intelligems Analytics — Rollout Brief

Stakeholder-ready summary document combining verdict, financial impact,
segment analysis, and recommendations into one shareable brief.

Usage:
    python3 rollout.py              # Lists active tests, prompts to pick
    python3 rollout.py <test_id>    # Brief for a specific test
    python3 rollout.py <test_id> --slack <webhook_url>   # Send to Slack
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv

from ig_client import IntelligemsAPI
from ig_slack import (
    parse_slack_args, send_to_slack,
    header_block, section_block, fields_block, divider_block, context_block,
    verdict_emoji,
)
from ig_metrics import (
    get_metric_value,
    get_metric_uplift,
    get_metric_confidence,
    get_metric_ci,
    get_total_visitors,
    get_total_orders,
    has_cogs_data,
    primary_revenue_metric,
    group_metrics_by_segment,
    get_variation_visitors,
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
    SEGMENT_TYPES, MIN_CONFIDENCE, NEUTRAL_LIFT_THRESHOLD,
    VERDICT_MIN_RUNTIME, VERDICT_MIN_ORDERS, METRIC_LABELS,
)


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


def pick_best_variant(variants, metrics, metric_name):
    """Find the variant with the highest uplift."""
    best = None
    best_uplift = None
    for v in variants:
        uplift = get_metric_uplift(metrics, metric_name, v["id"])
        if uplift is not None and (best_uplift is None or uplift > best_uplift):
            best = v
            best_uplift = uplift
    return best


def segment_verdict(p2bb, uplift, days):
    """Determine verdict for a segment."""
    if p2bb is None or uplift is None:
        return "LOW DATA"
    if p2bb >= MIN_CONFIDENCE and uplift > NEUTRAL_LIFT_THRESHOLD:
        return "WINNER"
    if (1 - p2bb) >= MIN_CONFIDENCE and uplift < -NEUTRAL_LIFT_THRESHOLD:
        return "LOSER"
    if days >= 21 and abs(uplift) <= NEUTRAL_LIFT_THRESHOLD:
        return "FLAT"
    return "KEEP RUNNING"


def build_executive_summary(
    test_name, test_type, verdict, rev_label, uplift, confidence,
    expected_annual, days
):
    """Build a 2-3 sentence executive summary."""
    parts = []

    if verdict == "WINNER":
        parts.append(
            'The "{0}" {1} test is a winner — {2} is up {3} '
            'with {4} confidence after {5} days.'.format(
                test_name, test_type.lower(), rev_label,
                fmt_lift(uplift), fmt_confidence(confidence), days,
            )
        )
        if expected_annual and expected_annual > 0:
            parts.append(
                "Projected annual impact: {0}. Recommend rolling out immediately.".format(
                    fmt_currency(expected_annual))
            )

    elif verdict == "LOSER":
        parts.append(
            'The "{0}" {1} test is underperforming — {2} is down {3} '
            'with {4} confidence.'.format(
                test_name, test_type.lower(), rev_label,
                fmt_lift(uplift), fmt_confidence(confidence),
            )
        )
        if expected_annual:
            parts.append(
                "This variant would cost approximately {0}/year if rolled out. "
                "Recommend ending the test.".format(fmt_currency(abs(expected_annual)))
            )

    elif verdict == "FLAT":
        parts.append(
            'The "{0}" {1} test shows no meaningful difference — {2} '
            'lift is {3} after {4} days.'.format(
                test_name, test_type.lower(), rev_label,
                fmt_lift(uplift), days,
            )
        )
        parts.append("Recommend ending and testing a different lever.")

    elif verdict == "KEEP RUNNING":
        parts.append(
            'The "{0}" {1} test shows {2} lift at {3} confidence '
            'after {4} days.'.format(
                test_name, test_type.lower(), fmt_lift(uplift),
                fmt_confidence(confidence), days,
            )
        )
        parts.append("Not enough data for a confident call yet. Recommend letting it run.")

    else:  # TOO EARLY
        parts.append(
            'The "{0}" {1} test is too early to evaluate — '
            'insufficient data after {2} days.'.format(
                test_name, test_type.lower(), days,
            )
        )
        parts.append("Recommend checking back when minimum thresholds are met.")

    return " ".join(parts)


def build_recommendation(verdict, segment_results, overall_uplift):
    """Build a clear recommendation with reasoning."""
    has_contradictions = any(
        s.get("contradiction") for s in segment_results
    )

    if verdict == "WINNER":
        if has_contradictions:
            losers = [s for s in segment_results if s["verdict"] == "LOSER"]
            if losers:
                loser_names = ", ".join(s["name"] for s in losers[:2])
                return (
                    "ROLL OUT WITH CAUTION",
                    "Overall winner, but {0} underperforming. Consider a segment-specific "
                    "rollout or investigate the contradiction before full rollout.".format(loser_names)
                )
        return (
            "ROLL OUT",
            "Strong signal across the board. Roll out to all traffic."
        )

    if verdict == "LOSER":
        return (
            "END TEST",
            "The variant is hurting performance. End the test and revert to control."
        )

    if verdict == "FLAT":
        return (
            "END TEST — TRY SOMETHING DIFFERENT",
            "No meaningful impact. End the test and explore a different lever."
        )

    if verdict == "KEEP RUNNING":
        return (
            "KEEP RUNNING",
            "Promising signals but not conclusive. Let the test accumulate more data."
        )

    return (
        "WAIT",
        "Insufficient data to make any recommendation. Let the test run longer."
    )


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

    # ── Select test ──────────────────────────────────────────────
    args = []
    skip_next = False
    for arg in sys.argv[1:]:
        if skip_next:
            skip_next = False
            continue
        if arg == "--slack":
            skip_next = True
            continue
        args.append(arg)

    test_id = args[0] if args else None
    if not test_id:
        print("Fetching active experiments...")
        experiments = api.get_active_experiments()
        if not experiments:
            print("No active experiments found.")
            sys.exit(0)

        print("\nFound {0} active experiment(s):\n".format(len(experiments)))
        for i, exp in enumerate(experiments, 1):
            name = exp.get("name", "Unnamed")
            exp_id = exp.get("id", "?")
            d = runtime_days(exp.get("startedAtTs") or exp.get("startedAt"))
            print("  {0}. {1}  (ID: {2}, running {3} days)".format(i, name, exp_id, d))

        print()
        try:
            choice = input("Pick a test number (or paste an ID): ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nCancelled.")
            sys.exit(0)

        if choice.isdigit() and 1 <= int(choice) <= len(experiments):
            test_id = experiments[int(choice) - 1]["id"]
        else:
            test_id = choice

    if not test_id:
        print("ERROR: No test selected.")
        sys.exit(1)

    # ── Fetch all data ───────────────────────────────────────────
    print("\nFetching test details...")
    experiment = api.get_experience_detail(test_id)
    if not experiment or "id" not in experiment:
        print("ERROR: Could not find test with ID '{0}'.".format(test_id))
        sys.exit(1)

    test_name = experiment.get("name", "Unnamed Test")
    test_type = detect_test_type(experiment)
    variations = experiment.get("variations", [])
    control = find_control(variations)
    variant_list = find_variants(variations)

    if not control or not variant_list:
        print("ERROR: Could not identify control and variant.")
        sys.exit(1)

    started_ts = experiment.get("startedAtTs") or experiment.get("startedAt")
    days = runtime_days(started_ts)
    days_display = runtime_display(started_ts)

    print("Fetching analytics...")
    analytics = api.get_overview_analytics(test_id)
    metrics = analytics.get("metrics", [])
    if not metrics:
        print("ERROR: No analytics data.")
        sys.exit(1)

    total_visitors = get_total_visitors(metrics)
    total_orders = get_total_orders(metrics)
    cogs = has_cogs_data(metrics)
    rev_metric = primary_revenue_metric(metrics)
    rev_label = METRIC_LABELS.get(rev_metric, rev_metric)

    # Best variant
    best = pick_best_variant(variant_list, metrics, rev_metric)
    if not best:
        best = variant_list[0]
    best_id = best["id"]
    best_name = get_variation_name(variations, best_id)
    control_id = control["id"]
    control_name = get_variation_name(variations, control_id)

    # Key metrics
    uplift = get_metric_uplift(metrics, rev_metric, best_id)
    confidence = get_metric_confidence(metrics, rev_metric, best_id)
    ci_low, ci_high = get_metric_ci(metrics, rev_metric, best_id)
    control_rpv = get_metric_value(metrics, rev_metric, control_id)
    cr_uplift = get_metric_uplift(metrics, "conversion_rate", best_id)
    cr_conf = get_metric_confidence(metrics, "conversion_rate", best_id)

    # Verdict
    verdict = compute_verdict(confidence, uplift, days, total_orders)

    # Financial projections
    avg_daily_vis = daily_visitors(total_visitors, days) if days > 0 else 0
    annual_visitors = avg_daily_vis * 365
    annual_baseline = annual_visitors * (control_rpv or 0)
    expected_annual = annual_baseline * (uplift or 0)
    expected_monthly = expected_annual / 12

    conservative_annual = annual_baseline * ci_low if ci_low and ci_low > 0 else 0.0
    optimistic_annual = annual_baseline * ci_high if ci_high else None
    daily_cost = expected_annual / 365 if expected_annual else 0

    # ── Segment analysis ──────────────────────────────────────────
    segment_results = []
    for seg_type, seg_label in SEGMENT_TYPES:
        print("Fetching {0} segments...".format(seg_label))
        try:
            seg_data = api.get_segment_analytics(test_id, seg_type)
            seg_metrics = seg_data.get("metrics", [])
            if not seg_metrics:
                continue
            grouped = group_metrics_by_segment(seg_metrics)
            for seg_name, seg_m in grouped.items():
                seg_uplift = get_metric_uplift(seg_m, rev_metric, best_id)
                seg_conf = get_metric_confidence(seg_m, rev_metric, best_id)
                v = segment_verdict(seg_conf, seg_uplift, days)

                contradiction = False
                if uplift is not None and seg_uplift is not None:
                    if uplift > NEUTRAL_LIFT_THRESHOLD and seg_uplift < -NEUTRAL_LIFT_THRESHOLD:
                        contradiction = True
                    elif uplift < -NEUTRAL_LIFT_THRESHOLD and seg_uplift > NEUTRAL_LIFT_THRESHOLD:
                        contradiction = True

                segment_results.append({
                    "name": seg_name,
                    "type": seg_label,
                    "verdict": v,
                    "uplift": seg_uplift,
                    "confidence": seg_conf,
                    "contradiction": contradiction,
                })
        except Exception as e:
            print("  Warning: Could not fetch {0}: {1}".format(seg_label, e))

    # Executive summary
    exec_summary = build_executive_summary(
        test_name, test_type, verdict, rev_label,
        uplift, confidence, expected_annual, days,
    )

    # Recommendation
    rec_action, rec_reason = build_recommendation(verdict, segment_results, uplift)

    # Next steps
    next_steps = []
    if verdict == "WINNER":
        next_steps.append("Implement the winning variant across all traffic.")
        if any(s["contradiction"] for s in segment_results):
            next_steps.append("Investigate segment contradictions before full rollout.")
        next_steps.append("Plan a follow-up test to optimize further.")
    elif verdict == "LOSER":
        next_steps.append("Revert to control immediately.")
        next_steps.append("Document learnings for the team.")
        next_steps.append("Plan an alternative test with a different approach.")
    elif verdict == "FLAT":
        next_steps.append("End the test — no action needed on the variant.")
        next_steps.append("Explore a different lever (pricing, shipping, offers, content).")
    else:
        next_steps.append("Let the test continue running.")
        next_steps.append("Check back in a few days for updated results.")

    # ── Output ────────────────────────────────────────────────────
    if not slack_url:
        print("\n" + "=" * 60)
        print("  ROLLOUT BRIEF")
        print("  Generated: {0}".format(datetime.now().strftime("%Y-%m-%d %H:%M")))
        print("=" * 60)

        # Executive Summary
        print("\n--- EXECUTIVE SUMMARY ---")
        words = exec_summary.split()
        line = "  "
        for word in words:
            if len(line) + len(word) + 1 > 58:
                print(line)
                line = "  " + word
            else:
                line += (" " if len(line) > 2 else "") + word
        if line.strip():
            print(line)
        print()

        # Test Details
        print("--- TEST DETAILS ---")
        print("  Name:     {0}".format(test_name))
        print("  Type:     {0}".format(test_type))
        print("  Runtime:  {0}".format(days_display))
        print("  Visitors: {0}".format(fmt_number(total_visitors)))
        print("  Orders:   {0}".format(fmt_number(total_orders)))
        print("  Variant:  {0}".format(best_name))
        print("  Control:  {0}".format(control_name))
        print()

        # Results
        print("--- RESULTS ---")
        print("  VERDICT: {0}".format(verdict))
        print("  {0}: {1} ({2} confidence)".format(
            rev_label, fmt_lift(uplift), fmt_confidence(confidence)))
        if cr_uplift is not None:
            print("  Conversion Rate: {0} ({1} confidence)".format(
                fmt_lift(cr_uplift), fmt_confidence(cr_conf)))
        if ci_low is not None and ci_high is not None:
            print("  CI Range: {0} to {1}".format(fmt_lift(ci_low), fmt_lift(ci_high)))
        print()

        # Financial Impact
        if expected_annual != 0:
            print("--- FINANCIAL IMPACT ---")
            print("  Expected annual:      {0}".format(fmt_currency(expected_annual)))
            print("  Expected monthly:     {0}".format(fmt_currency(expected_monthly)))
            if conservative_annual:
                print("  Conservative annual:  {0}".format(fmt_currency(conservative_annual)))
            if optimistic_annual:
                print("  Optimistic annual:    {0}".format(fmt_currency(optimistic_annual)))
            if verdict == "WINNER" and daily_cost > 0:
                print("  Daily cost of waiting: {0}".format(fmt_currency(daily_cost)))
            print()

        # Segment Analysis
        if segment_results:
            print("--- SEGMENT ANALYSIS ---")
            for s in segment_results:
                flag = " ***" if s["contradiction"] else ""
                print("  {0:<16} ({1:<14}) {2:<12} {3:>7} ({4}){5}".format(
                    s["name"][:16], s["type"][:14], s["verdict"],
                    fmt_lift(s["uplift"]), fmt_confidence(s["confidence"]),
                    flag,
                ))
            if any(s["contradiction"] for s in segment_results):
                print()
                print("  *** = contradicts overall result")
            print()

        # Recommendation
        print("--- RECOMMENDATION ---")
        print("  {0}".format(rec_action))
        words = rec_reason.split()
        line = "  "
        for word in words:
            if len(line) + len(word) + 1 > 58:
                print(line)
                line = "  " + word
            else:
                line += (" " if len(line) > 2 else "") + word
        if line.strip():
            print(line)
        print()

        # Next Steps
        print("--- NEXT STEPS ---")
        for i, step in enumerate(next_steps, 1):
            print("  {0}. {1}".format(i, step))
        print()
        print("=" * 60)

    else:
        # ── Slack output ──────────────────────────────────────
        blocks = []

        emoji = verdict_emoji(verdict)
        blocks.append(header_block("{0} Rollout Brief".format(emoji)))

        # Executive summary
        blocks.append(section_block("*Executive Summary*\n{0}".format(exec_summary)))

        blocks.append(divider_block())

        # Test details + results
        blocks.append(fields_block([
            "*Test:* {0}".format(test_name),
            "*Type:* {0}".format(test_type),
            "*Runtime:* {0}".format(days_display),
            "*Orders:* {0}".format(fmt_number(total_orders)),
        ]))

        blocks.append(section_block(
            "*Results*\n"
            "Verdict: *{0}*\n"
            "{1}: {2} ({3} confidence)".format(
                verdict, rev_label, fmt_lift(uplift), fmt_confidence(confidence),
            )
        ))

        # Financial
        if expected_annual != 0:
            fin_text = "*Financial Impact*\nExpected: {0}/yr ({1}/mo)".format(
                fmt_currency(expected_annual), fmt_currency(expected_monthly))
            if verdict == "WINNER" and daily_cost > 0:
                fin_text += "\nDaily cost of waiting: {0}".format(fmt_currency(daily_cost))
            blocks.append(section_block(fin_text))

        blocks.append(divider_block())

        # Segments
        if segment_results:
            seg_lines = []
            for s in segment_results:
                flag = " :warning:" if s["contradiction"] else ""
                seg_lines.append("*{0}* ({1}): {2} ({3}){4}".format(
                    s["name"], s["type"], fmt_lift(s["uplift"]),
                    fmt_confidence(s["confidence"]), flag,
                ))
            blocks.append(section_block(
                "*Segment Analysis*\n" + "\n".join(seg_lines)))

        # Recommendation
        blocks.append(section_block(
            "*Recommendation: {0}*\n{1}".format(rec_action, rec_reason)))

        # Next steps
        blocks.append(section_block(
            "*Next Steps*\n" +
            "\n".join("- {0}".format(s) for s in next_steps)
        ))

        blocks.append(context_block("Powered by Intelligems Analytics"))

        fallback = "Rollout Brief: {0} — {1}".format(verdict, test_name)
        success = send_to_slack(slack_url, blocks, text=fallback)
        if success:
            print("Sent to Slack ✓")
        else:
            print("Failed to send to Slack.")


if __name__ == "__main__":
    main()
