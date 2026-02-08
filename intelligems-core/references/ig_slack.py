"""
Intelligems Analytics — Slack Integration

Shared helpers for formatting output as Slack Block Kit messages
and sending them to a webhook URL.

All skills support --slack <webhook_url> to send results to Slack
instead of printing to terminal.
"""

import json
import requests
from typing import List, Dict, Optional


# ── Block builders ────────────────────────────────────────────────────

def header_block(text: str) -> Dict:
    """Large bold header text."""
    return {
        "type": "header",
        "text": {"type": "plain_text", "text": text[:150], "emoji": True},
    }


def section_block(text: str) -> Dict:
    """Markdown-formatted section."""
    return {
        "type": "section",
        "text": {"type": "mrkdwn", "text": text},
    }


def fields_block(fields: List[str]) -> Dict:
    """Side-by-side field pairs (max 10 fields)."""
    return {
        "type": "section",
        "fields": [{"type": "mrkdwn", "text": f} for f in fields[:10]],
    }


def divider_block() -> Dict:
    """Horizontal divider line."""
    return {"type": "divider"}


def context_block(text: str) -> Dict:
    """Small gray context text."""
    return {
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": text}],
    }


# ── Status formatting ─────────────────────────────────────────────────

def status_emoji(status: str) -> str:
    """Map status labels to Slack emoji."""
    mapping = {
        "RED": ":red_circle:",
        "YELLOW": ":large_yellow_circle:",
        "GREEN": ":large_green_circle:",
        "WINNER": ":white_check_mark:",
        "LOSER": ":x:",
        "FLAT": ":wavy_dash:",
        "KEEP RUNNING": ":hourglass_flowing_sand:",
        "TOO EARLY": ":hourglass:",
    }
    return mapping.get(status.upper(), ":grey_question:")


def verdict_emoji(verdict: str) -> str:
    """Map verdict to a single emoji for headers."""
    mapping = {
        "WINNER": "✅",
        "LOSER": "❌",
        "FLAT": "➖",
        "KEEP RUNNING": "⏳",
        "TOO EARLY": "⏳",
    }
    return mapping.get(verdict.upper(), "❓")


# ── Send to Slack ─────────────────────────────────────────────────────

def send_to_slack(webhook_url: str, blocks: List[Dict], text: str = "Intelligems Analytics") -> bool:
    """POST blocks to a Slack webhook URL.

    Args:
        webhook_url: Slack incoming webhook URL
        blocks: List of Block Kit block dicts
        text: Fallback text for notifications

    Returns:
        True if successful, False otherwise
    """
    payload = {"text": text, "blocks": blocks}

    try:
        response = requests.post(
            webhook_url,
            json=payload,
            headers={"Content-Type": "application/json"},
            timeout=10,
        )
        if response.status_code == 200 and response.text == "ok":
            return True
        print(f"Slack error: {response.status_code} — {response.text}")
        return False
    except requests.RequestException as e:
        print(f"Slack error: {e}")
        return False


# ── Argument parsing helper ───────────────────────────────────────────

def parse_slack_args(argv: list) -> Optional[str]:
    """Check sys.argv for --slack <webhook_url>.

    Returns the webhook URL if found, None otherwise.
    """
    for i, arg in enumerate(argv):
        if arg == "--slack" and i + 1 < len(argv):
            url = argv[i + 1]
            if url.startswith("https://"):
                return url
            print(f"Warning: Slack webhook URL should start with https://")
            return url
    return None
