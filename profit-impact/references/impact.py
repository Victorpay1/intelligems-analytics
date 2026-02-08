"""
Intelligems Analytics — Profit Impact Report

Translates A/B test lift percentages into annualized dollar projections.
Shows conservative and optimistic revenue impact, break-even analysis,
and opportunity cost of waiting.
"""

import sys
import os
from dotenv import load_dotenv

from ig_client import IntelligemsAPI
from ig_metrics import (
    get_metric_value,
    get_metric_uplift,
    get_metric_confidence,
    get_metric_ci,
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
    daily_orders,
)
from ig_config import MIN_CONFIDENCE, MIN_RUNTIME_DAYS, METRIC_LABELS
from ig_slack import parse_slack_args, send_to_slack, header_block, section_block, fields_block, divider_block, context_block


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


def select_experiment(api):
    """List active experiments and let the user pick one."""
    print("Fetching active experiments...")
    experiments = api.get_active_experiments()

    if not experiments:
        print("\nNo active experiments found.")
        print("Make sure your API key is correct and you have running tests.")
        sys.exit(1)

    print(f"\nFound {len(experiments)} active experiment(s):\n")
    for i, exp in enumerate(experiments, 1):
        name = exp.get("name", "Unnamed")
        test_type = detect_test_type(exp)
        days = runtime_days(exp.get("startedAtTs") or exp.get("startedAt"))
        print(f"  [{i}] {name}")
        print(f"      Type: {test_type} | Running: {days} days")

    print()
    while True:
        try:
            choice = input("Select a test (number): ").strip()
            idx = int(choice) - 1
            if 0 <= idx < len(experiments):
                return experiments[idx]
            print(f"Please enter a number between 1 and {len(experiments)}")
        except (ValueError, EOFError):
            print("Please enter a valid number.")


def generate_business_summary(
    test_name, test_type, metric_label, variant_name,
    uplift, confidence, expected_annual, conservative_annual,
    optimistic_annual, daily_cost, ci_low, ci_high, runtime
):
    """Generate a 2-3 sentence stakeholder-ready summary."""
    lines = []

    conf_str = fmt_confidence(confidence)
    has_high_conf = confidence is not None and confidence >= MIN_CONFIDENCE

    if uplift is not None and uplift > 0:
        lines.append(
            f'The "{variant_name}" variant in the {test_name} {test_type.lower()} test '
            f"shows a {fmt_lift(uplift)} lift in {metric_label} "
            f"({conf_str} confidence)."
        )
        if has_high_conf and conservative_annual is not None and conservative_annual > 0:
            lines.append(
                f"Projected annual impact ranges from {fmt_currency(conservative_annual)} "
                f"(conservative) to {fmt_currency(optimistic_annual)} (optimistic), "
                f"with an expected value of {fmt_currency(expected_annual)}."
            )
        elif has_high_conf:
            lines.append(
                f"Expected annual impact: {fmt_currency(expected_annual)}. "
                f"The lower confidence bound crosses zero, so the conservative estimate "
                f"is break-even."
            )
        else:
            lines.append(
                f"Estimated annual impact is {fmt_currency(expected_annual)}, "
                f"but confidence is below {fmt_pct(MIN_CONFIDENCE)} — "
                f"more data is needed before acting."
            )

        if has_high_conf and daily_cost > 0:
            lines.append(
                f"Every day without rolling out this winner costs approximately "
                f"{fmt_currency(daily_cost)}."
            )
    elif uplift is not None and uplift < 0:
        loss = abs(expected_annual)
        lines.append(
            f'The "{variant_name}" variant in the {test_name} {test_type.lower()} test '
            f"shows a {fmt_lift(uplift)} decline in {metric_label} "
            f"({conf_str} confidence)."
        )
        lines.append(
            f"If this variant were rolled out, it would cost approximately "
            f"{fmt_currency(loss)}/year. This test has protected you from that loss."
        )
    else:
        lines.append(
            f'The "{variant_name}" variant in the {test_name} {test_type.lower()} test '
            f"shows no meaningful lift in {metric_label} ({conf_str} confidence)."
        )
        if runtime < MIN_RUNTIME_DAYS:
            lines.append(
                f"The test has only been running {runtime} days — "
                f"let it run at least {MIN_RUNTIME_DAYS} days before drawing conclusions."
            )
        else:
            lines.append("Consider iterating on a new variant or testing a different lever.")

    return " ".join(lines)


