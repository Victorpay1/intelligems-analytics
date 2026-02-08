#!/usr/bin/env python3
"""
Intelligems Analytics — Test Verdict

Analyzes a single A/B test and delivers a plain-English verdict:
WINNER / LOSER / FLAT / KEEP RUNNING / TOO EARLY

Usage:
    python3 verdict.py              # Lists active tests, prompts to pick one
    python3 verdict.py <test_id>    # Analyzes a specific test (active or ended)
    python3 verdict.py <test_id> --slack <webhook_url>   # Send results to Slack
"""

import sys
import os
from datetime import datetime
from dotenv import load_dotenv

from ig_client import IntelligemsAPI
from ig_slack import parse_slack_args, send_to_slack, header_block, section_block, fields_block, divider_block, context_block, verdict_emoji
from ig_metrics import (
    get_metric_value,
    get_metric_uplift,
    get_metric_confidence,
    get_metric_ci,
    get_total_visitors,
    get_total_orders,
    has_cogs_data,
    primary_revenue_metric,
    get_variation_visitors,
    get_variation_orders,
    group_metrics_by_segment,
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
    daily_orders,
    days_to_target_orders,
)
from ig_config import (
    MIN_CONFIDENCE,
    NEUTRAL_LIFT_THRESHOLD,
    MIN_VISITORS,
    VERDICT_MIN_RUNTIME,
    VERDICT_MIN_ORDERS,
    METRIC_LABELS,
)


# ── Helpers ──────────────────────────────────────────────────────────────


def compute_runtime_days(experiment: dict) -> int:
    """Calculate runtime days, handling both active and ended tests."""
    ended_at = experiment.get("endedAtTs") or experiment.get("endedAt")
    started_at = experiment.get("startedAtTs") or experiment.get("startedAt")
    if not started_at:
        return 0
    start = datetime.fromtimestamp(started_at / 1000)
    if ended_at:
        end = datetime.fromtimestamp(ended_at / 1000)
    else:
        end = datetime.now()
    return max((end - start).days, 0)


def compute_runtime_display(days: int) -> str:
    """Human-readable runtime."""
    if days == 0:
        return "< 1 day"
    if days == 1:
        return "1 day"
    return f"{days} days"


def variation_verdict(p2bb: float, uplift: float, days: int) -> str:
    """Determine verdict for a single variation."""
    if p2bb is None or uplift is None:
        return "TOO EARLY"

    if p2bb >= MIN_CONFIDENCE and uplift > NEUTRAL_LIFT_THRESHOLD:
        return "WINNER"

    if (1 - p2bb) >= MIN_CONFIDENCE and uplift < -NEUTRAL_LIFT_THRESHOLD:
        return "LOSER"

    if days >= 21 and abs(uplift) <= NEUTRAL_LIFT_THRESHOLD:
        return "FLAT"

    return "KEEP RUNNING"


