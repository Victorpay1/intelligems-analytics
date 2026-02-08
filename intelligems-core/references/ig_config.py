"""
Intelligems Analytics — Shared Configuration

Thresholds and constants used across all skills.
Intelligems philosophy: 80% confidence is enough. We're not making cancer medicine.
"""

# API
API_BASE = "https://api.intelligems.io/v25-10-beta"

# Confidence & significance
MIN_CONFIDENCE = 0.80          # 80% p2bb = "confident enough to act"
HIGH_CONFIDENCE = 0.95         # 95%+ = very high confidence
NEUTRAL_LIFT_THRESHOLD = 0.02  # ±2% lift = effectively flat

# Maturity — don't make calls on immature tests
MIN_RUNTIME_DAYS = 10
MIN_VISITORS = 100
MIN_ORDERS = 10

# Verdict thresholds
VERDICT_MIN_RUNTIME = 10       # Days before issuing a verdict
VERDICT_MIN_ORDERS = 30        # Orders before a verdict is credible

# Rate limiting
REQUEST_DELAY = 1.0            # Seconds between requests
MAX_RETRIES = 5
RETRY_BASE_DELAY = 5           # Seconds, doubles each retry

# Segments available in the API
SEGMENT_TYPES = [
    ("device_type", "Device"),
    ("visitor_type", "Visitor Type"),
    ("source_channel", "Traffic Source"),
]

ALL_SEGMENT_TYPES = [
    ("device_type", "Device"),
    ("visitor_type", "Visitor Type"),
    ("source_channel", "Traffic Source"),
    ("country_code", "Country"),
]

# Funnel stages in order
FUNNEL_STAGES = [
    ("add_to_cart_rate", "Add to Cart"),
    ("checkout_begin_rate", "Begin Checkout"),
    ("checkout_enter_contact_info_rate", "Enter Contact Info"),
    ("checkout_address_submitted_rate", "Submit Address"),
    ("conversion_rate", "Purchase"),
]

# Metric display names
METRIC_LABELS = {
    "net_revenue_per_visitor": "Revenue / Visitor",
    "gross_profit_per_visitor": "Profit / Visitor",
    "conversion_rate": "Conversion Rate",
    "net_revenue_per_order": "AOV",
    "n_visitors": "Visitors",
    "n_orders": "Orders",
    "add_to_cart_rate": "Add to Cart Rate",
    "checkout_begin_rate": "Checkout Rate",
    "abandoned_cart_rate": "Cart Abandonment",
    "abandoned_checkout_rate": "Checkout Abandonment",
}
