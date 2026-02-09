"""
Intelligems Analytics — Test Debrief

Post-mortem analysis for any A/B test outcome.
Extracts learnings from funnel data, segment patterns,
and customer behavior — then suggests specific next tests.

Usage:
    python3 debrief.py              # Lists active tests, prompts to pick
    python3 debrief.py <test_id>    # Debriefs a specific test
    python3 debrief.py <test_id> --slack <webhook_url>   # Send to Slack
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv

from ig_client import IntelligemsAPI
from ig_slack import (
    parse_slack_args, send_to_slack,
    header_block, section_block, divider_block, context_block,
    verdict_emoji,
)
from ig_metrics import (
    get_metric_value,
    get_metric_uplift,
    get_metric_confidence,
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
    FUNNEL_STAGES, SEGMENT_TYPES, MIN_CONFIDENCE,
    NEUTRAL_LIFT_THRESHOLD, VERDICT_MIN_RUNTIME,
    VERDICT_MIN_ORDERS, METRIC_LABELS, MIN_VISITORS,
)


# ── Verdict logic ────────────────────────────────────────────────────────


def compute_verdict(p2bb, uplift, days, total_orders):
    """Determine overall verdict."""
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


# ── Funnel analysis ──────────────────────────────────────────────────────


def analyze_funnel(metrics, control_id, variant_id):
    """Analyze each funnel stage."""
    stages = []
    for metric_name, label in FUNNEL_STAGES:
        uplift = get_metric_uplift(metrics, metric_name, variant_id)
        confidence = get_metric_confidence(metrics, metric_name, variant_id)
        control_val = get_metric_value(metrics, metric_name, control_id)
        variant_val = get_metric_value(metrics, metric_name, variant_id)

        if control_val is None and variant_val is None:
            continue

        stages.append({
            "label": label,
            "control": control_val,
            "variant": variant_val,
            "uplift": uplift,
            "confidence": confidence,
        })
    return stages


# ── Segment insights ─────────────────────────────────────────────────────


def analyze_segments(api, test_id, rev_metric, best_id, control_id, days):
    """Fetch and analyze all segment types. Returns list of segment results."""
    all_segments = []

    for seg_type, seg_label in SEGMENT_TYPES:
        try:
            seg_data = api.get_segment_analytics(test_id, seg_type)
            seg_metrics = seg_data.get("metrics", [])
            if not seg_metrics:
                continue

            grouped = group_metrics_by_segment(seg_metrics)
            for seg_name, seg_m in grouped.items():
                seg_uplift = get_metric_uplift(seg_m, rev_metric, best_id)
                seg_conf = get_metric_confidence(seg_m, rev_metric, best_id)
                seg_visitors = get_variation_visitors(seg_m, best_id)
                ctrl_visitors = get_variation_visitors(seg_m, control_id)

                all_segments.append({
                    "name": seg_name,
                    "type": seg_label,
                    "uplift": seg_uplift,
                    "confidence": seg_conf,
                    "visitors": seg_visitors + ctrl_visitors,
                })
        except Exception as e:
            print("  Warning: Could not fetch {0} segments: {1}".format(seg_label, e))

    return all_segments


def generate_insights(segments, overall_uplift):
    """Generate customer behavior insights from segment patterns."""
    insights = []
    if not segments:
        return insights

    # Find strongest and weakest segments
    with_data = [s for s in segments if s["uplift"] is not None]
    if not with_data:
        return insights

    strongest = max(with_data, key=lambda s: s["uplift"])
    weakest = min(with_data, key=lambda s: s["uplift"])

    # Insight 1: Strongest segment
    if strongest["uplift"] > NEUTRAL_LIFT_THRESHOLD:
        insights.append(
            "{0} ({1}) responded strongest at {2} lift.".format(
                strongest["name"], strongest["type"],
                fmt_lift(strongest["uplift"]),
            )
        )

    # Insight 2: Weakest segment (especially if it contradicts overall)
    if weakest["uplift"] is not None and overall_uplift is not None:
        if (overall_uplift > 0 and weakest["uplift"] < -NEUTRAL_LIFT_THRESHOLD):
            insights.append(
                "{0} ({1}) is the outlier — actually negative at {2} while overall is positive.".format(
                    weakest["name"], weakest["type"],
                    fmt_lift(weakest["uplift"]),
                )
            )
        elif weakest["uplift"] < -NEUTRAL_LIFT_THRESHOLD:
            insights.append(
                "{0} ({1}) is underperforming at {2}.".format(
                    weakest["name"], weakest["type"],
                    fmt_lift(weakest["uplift"]),
                )
            )

    # Insight 3: Device comparison
    devices = [s for s in with_data if s["type"] == "Device"]
    if len(devices) >= 2:
        devices.sort(key=lambda s: s["uplift"] or 0, reverse=True)
        best_dev = devices[0]
        worst_dev = devices[-1]
        if best_dev["uplift"] is not None and worst_dev["uplift"] is not None:
            diff = abs(best_dev["uplift"] - worst_dev["uplift"])
            if diff > 0.05:  # >5% difference is noteworthy
                insights.append(
                    "{0} outperforms {1} by {2} — consider device-specific optimization.".format(
                        best_dev["name"], worst_dev["name"],
                        fmt_lift(diff),
                    )
                )

    # Insight 4: New vs returning
    visitors = [s for s in with_data if s["type"] == "Visitor Type"]
    if len(visitors) >= 2:
        new = next((s for s in visitors if "new" in s["name"].lower()), None)
        returning = next((s for s in visitors if "return" in s["name"].lower()), None)
        if new and returning and new["uplift"] is not None and returning["uplift"] is not None:
            diff = abs(new["uplift"] - returning["uplift"])
            if diff > 0.03:
                if new["uplift"] > returning["uplift"]:
                    insights.append(
                        "New visitors drove more of the lift ({0}) vs returning ({1}).".format(
                            fmt_lift(new["uplift"]), fmt_lift(returning["uplift"]),
                        )
                    )
                else:
                    insights.append(
                        "Returning visitors responded more ({0}) vs new visitors ({1}).".format(
                            fmt_lift(returning["uplift"]), fmt_lift(new["uplift"]),
                        )
                    )

    # Insight 5: Traffic source patterns
    sources = [s for s in with_data if s["type"] == "Traffic Source"]
    if sources:
        positive_sources = [s for s in sources if s["uplift"] is not None and s["uplift"] > NEUTRAL_LIFT_THRESHOLD]
        negative_sources = [s for s in sources if s["uplift"] is not None and s["uplift"] < -NEUTRAL_LIFT_THRESHOLD]
        if positive_sources and negative_sources:
            pos_names = ", ".join(s["name"] for s in positive_sources[:2])
            neg_names = ", ".join(s["name"] for s in negative_sources[:2])
            insights.append(
                "Works for {0} traffic but not {1} — audience intent may differ.".format(
                    pos_names, neg_names,
                )
            )

    return insights


def suggest_next_tests(verdict, test_type, funnel_stages, insights, segments):
    """Generate specific next-test suggestions based on findings."""
    suggestions = []

    # Funnel-based suggestions
    if funnel_stages:
        drops = [s for s in funnel_stages if s["uplift"] is not None and s["uplift"] < -NEUTRAL_LIFT_THRESHOLD]
        gains = [s for s in funnel_stages if s["uplift"] is not None and s["uplift"] > NEUTRAL_LIFT_THRESHOLD]

        if drops:
            worst_stage = min(drops, key=lambda s: s["uplift"])
            suggestions.append(
                "Fix the {0} stage ({1}) — test changes specifically targeting this step.".format(
                    worst_stage["label"], fmt_lift(worst_stage["uplift"]),
                )
            )
        if gains:
            best_stage = max(gains, key=lambda s: s["uplift"])
            suggestions.append(
                "Double down on {0} ({1}) — this stage is working, push it further.".format(
                    best_stage["label"], fmt_lift(best_stage["uplift"]),
                )
            )

    # Segment-based suggestions
    contradictions = [s for s in segments
                      if s["uplift"] is not None and s["uplift"] < -NEUTRAL_LIFT_THRESHOLD]
    if contradictions:
        worst_seg = min(contradictions, key=lambda s: s["uplift"])
        suggestions.append(
            "Investigate why {0} ({1}) underperforms — consider a {0}-specific test.".format(
                worst_seg["name"], worst_seg["type"],
            )
        )

    # Test type-based suggestions
    type_suggestions = {
        "Pricing": "Test a different price point or pricing display format.",
        "Shipping": "Test shipping threshold messaging or delivery speed options.",
        "Offer": "Test a different discount structure or qualifying criteria.",
        "Content": "Test a completely different messaging angle or visual approach.",
    }
    if verdict in ("WINNER", "FLAT") and test_type in type_suggestions:
        suggestions.append(type_suggestions[test_type])

    if verdict == "LOSER":
        suggestions.append("Consider reversing the approach — test the opposite direction.")

    if not suggestions:
        suggestions.append("Run a broader discovery test to identify the next high-impact lever.")

    return suggestions


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
            print("To debrief an ended test, pass its ID: python3 debrief.py <test_id>")
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

    # ── Fetch data ───────────────────────────────────────────────
    print("\nFetching test details for {0}...".format(test_id))
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

    print("Fetching overview analytics...")
    analytics = api.get_overview_analytics(test_id)
    metrics = analytics.get("metrics", [])
    if not metrics:
        print("ERROR: No analytics data returned.")
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
    cr_uplift = get_metric_uplift(metrics, "conversion_rate", best_id)
    cr_conf = get_metric_confidence(metrics, "conversion_rate", best_id)

    # Verdict
    verdict = compute_verdict(confidence, uplift, days, total_orders)

    # Funnel analysis
    funnel_stages = analyze_funnel(metrics, control_id, best_id)

    # Segment analysis
    print("Fetching segment data...")
    segments = analyze_segments(api, test_id, rev_metric, best_id, control_id, days)

    # Insights
    insights = generate_insights(segments, uplift)

    # Next test suggestions
    suggestions = suggest_next_tests(verdict, test_type, funnel_stages, insights, segments)

    # ── Output ────────────────────────────────────────────────────
    if not slack_url:
        # ── Terminal output ───────────────────────────────────
        print("\n" + "=" * 60)
        print("  TEST DEBRIEF")
        print("=" * 60)

        # Section 1: What Happened
        print("\n--- WHAT HAPPENED ---")
        print("  Test: {0}".format(test_name))
        print("  Type: {0} | Runtime: {1}".format(test_type, days_display))
        print("  Visitors: {0} | Orders: {1}".format(
            fmt_number(total_visitors), fmt_number(total_orders)))
        print("  Variant: {0} vs Control: {1}".format(best_name, control_name))
        print()
        print("  VERDICT: {0}".format(verdict))
        print("  {0}: {1} ({2} confidence)".format(rev_label, fmt_lift(uplift), fmt_confidence(confidence)))
        if cr_uplift is not None:
            print("  Conversion Rate: {0} ({1} confidence)".format(
                fmt_lift(cr_uplift), fmt_confidence(cr_conf)))
        print()

        # Section 2: Funnel Analysis
        if funnel_stages:
            print("--- WHY IT HAPPENED: FUNNEL ---")
            for s in funnel_stages:
                ctrl_str = fmt_pct(s["control"]) if s["control"] else "—"
                var_str = fmt_pct(s["variant"]) if s["variant"] else "—"
                print("  {0:<22} {1:>6} → {2:>6} ({3}, {4} conf)".format(
                    s["label"], ctrl_str, var_str,
                    fmt_lift(s["uplift"]), fmt_confidence(s["confidence"]),
                ))
            print()

        # Section 3: Segment Patterns
        if segments:
            print("--- WHY IT HAPPENED: SEGMENTS ---")
            for s in segments:
                print("  {0:<16} ({1:<14}) {2:>7} ({3})".format(
                    s["name"][:16], s["type"][:14],
                    fmt_lift(s["uplift"]), fmt_confidence(s["confidence"]),
                ))
            print()

        # Section 4: Insights
        if insights:
            print("--- CUSTOMER BEHAVIOR INSIGHTS ---")
            for i, insight in enumerate(insights, 1):
                print("  {0}. {1}".format(i, insight))
            print()

        # Section 5: Next Tests
        print("--- WHAT TO TEST NEXT ---")
        for i, suggestion in enumerate(suggestions, 1):
            print("  {0}. {1}".format(i, suggestion))
        print()
        print("=" * 60)

    else:
        # ── Slack output ──────────────────────────────────────
        blocks = []

        emoji = verdict_emoji(verdict)
        blocks.append(header_block("{0} Test Debrief: {1}".format(emoji, verdict)))

        # What happened
        blocks.append(section_block(
            "*{0}*\n"
            "Type: {1} | Runtime: {2}\n"
            "Variant: {3} vs Control: {4}\n"
            "{5}: {6} ({7} confidence)".format(
                test_name, test_type, days_display,
                best_name, control_name,
                rev_label, fmt_lift(uplift), fmt_confidence(confidence),
            )
        ))

        blocks.append(divider_block())

        # Funnel
        if funnel_stages:
            funnel_lines = []
            for s in funnel_stages:
                ctrl_str = fmt_pct(s["control"]) if s["control"] else "—"
                var_str = fmt_pct(s["variant"]) if s["variant"] else "—"
                funnel_lines.append("*{0}:* {1} → {2} ({3})".format(
                    s["label"], ctrl_str, var_str, fmt_lift(s["uplift"]),
                ))
            blocks.append(section_block("*Funnel Analysis*\n" + "\n".join(funnel_lines)))

        # Insights
        if insights:
            blocks.append(section_block(
                "*Customer Behavior Insights*\n" +
                "\n".join("- {0}".format(ins) for ins in insights)
            ))

        # Next tests
        blocks.append(section_block(
            "*What to Test Next*\n" +
            "\n".join("- {0}".format(s) for s in suggestions)
        ))

        blocks.append(context_block("Powered by Intelligems Analytics"))

        fallback = "Test Debrief: {0} — {1}".format(verdict, test_name)
        success = send_to_slack(slack_url, blocks, text=fallback)
        if success:
            print("Sent to Slack ✓")
        else:
            print("Failed to send to Slack.")


if __name__ == "__main__":
    main()
