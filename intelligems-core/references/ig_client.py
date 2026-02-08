"""
Intelligems Analytics — API Client

Handles all communication with the Intelligems External API.
Includes automatic retry with exponential backoff for rate limits.
"""

import time
import requests
from typing import Dict, List, Optional
from ig_config import (
    API_BASE, REQUEST_DELAY, MAX_RETRIES, RETRY_BASE_DELAY
)


class IntelligemsAPI:
    """Client for the Intelligems External API."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.headers = {
            "intelligems-access-token": api_key,
            "Content-Type": "application/json",
        }
        self._last_request_time = 0

    def _throttle(self):
        """Enforce minimum delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < REQUEST_DELAY:
            time.sleep(REQUEST_DELAY - elapsed)
        self._last_request_time = time.time()

    def _request(self, url: str, params: Optional[Dict] = None) -> Dict:
        """Make a GET request with retry logic for rate limits."""
        for attempt in range(MAX_RETRIES):
            self._throttle()
            try:
                response = requests.get(url, headers=self.headers, params=params)
                response.raise_for_status()
                return response.json()
            except requests.HTTPError as e:
                if e.response is not None and e.response.status_code == 429:
                    wait = RETRY_BASE_DELAY * (2 ** attempt)
                    print(f"  Rate limited. Waiting {wait}s...")
                    time.sleep(wait)
                    continue
                raise
        print("  Warning: Max retries reached. Returning empty result.")
        return {}

    # ── Experience endpoints ──────────────────────────────────────────

    def get_experiences(
        self,
        status: Optional[str] = None,
        category: Optional[str] = None,
    ) -> List[Dict]:
        """List experiences with optional filters.

        Args:
            status: 'started', 'ended', 'pending', 'paused'
            category: 'experiment' or 'personalization'
        """
        params = {}
        if status:
            params["status"] = status
        if category:
            params["category"] = category
        data = self._request(f"{API_BASE}/experiences-list", params)
        return data.get("experiencesList", [])

    def get_active_experiments(self) -> List[Dict]:
        """Fetch all currently running experiments."""
        return self.get_experiences(status="started", category="experiment")

    def get_ended_experiments(self) -> List[Dict]:
        """Fetch all ended experiments."""
        return self.get_experiences(status="ended", category="experiment")

    def get_experience_detail(self, experience_id: str) -> Dict:
        """Get full configuration for a specific experience."""
        data = self._request(f"{API_BASE}/experiences/{experience_id}")
        return data.get("experience", data)

    # ── Analytics endpoints ───────────────────────────────────────────

    def get_overview_analytics(self, experience_id: str) -> Dict:
        """Fetch overview analytics for an experience."""
        return self._request(
            f"{API_BASE}/analytics/resource/{experience_id}",
            params={"view": "overview"},
        )

    def get_segment_analytics(
        self, experience_id: str, segment_type: str
    ) -> Dict:
        """Fetch audience-segmented analytics.

        Args:
            segment_type: 'device_type', 'visitor_type', 'source_channel',
                          'country_code', 'landing_page_full_path'
        """
        return self._request(
            f"{API_BASE}/analytics/resource/{experience_id}",
            params={"view": "audience", "audience": segment_type},
        )

    def get_date_range_analytics(
        self, experience_id: str, start_ts: int, end_ts: int
    ) -> Dict:
        """Fetch analytics for a specific date range.

        Args:
            start_ts: Unix timestamp in seconds (10-digit)
            end_ts: Unix timestamp in seconds (10-digit)
        """
        return self._request(
            f"{API_BASE}/analytics/resource/{experience_id}",
            params={"view": "overview", "start": start_ts, "end": end_ts},
        )
