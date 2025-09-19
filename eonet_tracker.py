import requests
import threading
from datetime import date, timedelta

class EONETTracker:
    """
    Handles fetching and processing natural event data from NASA's EONET API.
    """
    def __init__(self):
        self.base_url = "https://eonet.gsfc.nasa.gov/api/v3/events"
        self.events = []
        self.data_lock = threading.Lock()

    def fetch_data(self):
        """Fetches the 20 most recent natural events."""
        params = {
            "limit": 20,
        }
        print("INFO: Fetching EONET data from NASA API...")
        try:
            response = requests.get(self.base_url, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            processed_events = []
            for event in data.get('events', []):
                # CORRECCIÓN: La clave es "geometry" (singular), no "geometries" (plural).
                geometry = event.get('geometry', [])
                if geometry:
                    # Usamos el último punto de la geometría para la ubicación más reciente.
                    geom = geometry[-1] 
                    processed_events.append({
                        "title": event.get('title', 'Unknown Event'),
                        "category": event['categories'][0]['title'] if event.get('categories') else 'Uncategorized',
                        "date": geom.get('date', 'N/A'),
                        "coordinates": geom.get('coordinates', [0, 0])
                    })

            with self.data_lock:
                self.events = processed_events
            
            print(f"INFO: Found {len(self.events)} most recent natural events.")

        except requests.RequestException as e:
            print(f"ERROR: Could not fetch EONET data: {e}")

    def get_events(self):
        """Safely returns the latest fetched event data."""
        with self.data_lock:
            return self.events

    def start_periodic_fetch(self, interval_hours=1):
        """Starts a recurring timer to fetch data periodically."""
        self.fetch_data() # Fetch immediately on start
        fetch_timer = threading.Timer(interval_hours * 3600, self.start_periodic_fetch, [interval_hours])
        fetch_timer.daemon = True
        fetch_timer.start()