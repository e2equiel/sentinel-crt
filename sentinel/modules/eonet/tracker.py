"""Utility for retrieving natural events from NASA's EONET API."""

from __future__ import annotations

import threading
from typing import List

import requests


class EONETTracker:
    """Fetch and cache natural event data from the EONET feed."""

    def __init__(self) -> None:
        self.base_url = "https://eonet.gsfc.nasa.gov/api/v3/events"
        self.events: List[dict] = []
        self.data_lock = threading.Lock()

    def fetch_data(self) -> None:
        """Fetch the 20 most recent events from the NASA feed."""

        params = {
            "limit": 20,
        }
        print("INFO: Fetching EONET data from NASA API...")
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()

            processed_events: List[dict] = []
            for event in data.get("events", []):
                geometry = event.get("geometry", [])
                if geometry:
                    geom = geometry[-1]
                    processed_events.append(
                        {
                            "title": event.get("title", "Unknown Event"),
                            "category": event["categories"][0]["title"]
                            if event.get("categories")
                            else "Uncategorized",
                            "date": geom.get("date", "N/A"),
                            "coordinates": geom.get("coordinates", [0, 0]),
                        }
                    )

            with self.data_lock:
                self.events = processed_events

            print(f"INFO: Found {len(self.events)} most recent natural events.")

        except requests.RequestException as exc:  # pragma: no cover - network error path
            print(f"ERROR: Could not fetch EONET data: {exc}")

    def get_events(self) -> list[dict]:
        """Return the cached events in a thread-safe way."""

        with self.data_lock:
            return list(self.events)

    def start_periodic_fetch(self, interval_hours: float = 1) -> None:
        """Schedule regular refreshes of the NASA feed."""

        self.fetch_data()
        fetch_timer = threading.Timer(interval_hours * 3600, self.start_periodic_fetch, [interval_hours])
        fetch_timer.daemon = True
        fetch_timer.start()


__all__ = ["EONETTracker"]