# ── Main ─────────────────────────────────────────────────────────────────

def main():
    load_dotenv()
    api_key = os.getenv("INTELLIGEMS_API_KEY")

    if not api_key or api_key == "your_api_key_here":
        print("Error: INTELLIGEMS_API_KEY not set in .env file.")
        print("Add your key to ~/intelligems-analytics/.env")
        sys.exit(1)

    api = IntelligemsAPI(api_key)
    slack_url = parse_slack_args(sys.argv)

    # ── Filter out --slack args before parsing positional args ─────
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

    # ── Select experiment ────────────────────────────────────────────
    if args:
        test_id = args[0]
        print(f"Fetching experiment {test_id}...")
        experiment = api.get_experience_detail(test_id)
        if not experiment:
            print(f"Error: Could not find experiment with ID '{test_id}'.")
            sys.exit(1)
    else:
        experiment = select_experiment(api)

    exp_id = experiment.get("id", experiment.get("_id", ""))
    exp_name = experiment.get("name", "Unnamed Test")
    test_type = detect_test_type(experiment)
    started_at = experiment.get("startedAtTs") or experiment.get("startedAt")
    runtime = runtime_days(started_at)
    runtime_str = runtime_display(started_at)
    variations = experiment.get("variations", [])

    print(f"\nAnalyzing: {exp_name}")
    print(f"Type: {test_type} | Runtime: {runtime_str}")

    # ── Fetch analytics ──────────────────────────────────────────────
    print("Fetching analytics data...")
    analytics = api.get_overview_analytics(exp_id)
    metrics = analytics.get("metrics", [])

    if not metrics:
        print("Error: No analytics data available for this test.")
        sys.exit(1)

    # ── Identify control and variants ────────────────────────────────
    control = find_control(variations)
    if not control:
        print("Error: Could not identify control variation.")
        sys.exit(1)

    variant_list = find_variants(variations)
    if not variant_list:
        print("Error: No variant variations found.")
        sys.exit(1)

    control_id = control["id"]
    control_name = get_variation_name(variations, control_id)

    # ── Determine primary metric ─────────────────────────────────────
    metric_name = primary_revenue_metric(metrics)
    metric_label = METRIC_LABELS.get(metric_name, metric_name)
    uses_cogs = has_cogs_data(metrics)

    print(f"Primary metric: {metric_label}" + (" (COGS data available)" if uses_cogs else ""))

    # ── Aggregate stats ──────────────────────────────────────────────
    total_visitors = get_total_visitors(metrics)
    total_orders = get_total_orders(metrics)

    if total_orders == 0:
        print("\nError: This test has 0 orders. Cannot calculate financial impact.")
        print("The test needs more time to accumulate conversion data.")
        sys.exit(1)

    avg_daily_visitors = daily_visitors(total_visitors, runtime) if runtime > 0 else 0
    avg_daily_orders = daily_orders(total_orders, runtime) if runtime > 0 else 0

    # ── Find best variant ────────────────────────────────────────────
    best = pick_best_variant(variant_list, metrics, metric_name)
    if not best:
        print("Error: Could not determine best variant (no uplift data).")
        sys.exit(1)

    best_id = best["id"]
    best_name = get_variation_name(variations, best_id)

    # ── Extract metrics for best variant ─────────────────────────────
    control_value = get_metric_value(metrics, metric_name, control_id)
    uplift = get_metric_uplift(metrics, metric_name, best_id)
    confidence = get_metric_confidence(metrics, metric_name, best_id)
    ci_low, ci_high = get_metric_ci(metrics, metric_name, best_id)

    if control_value is None or uplift is None:
        print("Error: Insufficient metric data to calculate impact.")
        sys.exit(1)

    # ── Core calculations ────────────────────────────────────────────
    annual_visitors = avg_daily_visitors * 365
    annual_baseline = annual_visitors * control_value

    # Expected impact
    expected_annual = annual_baseline * uplift

    # Confidence-adjusted range
    if ci_low is not None:
        conservative_annual = annual_baseline * ci_low if ci_low > 0 else 0.0
    else:
        conservative_annual = None

    if ci_high is not None:
        optimistic_annual = annual_baseline * ci_high
    else:
        optimistic_annual = None

    # Monthly breakdowns
    expected_monthly = expected_annual / 12
    conservative_monthly = conservative_annual / 12 if conservative_annual is not None else None
    optimistic_monthly = optimistic_annual / 12 if optimistic_annual is not None else None

    # ── Break-even analysis ──────────────────────────────────────────
    breakeven_lines = []

    # Check for RPV up + CR down divergence
    cr_uplift = get_metric_uplift(metrics, "conversion_rate", best_id)
    rpv_uplift = get_metric_uplift(metrics, "net_revenue_per_visitor", best_id)

    if rpv_uplift is not None and rpv_uplift > 0 and cr_uplift is not None and cr_uplift < 0:
        cr_drop_pct = abs(cr_uplift) * 100
        rpv_gain_pct = rpv_uplift * 100
        breakeven_lines.append(
            f"Revenue per visitor is up {rpv_gain_pct:.1f}% while conversion rate "
            f"is down {cr_drop_pct:.1f}%."
        )
        headroom = rpv_gain_pct - cr_drop_pct
        if headroom > 0:
            breakeven_lines.append(
                f"You have {headroom:.1f}% of headroom — the revenue gain more than "
                f"absorbs the conversion dip."
            )
        breakeven_lines.append(
            f"You could afford up to ~{rpv_gain_pct:.1f}% conversion drop and still "
            f"come out ahead on revenue."
        )

    if test_type == "Pricing" and uplift > 0:
        # For pricing tests: how many customers can you lose and still win?
        if uplift > 0:
            customer_loss_limit = uplift * 100
            breakeven_lines.append(
                f"Pricing insight: At this {fmt_lift(uplift)} lift, you would need to "
                f"lose more than {customer_loss_limit:.1f}% of your customers to lose money."
            )

    if not breakeven_lines:
        if uplift > 0:
            breakeven_lines.append(
                "No metric divergence detected — revenue and conversion are "
                "moving in the same direction."
            )
        elif uplift < 0:
            breakeven_lines.append(
                "This variant underperforms the control. "
                "No break-even scenario exists — the control is the better option."
            )
        else:
            breakeven_lines.append("No meaningful difference detected between variants.")

    # ── Opportunity cost ─────────────────────────────────────────────
    daily_impact = expected_annual / 365 if expected_annual else 0
    weekly_impact = daily_impact * 7
    monthly_impact_cost = daily_impact * 30

    # ── CAC equivalence ──────────────────────────────────────────────
    assumed_cac = 40  # Mid-range assumption ($30-$50)
    monthly_equiv_customers = abs(expected_monthly) / assumed_cac if expected_monthly else 0

    # ── Business Case Summary (computed before output) ──────────────
    summary = generate_business_summary(
        exp_name, test_type, metric_label, best_name,
        uplift, confidence, expected_annual, conservative_annual,
        optimistic_annual, daily_impact, ci_low, ci_high, runtime
    )

    # ── Slack output ──────────────────────────────────────────────────
    if slack_url:
        blocks = []

        # Header
        blocks.append(header_block("\U0001f4b0 Profit Impact Report"))

        # Test info
        variant_label = "Best variant" if len(variant_list) > 1 else "Variant"
        blocks.append(section_block(
            f"*{exp_name}*\n"
            f"Type: {test_type} | Runtime: {runtime_str}\n"
            f"{variant_label}: {best_name} vs {control_name}"
        ))

        blocks.append(divider_block())

        # Annual impact fields
        annual_fields = [
            f"*Expected Annual*\n{fmt_currency(expected_annual)}",
            f"*Lift*\n{fmt_lift(uplift)} ({fmt_confidence(confidence)} conf.)",
        ]
        if conservative_annual is not None:
            annual_fields.append(f"*Conservative*\n{fmt_currency(conservative_annual)}")
        else:
            annual_fields.append("*Conservative*\nInsufficient data")
        if optimistic_annual is not None:
            annual_fields.append(f"*Optimistic*\n{fmt_currency(optimistic_annual)}")
        else:
            annual_fields.append("*Optimistic*\nInsufficient data")
        blocks.append(fields_block(annual_fields))

        # Monthly breakdown
        monthly_parts = [f"Expected: *{fmt_currency(expected_monthly)}*/mo"]
        if conservative_monthly is not None:
            monthly_parts.append(f"Conservative: *{fmt_currency(conservative_monthly)}*/mo")
        if optimistic_monthly is not None:
            monthly_parts.append(f"Optimistic: *{fmt_currency(optimistic_monthly)}*/mo")
        blocks.append(section_block(
            "*Monthly Breakdown*\n" + " | ".join(monthly_parts)
        ))

        # Break-even
        if breakeven_lines:
            blocks.append(section_block(
                "*Break-Even Analysis*\n" + "\n".join(breakeven_lines)
            ))

        # Opportunity cost (positive lift only)
        if uplift is not None and uplift > 0:
            blocks.append(section_block(
                "*Opportunity Cost*\n"
                f"Daily: ~{fmt_currency(abs(daily_impact))} | "
                f"Weekly: ~{fmt_currency(abs(weekly_impact))} | "
                f"Monthly: ~{fmt_currency(abs(monthly_impact_cost))}"
            ))

        # Business case summary
        blocks.append(section_block(f"*Business Case Summary*\n{summary}"))

        # Warnings
        warnings = []
        if confidence is not None and confidence < MIN_CONFIDENCE:
            warnings.append(
                f":warning: Confidence ({fmt_confidence(confidence)}) is below "
                f"{fmt_pct(MIN_CONFIDENCE)}. Projections carry higher uncertainty."
            )
        if runtime < MIN_RUNTIME_DAYS:
            warnings.append(
                f":warning: Test has only run {runtime} days "
                f"(min recommended: {MIN_RUNTIME_DAYS}). Projections may shift."
            )
        if warnings:
            blocks.append(context_block("\n".join(warnings)))

        blocks.append(context_block("Powered by Intelligems Analytics"))

        ok = send_to_slack(slack_url, blocks, f"Profit Impact: {exp_name}")
        if ok:
            print("\nSent to Slack \u2713")
        else:
            print("\nFailed to send to Slack — see error above.")

    else:
        # ── Terminal output ───────────────────────────────────────────
        print()
        print("=" * 55)
        print("  PROFIT IMPACT REPORT")
        print("=" * 55)
        print(f"  Test: {exp_name}")
        print(f"  Type: {test_type} | Runtime: {runtime_str}")
        print(f"  Visitors: {fmt_number(total_visitors)} ({fmt_number(int(avg_daily_visitors))}/day)")
        print(f"  Orders: {fmt_number(total_orders)} ({fmt_number(int(avg_daily_orders))}/day)")
        if len(variant_list) > 1:
            print(f"  Best variant: {best_name}")
        else:
            print(f"  Variant: {best_name}")
        print(f"  Control: {control_name}")
        print()

        # ── Annual Revenue Impact ────────────────────────────────────
        print("-" * 55)
        print("  ANNUAL REVENUE IMPACT")
        print("-" * 55)
        print(f"  Metric: {metric_label}" + (" (includes COGS)" if uses_cogs else ""))
        print(f"  Control value: {fmt_currency(control_value)}/visitor")
        print(f"  Variant lift: {fmt_lift(uplift)} ({fmt_confidence(confidence)} confidence)")
        print()
        print(f"  Expected annual impact:     {fmt_currency(expected_annual)}")

        if conservative_annual is not None:
            print(f"  Conservative estimate:      {fmt_currency(conservative_annual)}"
                  f"  (lower CI bound: {fmt_lift(ci_low)})")
        else:
            print(f"  Conservative estimate:      Insufficient data for range")

        if optimistic_annual is not None:
            print(f"  Optimistic estimate:        {fmt_currency(optimistic_annual)}"
                  f"  (upper CI bound: {fmt_lift(ci_high)})")
        else:
            print(f"  Optimistic estimate:        Insufficient data for range")

        print()

        # ── Monthly Breakdown ────────────────────────────────────────
        print("-" * 55)
        print("  MONTHLY BREAKDOWN")
        print("-" * 55)
        print(f"  Expected:     {fmt_currency(expected_monthly)}/month")

        if conservative_monthly is not None:
            print(f"  Conservative: {fmt_currency(conservative_monthly)}/month")
        else:
            print(f"  Conservative: Insufficient data")

        if optimistic_monthly is not None:
            print(f"  Optimistic:   {fmt_currency(optimistic_monthly)}/month")
        else:
            print(f"  Optimistic:   Insufficient data")

        print()

        # ── Break-Even Analysis ──────────────────────────────────────
        print("-" * 55)
        print("  BREAK-EVEN ANALYSIS")
        print("-" * 55)
        for line in breakeven_lines:
            print(f"  {line}")
        print()

        # ── Opportunity Cost ─────────────────────────────────────────
        if uplift is not None and uplift > 0:
            print("-" * 55)
            print("  OPPORTUNITY COST")
            print("-" * 55)
            print(f"  Daily:   Waiting costs ~{fmt_currency(abs(daily_impact))}/day")
            print(f"  Weekly:  A one-week delay = ~{fmt_currency(abs(weekly_impact))}")
            print(f"  Monthly: A one-month delay = ~{fmt_currency(abs(monthly_impact_cost))}")
            print()

        # ── CAC Equivalence ──────────────────────────────────────────
        if expected_monthly != 0:
            print("-" * 55)
            print("  MARKETING EQUIVALENCE")
            print("-" * 55)
            if uplift is not None and uplift > 0:
                print(
                    f"  This lift equals the value of acquiring ~"
                    f"{fmt_number(int(monthly_equiv_customers))} additional customers/month"
                )
                print(f"  — without spending an extra dollar on marketing.")
                print(f"  (Based on ~{fmt_currency(assumed_cac)} average CAC)")
            else:
                print(
                    f"  This variant would lose the equivalent of ~"
                    f"{fmt_number(int(monthly_equiv_customers))} customers/month in value."
                )
            print()

        # ── Business Case Summary ────────────────────────────────────
        print("-" * 55)
        print("  BUSINESS CASE SUMMARY")
        print("-" * 55)
        # Word-wrap the summary at ~50 chars per line for readability
        words = summary.split()
        line = "  "
        for word in words:
            if len(line) + len(word) + 1 > 55:
                print(line)
                line = "  " + word
            else:
                line += (" " if len(line) > 2 else "") + word
        if line.strip():
            print(line)
        print()
        print("=" * 55)

        # ── Confidence warning ───────────────────────────────────────
        if confidence is not None and confidence < MIN_CONFIDENCE:
            print()
            print(f"  *** CAUTION: Confidence ({fmt_confidence(confidence)}) is below "
                  f"the {fmt_pct(MIN_CONFIDENCE)} threshold. ***")
            print(f"  These projections carry higher uncertainty.")
            print(f"  Let the test run longer before making decisions.")
            print()

        if runtime < MIN_RUNTIME_DAYS:
            print()
            print(f"  *** NOTE: Test has only run {runtime} days "
                  f"(minimum recommended: {MIN_RUNTIME_DAYS}). ***")
            print(f"  Projections may shift as more data comes in.")
            print()


if __name__ == "__main__":
    main()