def suggest_next_test(test_type: str, verdict: str) -> str:
    """Suggest what to test next based on type and outcome."""
    suggestions = {
        ("Pricing", "WINNER"): (
            "Try testing a slightly higher price point to find the ceiling. "
            "Also consider testing price anchoring or bundle pricing."
        ),
        ("Pricing", "LOSER"): (
            "The price change hurt performance. Try a smaller increment, "
            "or test perceived-value tactics (strikethrough pricing, limited-time framing)."
        ),
        ("Pricing", "FLAT"): (
            "Price didn't matter here. Test something that changes perceived value instead: "
            "urgency messaging, social proof, or bundle offers."
        ),
        ("Shipping", "WINNER"): (
            "Great — shipping changes moved the needle. Try testing different free-shipping "
            "thresholds to optimize the balance between conversion lift and margin."
        ),
        ("Shipping", "LOSER"): (
            "This shipping approach hurt. Consider testing free shipping with a "
            "minimum order threshold, or offering shipping as a value-add at checkout."
        ),
        ("Shipping", "FLAT"): (
            "Shipping wasn't the lever. Test something else — pricing, offer messaging, "
            "or checkout flow changes."
        ),
        ("Offer", "WINNER"): (
            "The offer works. Now optimize it: test the discount level, "
            "the qualifying threshold, or the way it's communicated."
        ),
        ("Offer", "LOSER"): (
            "This offer didn't land. Try a different discount structure "
            "(percentage vs. fixed), or test urgency-based offers."
        ),
        ("Offer", "FLAT"): (
            "The offer didn't move behavior. Test something more visible — "
            "homepage messaging, product page layout, or the checkout experience."
        ),
        ("Content", "WINNER"): (
            "This content change is working. Double down — test further variations "
            "of the winning approach on other pages."
        ),
        ("Content", "LOSER"): (
            "This content didn't resonate. Try a completely different angle "
            "or test on a different page in the funnel."
        ),
        ("Content", "FLAT"): (
            "The messaging change isn't moving the needle. Try a bolder change — "
            "layout, imagery, or a fundamentally different value proposition."
        ),
    }

    if verdict in ("TOO EARLY", "KEEP RUNNING"):
        return "Just wait. Let the test accumulate more data before planning the next move."

    return suggestions.get(
        (test_type, verdict),
        "Consider testing a different lever entirely — pricing, shipping, offers, or content."
    )


# ── Main ─────────────────────────────────────────────────────────────────


