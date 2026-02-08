"""
Intelligems Analytics — Morning Brief

Fetches all active experiments, computes health status for each,
and outputs a prioritized summary with action items.

Designed for daily use — one-glance view of your testing program.
"""

import os
import sys
from datetime import datetime
from dotenv import load_dotenv
from ig_slack import (
    parse_slack_args,
    send_to_slack,
    header_block,
    section_block,
    fields_block,
    divider_block,
    context_block,
    status_emoji,
)

# ── Load environment ─────────────────────────────────────────────────
load_dotenv(os.path.expanduser("~/intelligems-analytics/.env"))

api_key = os.getenv("INTELLIGEMS_API_KEY")
if not api_key or api_key == "your_api_key_here":
    print("Error: No API key found. Set INTELLIGEMS_API_KEY in ~/intelligems-analytics/.env")
    sys.exit(1)

# ── Import core libraries ───────────────────────────────────────────
from ig_client import IntelligemsAPI
from ig_metrics import (
    get_metric_uplift,
    get_metric_confidence,
    get_total_visitors,
    get_total_orders,
    primary_revenue_metric,
)
from ig_helpers import (
    find_control,
    find_variants,
    get_variation_name,
    runtime_days,
    runtime_display,
    fmt_lift,
    fmt_confidence,
    fmt_number,
    detect_test_type,
    daily_visitors,
    daily_orders,
    days_to_target_orders,
)
from ig_config import (
    MIN_RUNTIME_DAYS,
    VERDICT_MIN_ORDERS,
)


# ── Health status logic ──────────────────────────────────────────────

STATUS_ORDER = {"RED": 0, "YELLOW": 1, "GREEN": 2}


def compute_health(runtime, total_orders, daily_vis_rate, best_primary_lift,
                   best_primary_conf, best_conv_lift, best_conv_conf):
    """Determine health status and action item for a test.

    Returns (status, action_text) where status is RED/YELLOW/GREEN.
    """

    # RED: Just started (< 3 days) — verify setup
    if runtime < 3:
        return "RED", "Just started — verify test setup is correct"

    # RED: Zero orders after 3+ days
    if runtime >= 3 and total_orders == 0:
        return "RED", "Zero orders after {0} days — check test setup".format(runtime)

    # RED: Conversion dropping > 20% with high confidence
    if best_conv_lift is not None and best_conv_conf is not None:
        if best_conv_lift < -0.20 and best_conv_conf >= 0.80:
            return "RED", "Conversion dropping {0} — consider pausing".format(
                fmt_lift(best_conv_lift)
            )

    # YELLOW: Too early for conclusions
    if runtime < MIN_RUNTIME_DAYS:
        return "YELLOW", "Only {0} days in — needs more data (min {1})".format(
            runtime, MIN_RUNTIME_DAYS
        )

    # YELLOW: Variant losing on primary metric with moderate confidence
    if best_primary_lift is not None and best_primary_conf is not None:
        if best_primary_lift < 0 and 0.60 <= best_primary_conf < 0.80:
            return "YELLOW", "Trending negative ({0}) — monitor closely".format(
                fmt_lift(best_primary_lift)
            )

    # YELLOW: Very low traffic
    if daily_vis_rate < 50:
        return "YELLOW", "Low traffic ({0:.0f} visitors/day) — will take longer".format(
            daily_vis_rate
        )

    # GREEN: Strong signal — close to callable
    if (best_primary_conf is not None and best_primary_conf >= 0.80
            and best_primary_lift is not None and best_primary_lift > 0.02
            and total_orders >= VERDICT_MIN_ORDERS):
        return "GREEN", "Strong signal ({0} at {1} confidence) — close to callable".format(
            fmt_lift(best_primary_lift), fmt_confidence(best_primary_conf)
        )

    # GREEN: Emerging winner
    if (best_primary_conf is not None and best_primary_conf >= 0.60
            and best_primary_lift is not None and best_primary_lift > 0.02):
        return "GREEN", "Emerging winner ({0}) — gathering more data".format(
            fmt_lift(best_primary_lift)
        )

    # GREEN: default — gathering data on track
    return "GREEN", "Gathering data on track"


def find_best_variant(metrics, variations, metric_name):
    """Find the variant with the highest uplift on a given metric.

    Returns (variant_name, lift, confidence) or (None, None, None).
    """
    variants = find_variants(variations)
    if not variants:
        return None, None, None

    best_name = None
    best_lift = None
    best_conf = None

    for v in variants:
        vid = v["id"]
        lift = get_metric_uplift(metrics, metric_name, vid)
        conf = get_metric_confidence(metrics, metric_name, vid)

        if lift is None:
            continue

        if best_lift is None or lift > best_lift:
            best_lift = lift
            best_conf = conf
            best_name = get_variation_name(variations, vid)

    return best_name, best_lift, best_conf


