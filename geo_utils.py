"""Geographic helpers for district centroids."""
from math import asin, cos, radians, sin, sqrt
from typing import Mapping, Tuple

Coordinate = Tuple[float, float]
EARTH_RADIUS_KM = 6371.0


def haversine_km(a: Coordinate, b: Coordinate) -> float:
    """Return great-circle distance between (latitude, longitude) pairs."""
    lat1, lon1 = map(radians, a)
    lat2, lon2 = map(radians, b)
    dlat, dlon = lat2 - lat1, lon2 - lon1
    h = sin(dlat / 2) ** 2 + cos(lat1) * cos(lat2) * sin(dlon / 2) ** 2
    return 2 * EARTH_RADIUS_KM * asin(sqrt(min(1.0, h)))


def nearest_district(latitude: float, longitude: float, profiles: Mapping[str, dict]) -> str:
    """Find the closest district profile by its centroid."""
    if not profiles:
        raise ValueError("profiles must contain at least one district")
    point = (latitude, longitude)
    return min(profiles, key=lambda name: haversine_km(point, profiles[name]["coordinates"]))