def main():
    # Load environment
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

    # Filter out --slack and its value from argv for test ID detection
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
            print("To analyze an ended test, pass its ID: python3 verdict.py <test_id>")
            sys.exit(0)

        print(f"\nFound {len(experiments)} active experiment(s):\n")
        for i, exp in enumerate(experiments, 1):
            name = exp.get("name", "Unnamed")
            exp_id = exp.get("id", "?")
            days = runtime_days(exp.get("startedAtTs") or exp.get("startedAt"))
            print(f"  {i}. {name}  (ID: {exp_id}, running {days} days)")

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

    print(f"\nFetching test details for {test_id}...")
    experiment = api.get_experience_detail(test_id)
    if not experiment or "id" not in experiment:
        print(f"ERROR: Could not find test with ID '{test_id}'.")
        print("Check the ID and try again.")
        sys.exit(1)

    test_name = experiment.get("name", "Unnamed Test")
    test_type = detect_test_type(experiment)
    variations = experiment.get("variations", [])
    control = find_control(variations)
    variants = find_variants(variations)

    if not control:
        print("ERROR: No control variation found in this test.")
        sys.exit(1)

    if not variants:
        print("ERROR: No non-control variations found in this test.")
        sys.exit(1)

    days = compute_runtime_days(experiment)
    days_display = compute_runtime_display(days)

    print("Fetching analytics...")
    analytics = api.get_overview_analytics(test_id)
    metrics = analytics.get("metrics", [])

    if not metrics:
        print("ERROR: No analytics data returned for this test.")
        print("The test may not have collected any data yet.")
        sys.exit(1)

    total_visitors = get_total_visitors(metrics)
    total_orders = get_total_orders(metrics)
    cogs = has_cogs_data(metrics)
    primary_metric = primary_revenue_metric(metrics)
    primary_label = METRIC_LABELS.get(primary_metric, primary_metric)

    # ── Maturity check ───────────────────────────────────────────────

    maturity_issues = []
    if days < VERDICT_MIN_RUNTIME:
        maturity_issues.append(
            f"Only {days_display} of runtime (minimum {VERDICT_MIN_RUNTIME} days)"
        )
    if total_orders < VERDICT_MIN_ORDERS:
        maturity_issues.append(
            f"Only {fmt_number(total_orders)} orders (minimum {VERDICT_MIN_ORDERS})"
        )
    if total_visitors < MIN_VISITORS:
        maturity_issues.append(
            f"Only {fmt_number(total_visitors)} visitors (minimum {MIN_VISITORS})"
        )

    is_too_early = len(maturity_issues) > 0

    # ── Analyze each variation ───────────────────────────────────────

    variation_results = []

    for variant in variants:
        vid = variant["id"]
        vname = get_variation_name(variations, vid)

        p2bb = get_metric_confidence(metrics, primary_metric, vid)
        uplift = get_metric_uplift(metrics, primary_metric, vid)
        ci_low, ci_high = get_metric_ci(metrics, primary_metric, vid)
        primary_value = get_metric_value(metrics, primary_metric, vid)
        control_value = get_metric_value(metrics, primary_metric, control["id"])

        # Revenue vs conversion comparison
        rpv_uplift = get_metric_uplift(metrics, "net_revenue_per_visitor", vid)
        cr_uplift = get_metric_uplift(metrics, "conversion_rate", vid)

        # Determine divergence
        divergence = None
        if rpv_uplift is not None and cr_uplift is not None:
            rpv_dir = "up" if rpv_uplift > 0.005 else ("down" if rpv_uplift < -0.005 else "flat")
            cr_dir = "up" if cr_uplift > 0.005 else ("down" if cr_uplift < -0.005 else "flat")

            if rpv_dir != cr_dir and rpv_dir != "flat" and cr_dir != "flat":
                if rpv_dir == "up" and cr_dir == "down":
                    divergence = (
                        "Revenue is UP but conversion is DOWN — fewer people are buying, "
                        "but those who do spend more. Worth monitoring."
                    )
                elif rpv_dir == "down" and cr_dir == "up":
                    divergence = (
                        "Conversion is UP but revenue is DOWN — more people are buying, "
                        "but they're spending less per order. Check if discounting is too aggressive."
                    )
                else:
                    divergence = (
                        f"Revenue per visitor is {rpv_dir} ({fmt_lift(rpv_uplift)}) "
                        f"while conversion rate is {cr_dir} ({fmt_lift(cr_uplift)}). "
                        "These signals don't fully align — investigate further."
                    )

        # GPV vs RPV comparison (when COGS data exists)
        profit_note = None
        if cogs:
            gpv_uplift = get_metric_uplift(metrics, "gross_profit_per_visitor", vid)
            rpv_uplift_check = get_metric_uplift(metrics, "net_revenue_per_visitor", vid)
            if gpv_uplift is not None and rpv_uplift_check is not None:
                gpv_dir = gpv_uplift > 0
                rpv_dir_bool = rpv_uplift_check > 0
                if gpv_dir != rpv_dir_bool:
                    profit_note = (
                        f"Revenue ({fmt_lift(rpv_uplift_check)}) and profit ({fmt_lift(gpv_uplift)}) "
                        "are moving in opposite directions. COGS are eating into the gains."
                    )
                else:
                    profit_note = (
                        f"Revenue ({fmt_lift(rpv_uplift_check)}) and profit ({fmt_lift(gpv_uplift)}) "
                        "are aligned. COGS aren't distorting the picture."
                    )

        # Verdict
        if is_too_early:
            v_verdict = "TOO EARLY"
        else:
            v_verdict = variation_verdict(p2bb, uplift, days)

        # Reasoning
        reasoning = build_reasoning(
            v_verdict, vname, primary_label, uplift, p2bb, days, total_orders
        )

        # Risk framing
        risk = build_risk(p2bb, ci_low, ci_high, primary_label, profit_note)

        variation_results.append({
            "id": vid,
            "name": vname,
            "verdict": v_verdict,
            "p2bb": p2bb,
            "uplift": uplift,
            "ci_low": ci_low,
            "ci_high": ci_high,
            "primary_value": primary_value,
            "control_value": control_value,
            "rpv_uplift": rpv_uplift,
            "cr_uplift": cr_uplift,
            "divergence": divergence,
            "profit_note": profit_note,
            "reasoning": reasoning,
            "risk": risk,
        })

    # ── Pick the best variation ──────────────────────────────────────

    # Sort: WINNER first, then by p2bb descending
    verdict_priority = {"WINNER": 0, "KEEP RUNNING": 1, "FLAT": 2, "LOSER": 3, "TOO EARLY": 4}
    variation_results.sort(
        key=lambda r: (verdict_priority.get(r["verdict"], 5), -(r["p2bb"] or 0))
    )
    best = variation_results[0]

    # ── Segment quick-check ──────────────────────────────────────────

    segment_results = []
    if not is_too_early:
        print("Checking segments (device type)...")
        try:
            seg_data = api.get_segment_analytics(test_id, "device_type")
            seg_metrics = seg_data.get("metrics", [])
            if seg_metrics:
                grouped = group_metrics_by_segment(seg_metrics)
                for seg_name, seg_m in grouped.items():
                    seg_p2bb = get_metric_confidence(seg_m, primary_metric, best["id"])
                    seg_uplift = get_metric_uplift(seg_m, primary_metric, best["id"])
                    seg_visitors = get_variation_visitors(seg_m, best["id"])

                    if seg_uplift is not None:
                        seg_verdict = variation_verdict(seg_p2bb, seg_uplift, days)
                    else:
                        seg_verdict = "LOW DATA"

                    # Flag contradictions with overall verdict
                    contradiction = False
                    if best["verdict"] == "WINNER" and seg_verdict == "LOSER":
                        contradiction = True
                    elif best["verdict"] == "LOSER" and seg_verdict == "WINNER":
                        contradiction = True

                    segment_results.append({
                        "segment": seg_name,
                        "verdict": seg_verdict,
                        "uplift": seg_uplift,
                        "p2bb": seg_p2bb,
                        "visitors": seg_visitors,
                        "contradiction": contradiction,
                    })
        except Exception as e:
            segment_results.append({
                "segment": "Error",
                "verdict": "N/A",
                "uplift": None,
                "p2bb": None,
                "visitors": 0,
                "contradiction": False,
                "error": str(e),
            })

    # ── Estimate time to readiness (for TOO EARLY / KEEP RUNNING) ───

    eta_note = ""
    if best["verdict"] in ("TOO EARLY", "KEEP RUNNING") and days > 0:
        d_orders = daily_orders(total_orders, days)
        if total_orders < VERDICT_MIN_ORDERS and d_orders > 0:
            eta = days_to_target_orders(total_orders, VERDICT_MIN_ORDERS, d_orders)
            if eta:
                eta_note = f"At the current rate (~{d_orders:.0f} orders/day), you'll hit {VERDICT_MIN_ORDERS} orders in ~{eta} day(s)."

    # ── What to test next ────────────────────────────────────────────

    next_test = suggest_next_test(test_type, best["verdict"])
    if eta_note:
        next_test = f"{eta_note}\n{next_test}"

    # ── Output ───────────────────────────────────────────────────────

    if not slack_url:
        # ── Terminal output ───────────────────────────────────────
        print("\n" + "=" * 60)
        print("=== TEST VERDICT ===")
        print("=" * 60)
        print(f"Test: {test_name}")
        print(f"Type: {test_type}")
        print(f"Runtime: {days_display} | Visitors: {fmt_number(total_visitors)} | Orders: {fmt_number(total_orders)}")
        if cogs:
            print(f"Primary Metric: {primary_label} (COGS data available)")
        else:
            print(f"Primary Metric: {primary_label}")
        print()

        # Maturity warnings
        if is_too_early:
            print("VERDICT: TOO EARLY")
            print()
            print("Maturity issues:")
            for issue in maturity_issues:
                print(f"  - {issue}")
            print()

        # Per-variation results
        for i, result in enumerate(variation_results):
            if len(variation_results) > 1:
                marker = " << BEST" if i == 0 else ""
                print(f"--- Variation: {result['name']}{marker} ---")
            else:
                print(f"--- Variation: {result['name']} ---")

            if not is_too_early:
                print(f"VERDICT: {result['verdict']}")

            print(f"{primary_label}: {fmt_lift(result['uplift'])}")
            print(f"Confidence: {fmt_confidence(result['p2bb'])}")

            if result['ci_low'] is not None and result['ci_high'] is not None:
                print(f"CI Range: {fmt_lift(result['ci_low'])} to {fmt_lift(result['ci_high'])}")

            if result['rpv_uplift'] is not None:
                print(f"RPV Lift: {fmt_lift(result['rpv_uplift'])}")
            if result['cr_uplift'] is not None:
                print(f"CR Lift: {fmt_lift(result['cr_uplift'])}")

            print()

        # Reasoning (for the best variation)
        print("--- Reasoning ---")
        print(best["reasoning"])
        print()

        # Risk assessment
        print("--- Risk Assessment ---")
        print(best["risk"])
        print()

        # Revenue vs conversion
        print("--- Revenue vs Conversion ---")
        if best["divergence"]:
            print(best["divergence"])
        else:
            print("Aligned — revenue and conversion are moving in the same direction.")
        print()

        # Segment check
        print("--- Segment Check (Device) ---")
        if not segment_results:
            if is_too_early:
                print("Skipped — not enough data for segment analysis yet.")
            else:
                print("No segment data available.")
        else:
            for seg in segment_results:
                if seg.get("error"):
                    print(f"  {seg['segment']}: Error fetching data — {seg['error']}")
                    continue
                flag = " *** CONTRADICTION ***" if seg["contradiction"] else ""
                visitors_str = f" ({fmt_number(seg['visitors'])} visitors)" if seg["visitors"] else ""
                print(
                    f"  {seg['segment']}: {seg['verdict']} "
                    f"({fmt_lift(seg['uplift'])}, {fmt_confidence(seg['p2bb'])} conf)"
                    f"{visitors_str}{flag}"
                )
        print()

        # What to test next
        print("--- What to Test Next ---")
        print(next_test)
        print()
        print("=" * 60)

    else:
        # ── Slack output ──────────────────────────────────────────
        blocks = []

        # Header
        emoji = verdict_emoji(best["verdict"])
        blocks.append(header_block(f"{emoji} TEST VERDICT: {best['verdict']}"))

        # Test summary
        metric_line = f"*Primary Metric:* {primary_label}"
        if cogs:
            metric_line += " (COGS data available)"
        blocks.append(section_block(
            f"*{test_name}*\n"
            f"Type: {test_type}\n"
            f"Runtime: {days_display} | Visitors: {fmt_number(total_visitors)} | Orders: {fmt_number(total_orders)}\n"
            f"{metric_line}"
        ))

        # Maturity warnings
        if is_too_early:
            issues_text = "\n".join(f"- {issue}" for issue in maturity_issues)
            blocks.append(section_block(f"*Maturity Issues:*\n{issues_text}"))

        # Per-variation summary fields
        for i, result in enumerate(variation_results):
            marker = " (BEST)" if len(variation_results) > 1 and i == 0 else ""
            v_text = (
                f"*{result['name']}{marker}*\n"
                f"Verdict: {result['verdict']}\n"
                f"{primary_label}: {fmt_lift(result['uplift'])}\n"
                f"Confidence: {fmt_confidence(result['p2bb'])}"
            )
            if result['ci_low'] is not None and result['ci_high'] is not None:
                v_text += f"\nCI Range: {fmt_lift(result['ci_low'])} to {fmt_lift(result['ci_high'])}"
            if result['rpv_uplift'] is not None:
                v_text += f"\nRPV Lift: {fmt_lift(result['rpv_uplift'])}"
            if result['cr_uplift'] is not None:
                v_text += f"\nCR Lift: {fmt_lift(result['cr_uplift'])}"
            blocks.append(section_block(v_text))

        blocks.append(divider_block())

        # Reasoning
        blocks.append(section_block(f"*Reasoning*\n{best['reasoning']}"))

        # Risk Assessment
        blocks.append(section_block(f"*Risk Assessment*\n{best['risk']}"))

        # Revenue vs Conversion
        rev_conv_text = best["divergence"] if best["divergence"] else "Aligned — revenue and conversion are moving in the same direction."
        blocks.append(section_block(f"*Revenue vs Conversion*\n{rev_conv_text}"))

        # Segments
        if segment_results:
            seg_lines = []
            for seg in segment_results:
                if seg.get("error"):
                    seg_lines.append(f"- {seg['segment']}: Error — {seg['error']}")
                    continue
                flag = " :warning: CONTRADICTION" if seg["contradiction"] else ""
                visitors_str = f" ({fmt_number(seg['visitors'])} visitors)" if seg["visitors"] else ""
                seg_lines.append(
                    f"- {seg['segment']}: {seg['verdict']} "
                    f"({fmt_lift(seg['uplift'])}, {fmt_confidence(seg['p2bb'])} conf)"
                    f"{visitors_str}{flag}"
                )
            blocks.append(section_block(f"*Segment Check (Device)*\n" + "\n".join(seg_lines)))
        elif is_too_early:
            blocks.append(section_block("*Segment Check (Device)*\nSkipped — not enough data for segment analysis yet."))

        # What to test next
        blocks.append(section_block(f"*What to Test Next*\n{next_test}"))

        # Footer
        blocks.append(context_block("Powered by Intelligems Analytics"))

        # Send
        fallback = f"Test Verdict: {best['verdict']} — {test_name}"
        success = send_to_slack(slack_url, blocks, text=fallback)
        if success:
            print("Sent to Slack ✓")
        else:
            print("Failed to send to Slack. Printing to terminal instead.")
            # Fall back to terminal output on failure
            print("\n" + "=" * 60)
            print(f"VERDICT: {best['verdict']} — {test_name}")
            print("=" * 60)


