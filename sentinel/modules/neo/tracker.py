"""Utility helpers for fetching data from the NASA NEO feed."""

from __future__ import annotations

import threading
from datetime import date, timedelta
from typing import Optional

import requests


class NEOTracker:
    """Fetch and cache data about near-earth objects."""

    def __init__(self, api_key: str) -> None:
        self.api_key = api_key
        self.base_url = "https://api.nasa.gov/neo/rest/v1/feed"
        self.closest_neo: Optional[dict] = None
        self.data_lock = threading.Lock()

    def fetch_data(self) -> None:
        """Retrieve objects for the next week and cache the closest NEO."""

        start_date = date.today().strftime("%Y-%m-%d")
        end_date = (date.today() + timedelta(days=7)).strftime("%Y-%m-%d")
        params = {
            "start_date": start_date,
            "end_date": end_date,
            "api_key": self.api_key,
        }
        print("INFO: Fetching NEO data from NASA API...")
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            all_neos = []
            for date_key in data.get("near_earth_objects", {}):
                all_neos.extend(data["near_earth_objects"][date_key])

            if not all_neos:
                print("WARNING: No NEOs found in the coming week.")
                return

            closest = min(
                all_neos,
                key=lambda neo: float(neo["close_approach_data"][0]["miss_distance"]["kilometers"]),
            )
            approach_info = closest["close_approach_data"][0]

            with self.data_lock:
                self.closest_neo = {
                    "id": closest.get("id", "N/A"),
                    "name": closest.get("name", "Unknown"),
                    "diameter_m": int(
                        closest.get("estimated_diameter", {})
                        .get("meters", {})
                        .get("estimated_diameter_max", 0)
                    ),
                    "is_hazardous": closest.get("is_potentially_hazardous_asteroid", False),
                    "approach_date": approach_info.get("close_approach_date_full", "N/A"),
                    "velocity_kmh": int(
                        float(approach_info.get("relative_velocity", {}).get("kilometers_per_hour", 0))
                    ),
                    "miss_distance_km": int(
                        float(approach_info.get("miss_distance", {}).get("kilometers", 0))
                    ),
                }

            print(f"INFO: Closest NEO identified: {self.closest_neo['name']}")

        except requests.RequestException as exc:  # pragma: no cover - network error path
            print(f"ERROR: Could not fetch NEO data: {exc}")

    def get_closest_neo_data(self) -> Optional[dict]:
        """Return the cached closest NEO information."""

        with self.data_lock:
            return dict(self.closest_neo) if self.closest_neo else None

    def start_periodic_fetch(self, interval_hours: float = 6) -> None:
        """Schedule periodic refreshes of the NEO feed."""

        self.fetch_data()
        fetch_timer = threading.Timer(interval_hours * 3600, self.start_periodic_fetch, [interval_hours])
        fetch_timer.daemon = True
        fetch_timer.start()


__all__ = ["NEOTracker"]
