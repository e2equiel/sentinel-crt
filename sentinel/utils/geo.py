"""Geospatial helper routines used across the Sentinel runtime."""

from __future__ import annotations

import math

EARTH_CIRCUMFERENCE_M = 40_075_017
EARTH_RADIUS_KM = 6_371


def calculate_zoom_from_radius(radius_m: float, map_width_px: int, latitude: float) -> int:
    """Calculate the Mapbox zoom level for a given radius and viewport width."""
    if radius_m <= 0 or map_width_px <= 0:
        return 10

    meters_per_pixel = (radius_m * 2) / map_width_px
    zoom_level = math.log2(
        (EARTH_CIRCUMFERENCE_M * math.cos(math.radians(latitude)))
        / (256 * meters_per_pixel)
    )
    return int(round(zoom_level))


def deg2num(lat_deg: float, lon_deg: float, zoom: int) -> tuple[int, int]:
    """Convert latitude/longitude to tile numbers for the specified zoom level."""
    lat_rad = math.radians(lat_deg)
    n = 2.0 ** zoom
    xtile = int((lon_deg + 180.0) / 360.0 * n)
    ytile = int((1.0 - math.asinh(math.tan(lat_rad)) / math.pi) / 2.0 * n)
    return xtile, ytile


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Compute the distance between two geographic coordinates in kilometers."""
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (
        math.sin(d_lat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(d_lon / 2) ** 2
    )
    return EARTH_RADIUS_KM * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))


__all__ = ["calculate_zoom_from_radius", "deg2num", "haversine_distance"]
