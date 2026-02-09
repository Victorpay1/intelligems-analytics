# Intelligems API Skill

Load the Intelligems External API documentation into Claude Code to build integrations for A/B test monitoring, health checks, Slack notifications, and custom dashboards.

## Install

```bash
npx skills add Victorpay1/intelligems-api
```

## Usage

```
/intelligems-api
```

Claude will load the full API documentation, then ask what you want to build.

## What's Included

- **API Reference** - All endpoints with request/response formats
- **Metrics Guide** - Available metrics and what they mean
- **Python Examples** - Ready-to-use code snippets
- **Health Check Formulas** - Thresholds and calculations for monitoring
- **Slack Integration Tutorial** - Step-by-step guide for notifications

## Quick Reference

| Endpoint | Purpose |
|----------|---------|
| `GET /experiences-list` | List all tests/experiences |
| `GET /experiences/{id}` | Get full test details |
| `GET /analytics/resource/{id}` | Get analytics data |

**Base URL:** `https://api.intelligems.io/v25-10-beta`

**Auth Header:**
```
intelligems-access-token: your_api_key
```

**Key Metrics:**
- `net_revenue_per_visitor` - Revenue per visitor (north star)
- `gross_profit_per_visitor` - Profit per visitor (requires COGS)
- `conversion_rate` - Conversion rate
- `p2bb` - Probability to beat baseline (confidence metric)

## Common Use Cases

| Build This | You Need |
|------------|----------|
| Daily health check bot | experiences-list + analytics endpoints |
| Slack test notifications | + Slack webhook URL |
| Custom dashboard | All endpoints + audience segmentation |
| Data warehouse export | Analytics endpoint with date ranges |

## Getting API Access

The API is currently in beta. Contact [Intelligems Support](https://portal.usepylon.com/intelligems/forms/intelligems-support-request) to request access.

Feature suggestions: jerica@intelligems.io

## License

MIT
