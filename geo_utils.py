"""
Hand-written geospatial math — haversine distance and ray-casting
point-in-polygon — used anywhere we need geo calculations without
relying on PostGIS's built-in ST_* functions. This is the "we wrote
the algorithm ourselves" layer for your report.
"""
import math


def haversine_distance_km(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Great-circle distance between two lat/lng points, in kilometers.
    This is what A* will use as its heuristic (straight-line distance
    to the goal), and what we use to compute base edge distances.
    """
    R = 6371.0  # Earth's radius in km

    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)

    a = (
        math.sin(delta_phi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    )
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return R * c


def point_in_polygon(lat: float, lng: float, polygon_coords: list[list[float]]) -> bool:
    """
    Ray-casting algorithm: is point (lat, lng) inside the polygon?
    polygon_coords is a list of [lat, lng] pairs forming the polygon
    boundary (matches the format used in risk_zones.polygon_coords).

    How it works: cast an imaginary ray from the point going east
    (increasing longitude) to infinity, and count how many polygon edges
    it crosses. Odd number of crossings = inside. Even = outside.
    """
    n = len(polygon_coords)
    inside = False

    j = n - 1
    for i in range(n):
        lat_i, lng_i = polygon_coords[i]
        lat_j, lng_j = polygon_coords[j]

        # Does the edge (i,j) straddle the point's latitude?
        intersects_latitude = (lat_i > lat) != (lat_j > lat)

        if intersects_latitude:
            # Longitude where this edge crosses the point's latitude
            lng_at_crossing = (lng_j - lng_i) * (lat - lat_i) / (lat_j - lat_i) + lng_i
            if lng < lng_at_crossing:
                inside = not inside

        j = i

    return inside


def point_in_any_zone(lat: float, lng: float, zones: list[dict]) -> list[dict]:
    """
    Checks a point against a list of risk zones (each with a
    'polygon_coords' key), returns the zones it falls inside.
    Used to check: is this user's location currently in a danger zone?
    """
    matches = []
    for zone in zones:
        if point_in_polygon(lat, lng, zone["polygon_coords"]):
            matches.append(zone)
    return matches


if __name__ == "__main__":
    # Quick sanity tests
    # Distance from Bhubaneswar to Puri (real-world ~60km by road, less as the crow flies)
    dist = haversine_distance_km(20.2961, 85.8245, 19.8135, 85.8312)
    print(f"Bhubaneswar -> Puri straight-line distance: {dist:.2f} km")

    # Simple square polygon test: corners at (0,0),(0,10),(10,10),(10,0)
    square = [[0, 0], [0, 10], [10, 10], [10, 0]]
    print(f"(5,5) inside square? {point_in_polygon(5, 5, square)}")   # should be True
    print(f"(15,15) inside square? {point_in_polygon(15, 15, square)}")  # should be False