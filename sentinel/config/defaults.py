"""Default configuration used when no user settings are available."""

from __future__ import annotations

from copy import deepcopy

DEFAULT_THEME_COLORS = {
    "default": (0, 255, 65),
    "warning": (255, 165, 0),
    "danger": (255, 0, 0),
}


DEFAULT_CORE_CONFIG = {
    "screen_width": 640,
    "screen_height": 480,
    "fps": 30,
    "startup_screen": "camera",
    "show_header": True,
    "margins": {"top": 10, "bottom": 10, "left": 10, "right": 10},
    "mqtt_host": "localhost",
    "mqtt_port": 1883,
    "mqtt_user": "",
    "mqtt_password": "",
    "frigate_topic": "frigate/events",
    "flight_topic": "flights/overhead",
    "camera_name": "default",
    "camera_rtsp_url": "",
    "frigate_host": "",
    "frigate_resolution": (1920, 1080),
    "bbox_delay": 0.4,
    "zoom_labels": ["person", "car"],
    "zoom_level": 2.5,
    "zoom_reset_time": 5,
    "zoom_speed": 0.08,
    "alert_zones": {"warning": ["street", "driveway"], "danger": ["porch"]},
    "mapbox_user": "",
    "mapbox_style_id": "",
    "mapbox_token": "",
    "map_latitude": 0.0,
    "map_longitude": 0.0,
    "map_radius_m": 15000,
    "map_distance_rings": 3,
    "map_radial_lines": True,
    "flight_screen_timeout": 10,
    "min_flight_altitude_ft": 1000,
    "idle_screen_list": ["camera", "neo_tracker", "eonet_globe"],
}


DEFAULT_MODULES = {
    "camera": {
        "module": "sentinel.modules.camera:CameraModule",
        "enabled": True,
        "config": {},
    },
    "radar": {
        "module": "sentinel.modules.radar:RadarModule",
        "enabled": True,
        "config": {},
    },
    "neo_tracker": {
        "module": "sentinel.modules.neo:NeoTrackerModule",
        "enabled": True,
        "config": {},
    },
    "eonet_globe": {
        "module": "sentinel.modules.eonet:EONETGlobeModule",
        "enabled": True,
        "config": {},
    },
}


DEFAULT_PRIORITIES = {
    "timeout_seconds": 15,
    "idle": {
        "cycle": ["camera", "neo_tracker", "eonet_globe"],
        "dwell_seconds": 20,
    },
    "rules": [
        {
            "when": {"module": "camera", "state": ["danger", "warning"]},
            "weight": 100,
            "screen": "camera",
        },
        {
            "when": {"module": "radar", "state": "air-traffic"},
            "weight": 80,
            "screen": "radar",
        },
    ],
}


def clone_defaults():
    """
    Create deep copies of the module's default configuration structures.
    
    Returns:
        tuple: (core_config, modules, priorities, theme_colors)
            core_config (dict): Deep copy of DEFAULT_CORE_CONFIG.
            modules (dict): Deep copy of DEFAULT_MODULES.
            priorities (dict): Deep copy of DEFAULT_PRIORITIES.
            theme_colors (dict): Deep copy of DEFAULT_THEME_COLORS.
    """

    return (
        deepcopy(DEFAULT_CORE_CONFIG),
        deepcopy(DEFAULT_MODULES),
        deepcopy(DEFAULT_PRIORITIES),
        deepcopy(DEFAULT_THEME_COLORS),
    )
