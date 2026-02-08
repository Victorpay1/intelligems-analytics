"""
Intelligems Analytics — Utility Helpers

Formatting, variation lookup, runtime calculation, and presentation helpers.
"""

from datetime import datetime
from typing import Optional, Dict, List


# ── Variation helpers ─────────────────────────────────────────────────

def find_control(variations: List[Dict]) -> Optional[Dict]:
    """Find the control/baseline variation."""
    for v in variations:
        if v.get("isControl"):
            return v
    return None


def find_variants(variations: List[Dict]) -> List[Dict]:
    """Return all non-control variations."""
    return [v for v in variations if not v.get("isControl")]


def get_variation_name(variations: List[Dict], variation_id: str) -> str:
    """Look up a variation's display name by ID."""
    for v in variations:
        if v["id"] == variation_id:
            return v.get("name", "Unknown")
    return "Unknown"


# ── Runtime calculation ───────────────────────────────────────────────

def runtime_days(started_ts: Optional[float]) -> int:
    """Calculate days since test started (timestamp in milliseconds).

    Works with both startedAt and startedAtTs field values.
    """
    if not started_ts:
        return 0
    start = datetime.fromtimestamp(started_ts / 1000)
    return max((datetime.now() - start).days, 0)


def runtime_display(started_ts: Optional[float]) -> str:
    """Human-readable runtime string."""
    days = runtime_days(started_ts)
    if days == 0:
        return "< 1 day"
    if days == 1:
        return "1 day"
    return f"{days} days"


# ── Formatting ────────────────────────────────────────────────────────

def fmt_lift(lift: Optional[float]) -> str:
    """Format lift as a signed percentage: +12.3% or -4.1%"""
    if lift is None:
        return "—"
    sign = "+" if lift > 0 else ""
    return f"{sign}{lift * 100:.1f}%"


def fmt_pct(value: Optional[float]) -> str:
    """Format a 0-1 value as percentage: 82%"""
    if value is None:
        return "—"
    return f"{value * 100:.0f}%"


def fmt_confidence(p2bb: Optional[float]) -> str:
    """Format p2bb as confidence display. Returns 'Low data' for None."""
    if p2bb is None:
        return "Low data"
    return f"{p2bb * 100:.0f}%"


def fmt_currency(amount: float) -> str:
    """Format a dollar amount: $1,234 or $1.2M"""
    if abs(amount) >= 1_000_000:
        return f"${amount / 1_000_000:,.1f}M"
    if abs(amount) >= 1_000:
        return f"${amount:,.0f}"
    return f"${amount:,.2f}"


def fmt_number(n: int) -> str:
    """Format a number with commas: 45,000"""
    return f"{n:,}"


# ── Test type detection ───────────────────────────────────────────────

def detect_test_type(experiment: Dict) -> str:
    """Determine what kind of test this is from testTypes flags."""
    test_types = experiment.get("testTypes", {})
    if test_types.get("hasTestPricing"):
        return "Pricing"
    if test_types.get("hasTestShipping"):
        return "Shipping"
    if test_types.get("hasTestCampaign"):
        return "Offer"
    if test_types.get("hasTestContent") or test_types.get("hasTestContentAdvanced"):
        return "Content"
    if test_types.get("hasTestContentTemplate") or test_types.get("hasTestContentOnsite"):
        return "Content"
    if test_types.get("hasTestContentUrl") or test_types.get("hasTestContentTheme"):
        return "Content"
    # Fallback to the type field
    exp_type = experiment.get("type", "")
    if "pricing" in exp_type:
        return "Pricing"
    if "shipping" in exp_type:
        return "Shipping"
    if "offer" in exp_type:
        return "Offer"
    return "Content"


# ── Daily run rate ────────────────────────────────────────────────────

def daily_visitors(total_visitors: int, runtime: int) -> float:
    """Calculate average daily visitors."""
    if runtime <= 0:
        return 0.0
    return total_visitors / runtime


def daily_orders(total_orders: int, runtime: int) -> float:
    """Calculate average daily orders."""
    if runtime <= 0:
        return 0.0
    return total_orders / runtime


def days_to_target_orders(
    current_orders: int, target_orders: int, daily_order_rate: float
) -> Optional[int]:
    """Estimate days until a target order count is reached."""
    if daily_order_rate <= 0:
        return None
    remaining = target_orders - current_orders
    if remaining <= 0:
        return 0
    return int(remaining / daily_order_rate) + 1
