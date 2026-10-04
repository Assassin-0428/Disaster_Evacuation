"""Deterministic mock weather forecasts and district impact scoring."""
from typing import Dict

# Nine illustrative Indian district profiles, with no network access or credentials.
DISTRICT_PROFILES = {
    "Mumbai": {"coordinates": (19.0760, 72.8777), "baseline_rain_mm": 42, "baseline_wind_kph": 38},
    "Pune": {"coordinates": (18.5204, 73.8567), "baseline_rain_mm": 18, "baseline_wind_kph": 24},
    "Ahmedabad": {"coordinates": (23.0225, 72.5714), "baseline_rain_mm": 8, "baseline_wind_kph": 20},
    "Jaipur": {"coordinates": (26.9124, 75.7873), "baseline_rain_mm": 12, "baseline_wind_kph": 22},
    "Kolkata": {"coordinates": (22.5726, 88.3639), "baseline_rain_mm": 55, "baseline_wind_kph": 44},
    "Chennai": {"coordinates": (13.0827, 80.2707), "baseline_rain_mm": 36, "baseline_wind_kph": 48},
    "Bengaluru": {"coordinates": (12.9716, 77.5946), "baseline_rain_mm": 24, "baseline_wind_kph": 28},
    "Hyderabad": {"coordinates": (17.3850, 78.4867), "baseline_rain_mm": 16, "baseline_wind_kph": 30},
    "Guwahati": {"coordinates": (26.1445, 91.7362), "baseline_rain_mm": 68, "baseline_wind_kph": 52},
}


def mock_forecast(district: str) -> Dict[str, float]:
    """Return stable demo data for a district."""
    profile = DISTRICT_PROFILES[district]
    return {
        "rain_mm_24h": float(profile["baseline_rain_mm"]),
        "wind_kph": float(profile["baseline_wind_kph"]),
    }


def _flood_level(rain_mm: float) -> int:
    return 3 if rain_mm >= 60 else 2 if rain_mm >= 35 else 1 if rain_mm >= 15 else 0


def _cyclone_level(wind_kph: float) -> int:
    return 3 if wind_kph >= 80 else 2 if wind_kph >= 55 else 1 if wind_kph >= 35 else 0


def fetch_district_impact(district: str) -> dict:
    """Score mock flood and cyclone signals into a single impact level (0–3)."""
    forecast = mock_forecast(district)
    flood = _flood_level(forecast["rain_mm_24h"])
    cyclone = _cyclone_level(forecast["wind_kph"])
    return {
        "district": district,
        **forecast,
        "flood_level": flood,
        "cyclone_level": cyclone,
        "impact_level": max(flood, cyclone),
    }


def refresh_all_districts() -> list[dict]:
    """Generate one impact record per configured district."""
    return [fetch_district_impact(name) for name in DISTRICT_PROFILES]