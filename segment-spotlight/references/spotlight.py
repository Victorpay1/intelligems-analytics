"""
Intelligems Analytics — Segment Spotlight

Revenue-opportunity-ranked segment analysis for any A/B test.
Shows per-segment dollar values, verdicts, and rollout recommendations.

Usage:
    python3 spotlight.py              # Lists active tests, prompts to pick
    python3 spotlight.py <test_id>    # Analyzes a specific test
    python3 spotlight.py <test_id> --slack <webhook_url>   # Send to Slack
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv

from ig_client import IntelligemsAPI
from ig_slack import (
    parse_slack_args, send_to_slack,
    header_block, section_block, fields_block, divider_block, context_block,
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
    SEGMENT_TYPES, MIN_CONFIDENCE, NEUTRAL_LIFT_THRESHOLD,
    METRIC_LABELS, VERDICT_MIN_RUNTIME,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def segment_verdict(p2bb, uplift, days):
    """Determine verdict for a single segment."""
    if p2bb is None or uplift is None:
        return "LOW DATA"

    if p2bb >= MIN_CONFIDENCE and uplift > NEUTRAL_LIFT_THRESHOLD:
        return "WINNER"

    if (1 - p2bb) >= MIN_CONFIDENCE and uplift < -NEUTRAL_LIFT_THRESHOLD:
        return "LOSER"

    if days >= 21 and abs(uplift) <= NEUTRAL_LIFT_THRESHOLD:
        return "FLAT"

    return "KEEP RUNNING"


def pick_best_variant(variants, metrics, metric_name):
    """Find the variant with the highest uplift on the given metric."""
    best = None
    best_uplift = None
    for v in variants:
        uplift = get_metric_uplift(metrics, metric_name, v["id"])
        if uplift is not None and (best_uplift is None or uplift > best_uplift):
            best = v
            best_uplift = uplift
    return best


def compute_revenue_opportunity(seg_visitors, uplift, control_rpv, days):
    """Calculate annualized revenue opportunity for a segment.

    Revenue opportunity = (segment daily visitors) × (RPV lift in dollars) × 365
    """
    if uplift is None or control_rpv is None or days <= 0 or seg_visitors <= 0:
        return 0.0
    seg_daily = seg_visitors / days
    rpv_delta = control_rpv * uplift  # Absolute dollar lift per visitor
    return seg_daily * rpv_delta * 365


def rollout_recommendation(segments):
    """Generate rollout recommendation based on segment results."""
    winners = [s for s in segments if s["verdict"] == "WINNER"]
    losers = [s for s in segments if s["verdict"] == "LOSER"]
    low_data = [s for s in segments if s["verdict"] == "LOW DATA"]
    total = len(segments)

    if total == 0:
        return "HOLD", "No segment data available for analysis."

    if len(losers) == 0 and len(winners) >= total * 0.5:
        return "ROLL OUT", "No losing segments. Roll out to all traffic."

    if len(losers) > 0 and len(winners) > 0:
        winner_names = ", ".join(s["name"] for s in winners[:3])
        loser_names = ", ".join(s["name"] for s in losers[:3])
        return "SEGMENT-SPECIFIC", (
            "Consider rolling out to {0} only. "
            "{1} {2} underperforming — exclude or investigate.".format(
                winner_names,
                loser_names,
                "is" if len(losers) == 1 else "are",
            )
        )

    if len(losers) > 0 and len(winners) == 0:
        return "DON'T ROLL OUT", "No winning segments found. The variant is hurting performance."

    if len(low_data) > total * 0.5:
        return "HOLD", "Most segments have insufficient data. Let the test run longer."

    return "HOLD", "Mixed signals. Monitor for another few days before making a call."


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
        print("Set INTELLIGEMS_API_KEY in your .env file.")
        sys.exit(1)

    api = IntelligemsAPI(api_key)
    slack_url = parse_slack_args(sys.argv)

    # ── Select test ──────────────────────────────────────────────────
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
            print("To analyze an ended test, pass its ID: python3 spotlight.py <test_id>")
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

    # ── Fetch test data ──────────────────────────────────────────────
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
        print("ERROR: Could not identify control and variant variations.")
        sys.exit(1)

    started_ts = experiment.get("startedAtTs") or experiment.get("startedAt")
    days = runtime_days(started_ts)
    days_display = runtime_display(started_ts)

    # ── Overview analytics ────────────────────────────────────────
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

    # Pick best variant
    best = pick_best_variant(variant_list, metrics, rev_metric)
    if not best:
        best = variant_list[0]
    best_id = best["id"]
    best_name = get_variation_name(variations, best_id)
    control_id = control["id"]

    # Overall lift
    overall_uplift = get_metric_uplift(metrics, rev_metric, best_id)
    overall_conf = get_metric_confidence(metrics, rev_metric, best_id)
    control_rpv = get_metric_value(metrics, rev_metric, control_id)

    # ── Segment analysis ──────────────────────────────────────────
    all_segments = []

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
                seg_visitors = get_variation_visitors(seg_m, best_id)
                # Also count control visitors for total segment size
                ctrl_visitors = get_variation_visitors(seg_m, control_id)
                total_seg_visitors = seg_visitors + ctrl_visitors

                v = segment_verdict(seg_conf, seg_uplift, days)
                rev_opp = compute_revenue_opportunity(
                    total_seg_visitors, seg_uplift, control_rpv, days
                )

                # Check for contradiction with overall
                contradiction = False
                if overall_uplift is not None and seg_uplift is not None:
                    if overall_uplift > NEUTRAL_LIFT_THRESHOLD and seg_uplift < -NEUTRAL_LIFT_THRESHOLD:
                        contradiction = True
                    elif overall_uplift < -NEUTRAL_LIFT_THRESHOLD and seg_uplift > NEUTRAL_LIFT_THRESHOLD:
                        contradiction = True

                all_segments.append({
                    "name": seg_name,
                    "type": seg_label,
                    "verdict": v,
                    "uplift": seg_uplift,
                    "confidence": seg_conf,
                    "visitors": total_seg_visitors,
                    "revenue_opportunity": rev_opp,
                    "contradiction": contradiction,
                })
        except Exception as e:
            print("  Warning: Could not fetch {0} segments: {1}".format(seg_label, e))

    # Sort by absolute revenue opportunity (descending)
    all_segments.sort(key=lambda s: abs(s["revenue_opportunity"]), reverse=True)

    # Rollout recommendation
    rec_action, rec_reason = rollout_recommendation(all_segments)

    # ── Output ────────────────────────────────────────────────────
    if not slack_url:
        # ── Terminal output ───────────────────────────────────
        print("\n" + "=" * 70)
        print("  SEGMENT SPOTLIGHT")
        print("=" * 70)
        print("  Test: {0}".format(test_name))
        print("  Type: {0} | Runtime: {1}".format(test_type, days_display))
        print("  Visitors: {0} | Orders: {1}".format(
            fmt_number(total_visitors), fmt_number(total_orders)))
        print("  Overall {0}: {1} ({2} confidence)".format(
            rev_label, fmt_lift(overall_uplift), fmt_confidence(overall_conf)))
        print()

        # Segment table
        print("-" * 70)
        print("  {0:<16} {1:<14} {2:<12} {3:>7} {4:>7} {5:>12}".format(
            "Segment", "Type", "Verdict", "Lift", "Conf", "Annual $"))
        print("-" * 70)

        for s in all_segments:
            flag = " ***" if s["contradiction"] else ""
            print("  {0:<16} {1:<14} {2:<12} {3:>7} {4:>7} {5:>12}{6}".format(
                s["name"][:16],
                s["type"][:14],
                s["verdict"],
                fmt_lift(s["uplift"]),
                fmt_confidence(s["confidence"]),
                fmt_currency(s["revenue_opportunity"]),
                flag,
            ))

        print()

        # Contradictions
        contradictions = [s for s in all_segments if s["contradiction"]]
        if contradictions:
            print("-" * 70)
            print("  CONTRADICTIONS (*** above)")
            print("-" * 70)
            for s in contradictions:
                print("  {0} ({1}): Overall is {2} but this segment is {3} ({4})".format(
                    s["name"], s["type"],
                    "positive" if overall_uplift > 0 else "negative",
                    "negative" if s["uplift"] < 0 else "positive",
                    fmt_lift(s["uplift"]),
                ))
            print()

        # Recommendation
        print("-" * 70)
        print("  ROLLOUT RECOMMENDATION: {0}".format(rec_action))
        print("-" * 70)
        words = rec_reason.split()
        line = "  "
        for word in words:
            if len(line) + len(word) + 1 > 68:
                print(line)
                line = "  " + word
            else:
                line += (" " if len(line) > 2 else "") + word
        if line.strip():
            print(line)
        print()
        print("=" * 70)

    else:
        # ── Slack output ──────────────────────────────────────
        blocks = []

        blocks.append(header_block("Segment Spotlight"))

        blocks.append(section_block(
            "*{0}*\n"
            "Type: {1} | Runtime: {2}\n"
            "Overall {3}: {4} ({5} confidence)".format(
                test_name, test_type, days_display,
                rev_label, fmt_lift(overall_uplift), fmt_confidence(overall_conf),
            )
        ))

        blocks.append(divider_block())

        # Segment lines
        seg_lines = []
        for s in all_segments:
            flag = " :warning:" if s["contradiction"] else ""
            seg_lines.append(
                "*{0}* ({1}) — {2}: {3} ({4} conf) | {5}/yr{6}".format(
                    s["name"], s["type"], s["verdict"],
                    fmt_lift(s["uplift"]), fmt_confidence(s["confidence"]),
                    fmt_currency(s["revenue_opportunity"]), flag,
                )
            )
        blocks.append(section_block(
            "*Revenue-Ranked Segments*\n" + "\n".join(seg_lines)
        ))

        blocks.append(divider_block())

        # Recommendation
        blocks.append(section_block(
            "*Rollout Recommendation: {0}*\n{1}".format(rec_action, rec_reason)
        ))

        blocks.append(context_block("Powered by Intelligems Analytics"))

        fallback = "Segment Spotlight: {0}".format(test_name)
        success = send_to_slack(slack_url, blocks, text=fallback)
        if success:
            print("Sent to Slack ✓")
        else:
            print("Failed to send to Slack.")


if __name__ == "__main__":
    main()