# ── Reasoning and risk builders ──────────────────────────────────────


def build_reasoning(
    verdict: str,
    variation_name: str,
    metric_label: str,
    uplift: float | None,
    p2bb: float | None,
    days: int,
    total_orders: int,
) -> str:
    """Build a plain-English explanation of the verdict."""
    lift_str = fmt_lift(uplift)
    conf_str = fmt_confidence(p2bb)

    if verdict == "TOO EARLY":
        parts = [f'"{variation_name}" has been running for {days} day(s) with {fmt_number(total_orders)} orders.']
        parts.append("There isn't enough data yet to make any call.")
        parts.append("Let it run longer before drawing conclusions.")
        return " ".join(parts)

    if verdict == "WINNER":
        return (
            f'"{variation_name}" is beating control by {lift_str} on {metric_label}, '
            f"with {conf_str} confidence. "
            f"After {days} days and {fmt_number(total_orders)} orders, "
            "the data supports rolling this out."
        )

    if verdict == "LOSER":
        return (
            f'"{variation_name}" is underperforming control by {lift_str} on {metric_label}, '
            f"with {conf_str} confidence that control is better. "
            "The data says this change is hurting — consider ending it."
        )

    if verdict == "FLAT":
        return (
            f'"{variation_name}" shows {lift_str} lift on {metric_label} after {days} days. '
            "That's within the noise threshold. "
            "There's no meaningful difference — pick whichever is simpler to maintain."
        )

    # KEEP RUNNING
    return (
        f'"{variation_name}" shows {lift_str} lift on {metric_label} '
        f"at {conf_str} confidence after {days} days. "
        "There are signals here, but not enough conviction yet. Keep running."
    )


def build_risk(
    p2bb: float | None,
    ci_low: float | None,
    ci_high: float | None,
    metric_label: str,
    profit_note: str | None,
) -> str:
    """Build the risk assessment section."""
    parts = []

    if p2bb is not None:
        conf_pct = p2bb * 100
        risk_pct = 100 - conf_pct
        if conf_pct >= 50:
            parts.append(
                f"At {conf_pct:.0f}% confidence, there's a {risk_pct:.0f}% chance "
                "the control was actually better."
            )
        else:
            parts.append(
                f"At {conf_pct:.0f}% confidence, there's a {100 - risk_pct:.0f}% chance "
                "this variation is actually better than control."
            )
    else:
        parts.append("Not enough data to calculate confidence yet.")

    if ci_low is not None and ci_high is not None:
        parts.append(
            f"The true {metric_label} lift likely falls between "
            f"{fmt_lift(ci_low)} and {fmt_lift(ci_high)}."
        )

    if profit_note:
        parts.append(profit_note)

    return "\n".join(parts) if parts else "Insufficient data for risk assessment."


if __name__ == "__main__":
    main()
