"""
Intelligems Analytics — Funnel Diagnosis

Stage-by-stage funnel comparison for any A/B test.
Find exactly where the variant diverges from control.

Usage:
    python3 funnel.py              # Lists active tests, prompts to pick one
    python3 funnel.py <test_id>    # Analyzes a specific test
    python3 funnel.py <test_id> --slack <webhook_url>   # Send results to Slack
"""

import sys
import os
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
    fmt_number,
    detect_test_type,
)
from ig_config import FUNNEL_STAGES, METRIC_LABELS, MIN_CONFIDENCE


# ── Helpers ──────────────────────────────────────────────────────────────


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


def analyze_funnel(metrics, control_id, variant_id):
    """Analyze each funnel stage for control vs variant.

    Returns a list of dicts, one per stage.
    """
    stages = []
    for metric_name, label in FUNNEL_STAGES:
        control_val = get_metric_value(metrics, metric_name, control_id)
        variant_val = get_metric_value(metrics, metric_name, variant_id)
        uplift = get_metric_uplift(metrics, metric_name, variant_id)
        confidence = get_metric_confidence(metrics, metric_name, variant_id)

        has_data = control_val is not None or variant_val is not None

        stages.append({
            "metric": metric_name,
            "label": label,
            "control": control_val,
            "variant": variant_val,
            "uplift": uplift,
            "confidence": confidence,
            "has_data": has_data,
        })

    return stages


def find_biggest_gain(stages):
    """Find the stage with the largest positive uplift."""
    best = None
    for s in stages:
        if s["uplift"] is not None and s["uplift"] > 0:
            if best is None or s["uplift"] > best["uplift"]:
                best = s
    return best


def find_biggest_drop(stages):
    """Find the stage with the largest negative uplift."""
    worst = None
    for s in stages:
        if s["uplift"] is not None and s["uplift"] < 0:
            if worst is None or s["uplift"] < worst["uplift"]:
                worst = s
    return worst


def find_breakpoint(stages):
    """Find where the funnel behavior changes direction.

    A breakpoint is where uplift flips from positive to negative (or vice versa).
    Returns the stage where the flip happens.
    """
    prev_direction = None
    for s in stages:
        if s["uplift"] is None:
            continue
        direction = "up" if s["uplift"] > 0.005 else ("down" if s["uplift"] < -0.005 else "flat")
        if prev_direction is not None and direction != prev_direction and direction != "flat" and prev_direction != "flat":
            return s
        if direction != "flat":
            prev_direction = direction
    return None


