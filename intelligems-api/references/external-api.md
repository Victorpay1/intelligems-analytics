# Intelligems External API

> **Beta Access:** Contact support at [Intelligems Support](https://portal.usepylon.com/intelligems/forms/intelligems-support-request) to request API access and get your API key.
>
> Feature suggestions: jerica@intelligems.io

---

## Overview

The Intelligems External API provides programmatic access to your Intelligems experiences and analytics data. This RESTful API allows you to integrate Intelligems functionality into your own applications, workflows, and data pipelines.

### What You Can Do

**Retrieve Test & Experience Data**
- List all tests and experiences in your account
- Get detailed configuration for specific tests and experiences including variations, targeting rules, offer details, and content modifications
- Access test and experience metadata like status, test types, and historical actions

**Access Analytics Data**
- Pull performance metrics for any test or experience
- View results by audience segments (device type, visitor type, traffic source, geography, etc.)
- Export analytics data for custom reporting and analysis

**Automate Workflows**
- Integrate Intelligems data into your business intelligence tools
- Build custom dashboards combining Intelligems metrics with other data sources
- Automate reporting and alerting based on test performance

### Common Use Cases

- **Custom Reporting**: Build internal dashboards that combine Intelligems test results with proprietary business metrics
- **Data Warehouse Integration**: Sync experience and analytics data to your data warehouse for unified analysis
- **Automated Monitoring**: Create alerts when tests reach statistical significance or meet specific performance thresholds
- **Cross-Platform Analysis**: Combine Intelligems data with other analytics platforms for comprehensive performance views

---

## Authentication

Include your API key in the `intelligems-access-token` header:

```
intelligems-access-token: your_api_key_here
```

---

## API Reference

Base URL: `https://api.intelligems.io`

### GET /v25-10-beta/experiences-list

Retrieve a list of all experiences with optional filtering.

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| category | string | Filter by `experiment` or `personalization` |
| status | string | Filter by `pending`, `started`, `ended`, or `paused` |
| limit | number/string | Number of results to return |
| page | number/string | Page number for pagination |
| random | boolean | Optional randomization |

**Response:** Returns `experiencesList` array with experience objects containing:
- `id` - UUID of the experience (use this for analytics calls)
- `name` - Experience name
- `status` - Current status
- `category` - experiment or personalization
- `type` - content/advanced, content/template, pricing, shipping, etc.
- `variations` - Array of variation configurations
- `audience` - Targeting rules with `filterType`, `expression`, `action`
- `testTypes` - Object with boolean flags (see below)
- `organizationId` - UUID of the organization

**Timestamp Fields (all in milliseconds):**
- `startedAtTs` - When the test started
- `endedAtTs` - When the test ended (null if active)
- `pausedAtTs` - When paused (null if not paused)
- `createdAtTs` - When created
- `lastUpdateTs` - Last modification
- `archivedAtTs` - When archived (null if not)

**testTypes Flags:**

The `testTypes` object contains boolean flags. Content tests have multiple sub-types — check all `hasTestContent*` flags:
- `hasTestPricing` - Price test
- `hasTestShipping` - Shipping test
- `hasTestCampaign` - Offer/campaign test
- `hasTestContent` - Basic content test
- `hasTestContentAdvanced` - Advanced content test
- `hasTestContentTemplate` - Template test (theme alternate templates)
- `hasTestContentOnsite` - Onsite edit test
- `hasTestContentUrl` - URL redirect test
- `hasTestContentTheme` - Theme test
- `hasTestCheckoutBlocks` - Checkout block test
- `hasTestOnsiteInjections` - Onsite injection test

---

### GET /v25-10-beta/experiences/{experienceId}

Get complete details for a specific experience.

**Path Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| experienceId | UUID | The experience ID |

**Response:** Returns the experience wrapped in an `experience` key:

```json
{
  "experience": {
    "id": "uuid",
    "name": "Test Name",
    "status": "started",
    ...
  }
}
```

**Important:** This is different from the list endpoint (which uses `experiencesList`). Extract with: `data.get("experience", data)`

The experience object includes:
- All base experience properties (same as list endpoint, plus full detail)
- `variations` with full configuration (price changes, onsite edits, offers, redirects)
- `audience` targeting rules
- `experienceIntegrations` - Connected third-party integrations
- `experienceCustomMetrics` - Custom event tracking
- `experienceKeyMetrics` - Business metrics being tracked
- `shippingTestMethodDefinitions` - Shipping rate configurations

---

### GET /v25-10-beta/analytics/resource/{experienceId}

Access analytics data for an experience with customizable date ranges and audience segmentation.

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| view | string | `overview` (default) or `audience` |
| audience | string | Segment by: `device_type`, `visitor_type`, `source_channel`, `source_site`, `country_code`, `landing_page_full_path` |
| start | integer | **Unix timestamp in seconds (10-digit integer)** - Start of date range |
| end | integer | **Unix timestamp in seconds (10-digit integer)** - End of date range |

**IMPORTANT: Date Range Format**

The `start` and `end` parameters MUST be **Unix timestamps in seconds** (10-digit integers), NOT date strings.

```python
from datetime import datetime, timezone

# Correct - Unix timestamp in seconds
jan_20 = datetime(2026, 1, 20, 0, 0, 0, tzinfo=timezone.utc)
start_ts = int(jan_20.timestamp())  # 1737331200

# Wrong - these will return 400 Bad Request
# start = "2026-01-20"           # Date string
# start = "2026-01-20T00:00:00Z" # ISO format
# start = 1737331200000          # Milliseconds (13 digits)
```

**Helper function for date ranges:**
```python
def date_to_unix_range(date) -> tuple:
    """Convert a date to Unix timestamp range (start of day, end of day)."""
    from datetime import datetime

    # Start of day (00:00:00)
    start_dt = datetime.combine(date, datetime.min.time())
    start_ts = int(start_dt.timestamp())

    # End of day (23:59:59)
    end_dt = datetime.combine(date, datetime.max.time().replace(microsecond=0))
    end_ts = int(end_dt.timestamp())

    return start_ts, end_ts
```

**Response:** Returns:
- `datasetId` - "variation_overview"
- `latestRunTs` - Latest calculation timestamp
- `metrics` - Array where **each item represents one variation** (see structure below)
- `variations` - Array with variation details:
  - `id`, `experienceId`, `name`
  - `percentage` - Traffic allocation (0-100)
  - `isControl` - Boolean (true for control/baseline)
  - `order` - Display order
  - `priceChange`, `priceChangeUnit` - For price tests
- `experienceId` and `experienceName`

**Metrics Array Structure:**

Each item in `metrics` represents one variation with metric names as keys:

```json
{
  "metrics": [
    {
      "variation_id": "uuid-of-variation",
      "n_visitors": {"value": 2037},
      "n_orders": {"value": 17},
      "conversion_rate": {
        "value": 0.0083,
        "uplift": {"value": 0.27, "ci_low": -0.30, "ci_high": 1.36},
        "p2bb": 0.77,
        "p2bc": 0.77,
        "ci_low": 0.005,
        "ci_high": 0.013
      },
      "net_revenue_per_visitor": {...},
      "net_revenue_per_order": {...}
    }
  ]
}
```

**Key fields per metric:**
- `value` - The metric value
- `uplift` - Lift vs control (for non-control variations)
- `p2bb` - **Probability to Beat Baseline** (this is the confidence metric, 0-1)
- `p2bc` - Probability to Beat Control
- `ci_low`, `ci_high` - Confidence interval bounds

**Important: `p2bb` Returns `null` for Low-Data Segments**

The API returns `p2bb: null` (not 0, literally null) when there's insufficient data to calculate statistical significance. This typically happens when:
- Segment has fewer than ~10-15 orders per variation
- Not enough conversions to compute confidence intervals

Example from real data:
- Paid Search: 4,431 visitors, 49 orders → `p2bb: 0.86` ✓
- Paid Social: 631 visitors, 5 orders → `p2bb: null` (insufficient data)

**Best Practice:** Always display `n_visitors` and `n_orders` alongside confidence so users understand WHY confidence may be unavailable. Show "Low data" or similar instead of "-" when `p2bb` is null.

**Available Metrics:**

*Core Metrics:*
- `n_visitors` - Number of visitors
- `n_orders` - Number of orders
- `conversion_rate` - Conversion rate
- `net_revenue_per_visitor` - Revenue per visitor (**key metric for price tests**)
- `net_revenue_per_order` - AOV (**key metric for offer tests**)
- `gross_profit_per_visitor` - Profit per visitor (requires COGS data)
- `gross_profit_per_order` - Profit per order (requires COGS data)

*Funnel Metrics:*
- `add_to_cart_rate` - Add to cart rate
- `checkout_begin_rate` - Checkout initiation rate
- `checkout_enter_contact_info_rate` - Contact info submission rate
- `checkout_address_submitted_rate` - Address submission rate
- `abandoned_cart_rate` - Cart abandonment rate
- `abandoned_checkout_rate` - Checkout abandonment rate

*Revenue Metrics:*
- `net_revenue` - Total net revenue
- `net_product_revenue` - Product revenue only
- `net_product_revenue_per_order` - Product revenue per order
- `total_discount` - Total discounts applied
- `avg_discount_per_all_orders` - Average discount per order
- `avg_units_per_order` - Average units per order

*COGS/Profit Detection:*
- `pct_revenue_with_cogs` - **Percentage of revenue with COGS data (0-1)**
  - If `== 0`: No COGS configured, `gross_profit_*` equals `net_revenue_*`
  - If `> 0`: COGS data exists, profit metrics are meaningful

*Subscription Metrics:*
- `n_subscription_orders` - Subscription order count
- `subscription_net_revenue` - Subscription revenue
- `subscription_gross_profit` - Subscription profit
- `pct_subscription_orders` - % of orders that are subscriptions

---

### Audience View Response Structure

When using `view=audience` with an `audience` parameter, the response structure changes:

- `datasetId` becomes `"variation_audience"` (not `"variation_overview"`)
- Each item in `metrics` includes an **`audience` field** containing the segment value

**Critical:** The segment value is ALWAYS in the `audience` field, NOT in a field named after the segment type.

```json
{
  "datasetId": "variation_audience",
  "metrics": [
    {
      "variation_id": "uuid-of-variation",
      "audience": "Desktop",
      "n_visitors": {"value": 1500},
      "net_revenue_per_visitor": {
        "value": 2.45,
        "uplift": {"value": 0.12},
        "p2bb": 0.82
      }
    },
    {
      "variation_id": "uuid-of-variation",
      "audience": "Mobile",
      "n_visitors": {"value": 3200},
      "net_revenue_per_visitor": {...}
    }
  ]
}
```

**Available Segment Values:**

| Segment Type | Possible Values |
|--------------|-----------------|
| `device_type` | Desktop, Mobile, Tablet |
| `visitor_type` | New, Returning |
| `source_channel` | Paid Search, Paid Social, Paid Shopping, Direct, Organic Search, Organic Social, Email, Other, Paid Other |
| `country_code` | US, CA, GB, etc. (ISO country codes) |

**Python Example - Extracting Segment Data:**

```python
def get_segment_analytics(self, experience_id: str, segment_type: str) -> Dict:
    """Fetch analytics segmented by audience type."""
    url = f"{API_BASE}/analytics/resource/{experience_id}"
    params = {"view": "audience", "audience": segment_type}
    response = requests.get(url, headers=self.headers, params=params)
    response.raise_for_status()
    return response.json()

# Usage
data = api.get_segment_analytics(exp_id, "device_type")
metrics = data.get("metrics", [])

# Group by segment value (use "audience" field, not segment_type)
segments = {}
for metric in metrics:
    seg_value = metric.get("audience")  # e.g., "Desktop", "Mobile"
    if seg_value not in segments:
        segments[seg_value] = []
    segments[seg_value].append(metric)
```

---

## Key Data Structures

### Experience Types
- `content/advanced` - Content tests
- `content/template` - Template tests (theme alternate templates)
- `content/onsiteEdits` - Onsite edit tests
- `content/url` - URL redirect tests
- `pricing` - Price tests
- `shipping` - Shipping tests
- `personalization` - Personalizations
- `personalization/offer` - Offer experiences
- `checkoutBlock` - Checkout block tests

**Note:** Use the `testTypes` flags (not the `type` field) for reliable test type detection. The `type` field has many variants, while `testTypes` flags are consistent booleans.

### Variation Properties
- `isControl` - Whether this is the baseline
- `percentage` - Traffic allocation (0-100)
- `priceChange` / `priceChangeUnit` - Price adjustments
- `onsiteEdits` - Content modifications
- `offer` - Discount/offer configuration
- `redirects` - URL redirect rules

### Audience Targeting
- `filterType` - utm, url, device, visitor, country, etc.
- `expression` - Complex filter rules
- `action` - What to do when matched (assignVariation, randomVariation, excludeFromExperience)

---

## Python Code Example

Basic implementation for fetching test data:

```python
import requests
from datetime import datetime
from typing import Optional, List, Dict

API_BASE = "https://api.intelligems.io/v25-10-beta"

class IntelligemsAPI:
    def __init__(self, api_key: str):
        self.headers = {
            "intelligems-access-token": api_key,
            "Content-Type": "application/json"
        }

    def get_active_tests(self) -> List[Dict]:
        """Fetch all currently running tests."""
        url = f"{API_BASE}/experiences-list"
        params = {"status": "started"}
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json().get("experiencesList", [])

    def get_analytics(self, experience_id: str) -> Dict:
        """Fetch analytics for a specific test."""
        url = f"{API_BASE}/analytics/resource/{experience_id}"
        params = {"view": "overview"}
        response = requests.get(url, headers=self.headers, params=params)
        response.raise_for_status()
        return response.json()

    def get_metric_value(self, metrics: List[Dict], metric_name: str, variation_id: str) -> Optional[float]:
        """Extract a metric value for a specific variation.

        Metrics structure: each item has variation_id and metric names as keys.
        Example: metrics[i].n_visitors.value
        """
        for metric in metrics:
            if metric.get("variation_id") == variation_id:
                metric_data = metric.get(metric_name, {})
                if isinstance(metric_data, dict):
                    return metric_data.get("value")
        return None

    def get_metric_confidence(self, metrics: List[Dict], metric_name: str, variation_id: str) -> Optional[float]:
        """Extract confidence (p2bb = probability to beat baseline) for a metric."""
        for metric in metrics:
            if metric.get("variation_id") == variation_id:
                metric_data = metric.get(metric_name, {})
                if isinstance(metric_data, dict):
                    return metric_data.get("p2bb")  # p2bb = probability to beat baseline
        return None

    def calculate_runtime(self, started_ts: float) -> str:
        """Convert timestamp (ms) to human-readable runtime."""
        start = datetime.fromtimestamp(started_ts / 1000)
        delta = datetime.now() - start
        return f"{delta.days} days"

# Usage
api = IntelligemsAPI("your_api_key_here")
tests = api.get_active_tests()

for test in tests:
    analytics = api.get_analytics(test["id"])
    variations = analytics.get("variations", [])
    metrics = analytics.get("metrics", [])

    # Find control and variant
    for v in variations:
        var_id = v["id"]
        visitors = api.get_metric_value(metrics, "n_visitors", var_id)
        conversion = api.get_metric_value(metrics, "conversion_rate", var_id)
        confidence = api.get_metric_confidence(metrics, "conversion_rate", var_id)

        print(f"{test['name']} - {v['name']}")
        print(f"  Visitors: {visitors}, Conversion: {conversion:.2%}, Confidence: {confidence:.0%}")
```

---

## Health Check Formulas

**Conversion Drop Calculation:**
```
drop = (control_conversion - variant_conversion) / control_conversion
```
Example: Control 5% → Variant 3.5% = (5-3.5)/5 = 30% drop

**Recommended Thresholds (Intelligems Philosophy):**
- `MIN_RUNTIME_DAYS = 10` - Don't call winners before this
- `MIN_VISITORS_FOR_SIGNIFICANCE = 100` - Minimum visitors before results meaningful
- `MIN_ORDERS_FOR_SIGNIFICANCE = 10` - Minimum orders before results meaningful
- `MIN_CONFIDENCE_LEVEL = 0.80` - **80% is enough** ("we're not making cancer medicine")
- `NEUTRAL_LIFT_THRESHOLD = 0.05` - ±5% considered flat/neutral

**Note:** Intelligems philosophy is that 80% confidence is sufficient for most pricing decisions. You can always change it back if needed.

---

## Slack Integration Tutorial

Build automated test health monitoring that sends daily updates to Slack.

### Prerequisites
- Claude Account (Pro, Max, Teams, or Enterprise)
- Intelligems API key
- Slack webhook URL

### Setup Steps

1. **Install Claude Code** in Terminal
2. **Create project directory:**
```bash
mkdir intelligems-slack-health-check
cd intelligems-slack-health-check
python3 -m venv venv
source venv/bin/activate
```

3. **Install dependencies:**
```bash
pip install requests python-dotenv
```

4. **Configure environment:**
```bash
echo "INTELLIGEMS_API_KEY=your_api_key_here" > .env
echo "SLACK_WEBHOOK_URL=your_webhook_url_here" >> .env
```

5. **Create config.py with thresholds:**
```python
MIN_RUNTIME_DAYS = 10  # Don't call winners before this
MIN_VISITORS_FOR_SIGNIFICANCE = 100
MIN_ORDERS_FOR_SIGNIFICANCE = 10
CONVERSION_DROP_ALERT_THRESHOLD = 0.20  # 20% drop triggers alert
MIN_CONFIDENCE_LEVEL = 0.80  # 80% is enough (Intelligems philosophy)
```

6. **Create health check script** (intelligems_health_check.py) that:
   - Fetches active tests via `/experiences-list?status=started`
   - Gets analytics for each via `/analytics/resource/{id}`
   - Calculates runtime, health status, metric comparisons
   - Sends formatted Slack message with results

7. **Schedule daily execution** using LaunchAgent (macOS):
```xml
<key>StartCalendarInterval</key>
<dict>
    <key>Hour</key>
    <integer>10</integer>
    <key>Minute</key>
    <integer>0</integer>
</dict>
```

### Customizable Thresholds

- **MIN_RUNTIME_DAYS**: Don't call winners before this (default 10)
- **MIN_VISITORS_FOR_SIGNIFICANCE**: Minimum visitors before considering results meaningful
- **MIN_ORDERS_FOR_SIGNIFICANCE**: Minimum orders before considering results meaningful
- **CONVERSION_DROP_ALERT_THRESHOLD**: Alert when variant drops this % vs control
- **MIN_CONFIDENCE_LEVEL**: Statistical confidence required (default 80% - Intelligems philosophy)

### Output Example

Slack message includes:
- Test name and runtime
- Total visitors
- Control vs variant metrics
- Conversion rate, revenue/visitor, AOV comparisons with lift %
- Statistical significance status

---

## Rate Limiting

The API has aggressive rate limiting:

- **~4 requests** before hitting rate limit
- **25-60 second cooldown** when rate limited (429 response)
- Rate limit applies across all endpoints

**Best Practices:**

A built-in throttle (1 second minimum between requests) prevents most rate limits. Combined with exponential backoff for 429 responses, this handles all normal usage:

```python
import time

REQUEST_DELAY = 1.0  # Minimum 1 second between requests — prevents most 429s
MAX_RETRIES = 5
RETRY_DELAY = 5  # Base delay in seconds, doubles each retry (5, 10, 20, 40, 80)

class IntelligemsAPI:
    def __init__(self, api_key):
        self._last_request_time = 0
        # ...

    def _throttle(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _request(self, url, params=None):
        """Make a GET request with retry logic for rate limits."""
        for attempt in range(MAX_RETRIES):
            self._throttle()
            try:
                response = requests.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as e:
                if e.response.status_code == 429:
                    wait_time = RETRY_DELAY * (2 ** attempt)
                    print(f"Rate limited, waiting {wait_time}s...")
                    time.sleep(wait_time)
                    continue
                raise
        return {}
```

**Tested throughput:** This pattern handles ~15 sequential requests reliably, including segment-heavy queries that trigger 2-3 rate limit retries.

**For batch operations** (like day-by-day analysis):
- Expect ~2-3 minutes for 24 days of data
- Consider caching results locally
- Use weekly batches instead of daily to reduce calls

---

## Related Documentation

- [JavaScript API](https://docs.intelligems.io/developer-resources/javascript-api)
- [MCP Server](https://docs.intelligems.io/developer-resources/mcp-server)
- [Webhook Integration](https://docs.intelligems.io/integrations/webhook-integration)

---

## Working Examples

**Segment Winner Analysis Tool:**
See the [intelligems-segment-analysis skill](https://github.com/Victorpay1/intelligems-segment-analysis) for a working example.

Shows which segments (device, visitor type, traffic source) each active experiment is winning in. Demonstrates audience view API usage, segment extraction, and winner determination logic.

**Temporal Analysis Tool:**
Available as a standalone project (not yet published).

Analyzes day-by-day A/B test performance to identify:
- Days the variant underperformed
- Weekend vs weekday patterns
- Traffic source correlations

Demonstrates:
- Date range filtering with Unix timestamps
- Rate limit handling with exponential backoff
- Building time-series data from multiple API calls
