"""
Intelligems Analytics — Metric Extraction Helpers

Functions to pull values, uplift, confidence, and CI bounds
from the Intelligems analytics response structure.
"""

from typing import Optional, Dict, List, Tuple


# ── Single-metric extraction ─────────────────────────────────────────

def get_metric_value(
    metrics: List[Dict], metric_name: str, variation_id: str
) -> Optional[float]:
    """Get the raw value for a metric + variation."""
    for m in metrics:
        if m.get("variation_id") == variation_id:
            data = m.get(metric_name, {})
            if isinstance(data, dict):
                return data.get("value")
    return None


def get_metric_uplift(
    metrics: List[Dict], metric_name: str, variation_id: str
) -> Optional[float]:
    """Get the uplift (lift vs. control) for a metric + variation."""
    for m in metrics:
        if m.get("variation_id") == variation_id:
            data = m.get(metric_name, {})
            if isinstance(data, dict):
                uplift = data.get("uplift", {})
                if isinstance(uplift, dict):
                    return uplift.get("value")
    return None


def get_metric_confidence(
    metrics: List[Dict], metric_name: str, variation_id: str
) -> Optional[float]:
    """Get p2bb (probability to beat baseline) for a metric + variation.

    Returns None when the API returns null (insufficient data).
    """
    for m in metrics:
        if m.get("variation_id") == variation_id:
            data = m.get(metric_name, {})
            if isinstance(data, dict):
                return data.get("p2bb")
    return None


def get_metric_ci(
    metrics: List[Dict], metric_name: str, variation_id: str
) -> Tuple[Optional[float], Optional[float]]:
    """Get confidence interval bounds (ci_low, ci_high) for uplift."""
    for m in metrics:
        if m.get("variation_id") == variation_id:
            data = m.get(metric_name, {})
            if isinstance(data, dict):
                uplift = data.get("uplift", {})
                if isinstance(uplift, dict):
                    return uplift.get("ci_low"), uplift.get("ci_high")
    return None, None


# ── Aggregate helpers ─────────────────────────────────────────────────

def get_total_visitors(metrics: List[Dict]) -> int:
    """Sum visitors across all variations."""
    total = 0
    for m in metrics:
        v = m.get("n_visitors", {})
        if isinstance(v, dict):
            total += v.get("value", 0) or 0
    return int(total)


def get_total_orders(metrics: List[Dict]) -> int:
    """Sum orders across all variations."""
    total = 0
    for m in metrics:
        o = m.get("n_orders", {})
        if isinstance(o, dict):
            total += o.get("value", 0) or 0
    return int(total)


def get_variation_visitors(metrics: List[Dict], variation_id: str) -> int:
    """Get visitors for a specific variation."""
    val = get_metric_value(metrics, "n_visitors", variation_id)
    return int(val) if val else 0


def get_variation_orders(metrics: List[Dict], variation_id: str) -> int:
    """Get orders for a specific variation."""
    val = get_metric_value(metrics, "n_orders", variation_id)
    return int(val) if val else 0


# ── COGS detection ────────────────────────────────────────────────────

def has_cogs_data(metrics: List[Dict]) -> bool:
    """Check if COGS data exists (gross profit metrics are meaningful).

    When pct_revenue_with_cogs > 0, GPV metrics reflect real profit.
    When it's 0, GPV = RPV (COGS not configured).
    """
    for m in metrics:
        pct = m.get("pct_revenue_with_cogs", {})
        if isinstance(pct, dict):
            val = pct.get("value", 0)
            if val and val > 0:
                return True
    return False


def primary_revenue_metric(metrics: List[Dict]) -> str:
    """Return the best revenue metric: GPV if COGS exist, else RPV."""
    return "gross_profit_per_visitor" if has_cogs_data(metrics) else "net_revenue_per_visitor"


# ── Segment grouping ─────────────────────────────────────────────────

def group_metrics_by_segment(metrics: List[Dict]) -> Dict[str, List[Dict]]:
    """Group audience-view metrics by their segment value.

    The API puts the segment label in the 'audience' field.
    """
    segments = {}
    for m in metrics:
        seg = m.get("audience", "Unknown")
        segments.setdefault(seg, []).append(m)
    return segments