def build_diagnosis(stages, biggest_gain, biggest_drop, breakpoint, test_type):
    """Build a plain-English diagnosis based on funnel findings."""
    parts = []

    if biggest_gain and biggest_drop:
        parts.append(
            "The variant improves {0} ({1}) but hurts {2} ({3}).".format(
                biggest_gain["label"], fmt_lift(biggest_gain["uplift"]),
                biggest_drop["label"], fmt_lift(biggest_drop["uplift"]),
            )
        )
    elif biggest_gain and not biggest_drop:
        parts.append(
            "The variant lifts {0} by {1} with no negative stages — clean signal across the funnel.".format(
                biggest_gain["label"], fmt_lift(biggest_gain["uplift"]),
            )
        )
    elif biggest_drop and not biggest_gain:
        parts.append(
            "The variant hurts {0} by {1} with no positive stages — the change is making things worse.".format(
                biggest_drop["label"], fmt_lift(biggest_drop["uplift"]),
            )
        )
    else:
        parts.append("No meaningful differences across funnel stages — the variant isn't moving behavior.")

    if breakpoint:
        parts.append(
            "The breakpoint is at {0}: behavior diverges here.".format(breakpoint["label"])
        )

    # Stage-specific suggestions
    if biggest_drop:
        drop_label = biggest_drop["label"]
        if "cart" in drop_label.lower():
            parts.append("Consider testing product page changes to improve add-to-cart conversion.")
        elif "checkout" in drop_label.lower():
            parts.append("Checkout is the bottleneck. Test checkout flow simplification or trust signals.")
        elif "contact" in drop_label.lower() or "address" in drop_label.lower():
            parts.append("Form friction is the issue. Test reducing required fields or adding progress indicators.")
        elif "purchase" in drop_label.lower():
            parts.append("The final purchase step is weak. Test payment options, shipping clarity, or urgency messaging.")

    return " ".join(parts)


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
            print("To analyze an ended test, pass its ID: python3 funnel.py <test_id>")
            sys.exit(0)

        print("\nFound {0} active experiment(s):\n".format(len(experiments)))
        for i, exp in enumerate(experiments, 1):
            name = exp.get("name", "Unnamed")
            exp_id = exp.get("id", "?")
            days = runtime_days(exp.get("startedAtTs") or exp.get("startedAt"))
            print("  {0}. {1}  (ID: {2}, running {3} days)".format(i, name, exp_id, days))

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

    if not control:
        print("ERROR: No control variation found.")
        sys.exit(1)
    if not variant_list:
        print("ERROR: No non-control variations found.")
        sys.exit(1)

    started_ts = experiment.get("startedAtTs") or experiment.get("startedAt")
    days = runtime_days(started_ts)
    days_display = runtime_display(started_ts)

    print("Fetching analytics...")
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

    # ── Pick best variant ─────────────────────────────────────────
    best = pick_best_variant(variant_list, metrics, rev_metric)
    if not best:
        best = variant_list[0]

    best_id = best["id"]
    best_name = get_variation_name(variations, best_id)
    control_id = control["id"]
    control_name = get_variation_name(variations, control_id)

    # ── Funnel analysis ───────────────────────────────────────────
    stages = analyze_funnel(metrics, control_id, best_id)
    active_stages = [s for s in stages if s["has_data"]]

    biggest_gain = find_biggest_gain(active_stages)
    biggest_drop = find_biggest_drop(active_stages)
    breakpoint = find_breakpoint(active_stages)
    diagnosis = build_diagnosis(active_stages, biggest_gain, biggest_drop, breakpoint, test_type)

    # ── RPV / GPV summary ─────────────────────────────────────────
    rev_uplift = get_metric_uplift(metrics, rev_metric, best_id)
    rev_conf = get_metric_confidence(metrics, rev_metric, best_id)

    # ── Output ────────────────────────────────────────────────────
    if not slack_url:
        # ── Terminal output ───────────────────────────────────
        print("\n" + "=" * 60)
        print("  FUNNEL DIAGNOSIS")
        print("=" * 60)
        print("  Test: {0}".format(test_name))
        print("  Type: {0} | Runtime: {1}".format(test_type, days_display))
        print("  Visitors: {0} | Orders: {1}".format(
            fmt_number(total_visitors), fmt_number(total_orders)))
        if len(variant_list) > 1:
            print("  Best variant: {0}".format(best_name))
        else:
            print("  Variant: {0}".format(best_name))
        print("  {0}: {1} ({2} confidence)".format(
            rev_label, fmt_lift(rev_uplift), fmt_confidence(rev_conf)))
        print()

        # Stage table
        print("-" * 60)
        print("  {0:<20} {1:>10} {2:>10} {3:>8} {4:>8}".format(
            "Stage", "Control", "Variant", "Lift", "Conf"))
        print("-" * 60)

        for s in stages:
            if not s["has_data"]:
                print("  {0:<20} {1:>10}".format(s["label"], "No data"))
                continue
            ctrl_str = fmt_pct(s["control"]) if s["control"] is not None else "—"
            var_str = fmt_pct(s["variant"]) if s["variant"] is not None else "—"
            lift_str = fmt_lift(s["uplift"])
            conf_str = fmt_confidence(s["confidence"])
            print("  {0:<20} {1:>10} {2:>10} {3:>8} {4:>8}".format(
                s["label"], ctrl_str, var_str, lift_str, conf_str))

        print()

        # Key findings
        print("-" * 60)
        print("  KEY FINDINGS")
        print("-" * 60)
        if biggest_gain:
            print("  Biggest gain:  {0} ({1})".format(
                biggest_gain["label"], fmt_lift(biggest_gain["uplift"])))
        else:
            print("  Biggest gain:  None — no positive stages")
        if biggest_drop:
            print("  Biggest drop:  {0} ({1})".format(
                biggest_drop["label"], fmt_lift(biggest_drop["uplift"])))
        else:
            print("  Biggest drop:  None — no negative stages")
        if breakpoint:
            print("  Breakpoint:    {0} — behavior diverges here".format(
                breakpoint["label"]))
        else:
            print("  Breakpoint:    None — consistent direction across funnel")
        print()

        # Diagnosis
        print("-" * 60)
        print("  DIAGNOSIS")
        print("-" * 60)
        words = diagnosis.split()
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
        print("=" * 60)

    else:
        # ── Slack output ──────────────────────────────────────
        blocks = []

        blocks.append(header_block("Funnel Diagnosis"))

        # Test info
        variant_label = "Best variant" if len(variant_list) > 1 else "Variant"
        blocks.append(section_block(
            "*{0}*\n"
            "Type: {1} | Runtime: {2}\n"
            "{3}: {4} vs {5}\n"
            "{6}: {7} ({8} confidence)".format(
                test_name, test_type, days_display,
                variant_label, best_name, control_name,
                rev_label, fmt_lift(rev_uplift), fmt_confidence(rev_conf),
            )
        ))

        blocks.append(divider_block())

        # Stage-by-stage
        stage_lines = []
        for s in stages:
            if not s["has_data"]:
                stage_lines.append("*{0}:* No data".format(s["label"]))
                continue
            ctrl_str = fmt_pct(s["control"]) if s["control"] is not None else "—"
            var_str = fmt_pct(s["variant"]) if s["variant"] is not None else "—"
            stage_lines.append(
                "*{0}:* {1} → {2} ({3}, {4} conf)".format(
                    s["label"], ctrl_str, var_str,
                    fmt_lift(s["uplift"]), fmt_confidence(s["confidence"]),
                )
            )
        blocks.append(section_block("*Funnel Stages*\n" + "\n".join(stage_lines)))

        blocks.append(divider_block())

        # Key findings
        findings = []
        if biggest_gain:
            findings.append("Biggest gain: *{0}* ({1})".format(
                biggest_gain["label"], fmt_lift(biggest_gain["uplift"])))
        if biggest_drop:
            findings.append("Biggest drop: *{0}* ({1})".format(
                biggest_drop["label"], fmt_lift(biggest_drop["uplift"])))
        if breakpoint:
            findings.append("Breakpoint: *{0}*".format(breakpoint["label"]))
        if findings:
            blocks.append(section_block("*Key Findings*\n" + "\n".join(findings)))

        # Diagnosis
        blocks.append(section_block("*Diagnosis*\n{0}".format(diagnosis)))

        blocks.append(context_block("Powered by Intelligems Analytics"))

        fallback = "Funnel Diagnosis: {0}".format(test_name)
        success = send_to_slack(slack_url, blocks, text=fallback)
        if success:
            print("Sent to Slack ✓")
        else:
            print("Failed to send to Slack.")


if __name__ == "__main__":
    main()