# ── Main ─────────────────────────────────────────────────────────────

def main():
    api = IntelligemsAPI(api_key)
    slack_url = parse_slack_args(sys.argv)

    # Fetch active experiments
    print("Fetching active experiments...")
    experiments = api.get_active_experiments()

    if not experiments:
        print("\n=== MORNING BRIEF ===")
        print("Date: {0}".format(datetime.now().strftime("%Y-%m-%d %H:%M")))
        print("\nNo active experiments found. All quiet!")
        return

    print("Found {0} active experiment(s)\n".format(len(experiments)))

    # Analyze each test
    test_cards = []

    for exp in experiments:
        name = exp.get("name", "Unnamed Test")
        exp_id = exp["id"]
        print("Analyzing {0}...".format(name))

        # Fetch analytics
        try:
            analytics = api.get_overview_analytics(exp_id)
        except Exception as e:
            print("  Warning: Could not fetch analytics for {0}: {1}".format(name, e))
            test_cards.append({
                "name": name,
                "status": "RED",
                "action": "API error — could not fetch analytics",
                "type": detect_test_type(exp),
                "runtime": 0,
                "runtime_display": "Unknown",
                "visitors": 0,
                "orders": 0,
                "daily_visitors": 0,
                "daily_orders": 0,
                "best_variant": None,
                "primary_metric_label": "RPV",
                "primary_lift": None,
                "primary_conf": None,
                "conv_lift": None,
                "conv_conf": None,
                "days_to_verdict": None,
            })
            continue

        metrics = analytics.get("metrics", [])
        variations = exp.get("variations", [])

        # Runtime (API uses startedAtTs, in milliseconds)
        started_ts = exp.get("startedAtTs") or exp.get("startedAt")
        days = runtime_days(started_ts)
        days_display = runtime_display(started_ts)

        # Totals
        total_vis = get_total_visitors(metrics)
        total_ord = get_total_orders(metrics)

        # Daily rates
        d_vis = daily_visitors(total_vis, days)
        d_ord = daily_orders(total_ord, days)

        # Primary metric
        rev_metric = primary_revenue_metric(metrics)
        is_gpv = rev_metric == "gross_profit_per_visitor"
        primary_label = "GPV" if is_gpv else "RPV"

        # Best variant on primary metric
        best_name, best_p_lift, best_p_conf = find_best_variant(
            metrics, variations, rev_metric
        )

        # Best variant on conversion
        _, best_c_lift, best_c_conf = find_best_variant(
            metrics, variations, "conversion_rate"
        )

        # Health status
        status, action = compute_health(
            days, total_ord, d_vis,
            best_p_lift, best_p_conf,
            best_c_lift, best_c_conf,
        )

        # Days to verdict
        dtv = None
        if total_ord < VERDICT_MIN_ORDERS:
            dtv = days_to_target_orders(total_ord, VERDICT_MIN_ORDERS, d_ord)

        test_cards.append({
            "name": name,
            "status": status,
            "action": action,
            "type": detect_test_type(exp),
            "runtime": days,
            "runtime_display": days_display,
            "visitors": total_vis,
            "orders": total_ord,
            "daily_visitors": d_vis,
            "daily_orders": d_ord,
            "best_variant": best_name,
            "primary_metric_label": primary_label,
            "primary_lift": best_p_lift,
            "primary_conf": best_p_conf,
            "conv_lift": best_c_lift,
            "conv_conf": best_c_conf,
            "days_to_verdict": dtv,
        })

    # Sort by priority: RED first, then YELLOW, then GREEN
    test_cards.sort(key=lambda c: STATUS_ORDER.get(c["status"], 99))

    # ── Program Pulse (computed for both outputs) ──────────────────

    total_daily_vis = sum(c["daily_visitors"] for c in test_cards)
    total_daily_ord = sum(c["daily_orders"] for c in test_cards)
    ready_to_call = sum(
        1 for c in test_cards
        if c["orders"] >= VERDICT_MIN_ORDERS
        and c["runtime"] >= MIN_RUNTIME_DAYS
    )
    need_more_time = len(test_cards) - ready_to_call

    # ── Slack output ──────────────────────────────────────────────

    if slack_url:
        blocks = []
        date_str = datetime.now().strftime("%Y-%m-%d")

        # Header
        blocks.append(header_block("Morning Brief — {0}".format(date_str)))
        blocks.append(divider_block())

        for card in test_cards:
            emoji = status_emoji(card["status"])

            # Test name with status emoji
            blocks.append(section_block("{0} *{1}*".format(emoji, card["name"])))

            # Fields: Type + Runtime | Visitors + Orders
            blocks.append(fields_block([
                "*Type:* {0}".format(card["type"]),
                "*Runtime:* {0}".format(card["runtime_display"]),
                "*Visitors:* {0} ({1:.0f}/day)".format(
                    fmt_number(card["visitors"]), card["daily_visitors"]
                ),
                "*Orders:* {0} ({1:.0f}/day)".format(
                    fmt_number(card["orders"]), card["daily_orders"]
                ),
            ]))

            # Best variant info + status/action
            if card["best_variant"]:
                variant_text = (
                    "*Best variant:* {0} — {1} {2} ({3} confidence)\n"
                    "*Conversion:* {4} ({5})\n"
                    "*Status:* {6}"
                ).format(
                    card["best_variant"],
                    card["primary_metric_label"],
                    fmt_lift(card["primary_lift"]),
                    fmt_confidence(card["primary_conf"]),
                    fmt_lift(card["conv_lift"]),
                    fmt_confidence(card["conv_conf"]),
                    card["action"],
                )
            else:
                variant_text = (
                    "*Best variant:* No variant data available\n"
                    "*Status:* {0}"
                ).format(card["action"])

            # Days to verdict
            if card["days_to_verdict"] is not None:
                if card["days_to_verdict"] == 0:
                    variant_text += "\n*Est. days to verdict:* Ready to call"
                else:
                    variant_text += "\n*Est. days to verdict:* {0}".format(
                        card["days_to_verdict"]
                    )
            elif card["orders"] >= VERDICT_MIN_ORDERS:
                variant_text += "\n*Est. days to verdict:* Ready to call"

            blocks.append(section_block(variant_text))
            blocks.append(divider_block())

        # Program Pulse
        blocks.append(header_block("Program Pulse"))
        blocks.append(fields_block([
            "*Active tests:* {0}".format(len(test_cards)),
            "*Daily visitors:* {0}".format(fmt_number(int(total_daily_vis))),
            "*Daily orders:* {0}".format(fmt_number(int(total_daily_ord))),
            "*Ready to call:* {0}".format(ready_to_call),
            "*Need more time:* {0}".format(need_more_time),
        ]))

        # Footer
        blocks.append(context_block("Powered by Intelligems Analytics"))

        success = send_to_slack(slack_url, blocks, "Morning Brief — {0}".format(date_str))
        if success:
            print("Sent to Slack ✓")
        else:
            print("Failed to send to Slack — check webhook URL")
        return

    # ── Terminal output ───────────────────────────────────────────

    print("\n" + "=" * 50)
    print("=== MORNING BRIEF ===")
    print("Date: {0}".format(datetime.now().strftime("%Y-%m-%d %H:%M")))
    print("=" * 50)

    for card in test_cards:
        print("\n--- {0} {1} ---".format(card["status"], card["name"]))
        print("Type: {0} | Runtime: {1}".format(card["type"], card["runtime_display"]))
        print("Visitors: {0} ({1:.0f}/day) | Orders: {2} ({3:.0f}/day)".format(
            fmt_number(card["visitors"]),
            card["daily_visitors"],
            fmt_number(card["orders"]),
            card["daily_orders"],
        ))

        if card["best_variant"]:
            print("Best variant: {0} — {1} {2} ({3} confidence)".format(
                card["best_variant"],
                card["primary_metric_label"],
                fmt_lift(card["primary_lift"]),
                fmt_confidence(card["primary_conf"]),
            ))
            print("Conversion: {0} ({1})".format(
                fmt_lift(card["conv_lift"]),
                fmt_confidence(card["conv_conf"]),
            ))
        else:
            print("Best variant: No variant data available")

        print("Status: {0}".format(card["action"]))

        if card["days_to_verdict"] is not None:
            if card["days_to_verdict"] == 0:
                print("Est. days to verdict: Ready to call")
            else:
                print("Est. days to verdict: {0}".format(card["days_to_verdict"]))
        elif card["orders"] >= VERDICT_MIN_ORDERS:
            print("Est. days to verdict: Ready to call")

    print("\n" + "=" * 50)
    print("=== PROGRAM PULSE ===")
    print("Active tests: {0}".format(len(test_cards)))
    print("Daily visitors: {0} across all tests".format(fmt_number(int(total_daily_vis))))
    print("Daily orders: {0}".format(fmt_number(int(total_daily_ord))))
    print("Ready to call: {0}".format(ready_to_call))
    print("Need more time: {0}".format(need_more_time))
    print("=" * 50)


if __name__ == "__main__":
    main()
