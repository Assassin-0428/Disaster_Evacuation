"""
Live weather ingestion. Polls OpenWeatherMap for each district, runs the
result through the trained flood risk model, and updates risk_zones in
the database — this is the "real IMD/weather update" step you described.

For each poll cycle:
  1. Fetch current rainfall for each tracked district
  2. Run (rainfall, elevation, distance_from_river, ...) through the model
  3. Update/insert that district's risk_zones row with the new probability
  4. (file #4 will add: check user locations against updated zones -> notify)
"""
import httpx

from app.config import settings
from app.geo_utils import haversine_distance_km
from ml.predict_flood_risk import predict_flood_risk, risk_probability_to_weight
from ml.predict_cyclone_risk import (
    predict_cyclone_risk,
    risk_probability_to_weight as cyclone_risk_probability_to_weight,
    cyclone_impact_level,
)

# District centroids + static geo features (elevation, distance from river,
# distance from coast, etc.) would ideally come from a proper GIS lookup;
# for now, seeded with reasonable real values for your 9 priority districts.
# Extend this dict as you cover more districts.
DISTRICT_PROFILES = {
    #                  lat       lng       elevation  dist_river  flood_freq  dist_coast  surge_exposure  cyclone_freq  mangrove  building_density
    "Puri":          {"lat": 19.8135, "lng": 85.8312, "elevation_m": 3,   "distance_from_river_km": 2.0, "historical_flood_freq": 4,
                       "distance_from_coast_km": 2.0,  "storm_surge_exposure": 0.85, "historical_cyclone_freq": 4, "mangrove_cover_index": 0.15, "building_density_index": 0.55},
    "Kendrapara":    {"lat": 20.5008, "lng": 86.4224, "elevation_m": 2,   "distance_from_river_km": 1.0, "historical_flood_freq": 6,
                       "distance_from_coast_km": 5.0,  "storm_surge_exposure": 0.90, "historical_cyclone_freq": 6, "mangrove_cover_index": 0.55, "building_density_index": 0.35},
    "Ganjam":        {"lat": 19.3149, "lng": 84.7941, "elevation_m": 15,  "distance_from_river_km": 3.5, "historical_flood_freq": 3,
                       "distance_from_coast_km": 8.0,  "storm_surge_exposure": 0.55, "historical_cyclone_freq": 3, "mangrove_cover_index": 0.20, "building_density_index": 0.45},
    "Jagatsinghpur": {"lat": 20.2532, "lng": 86.1739, "elevation_m": 4,   "distance_from_river_km": 1.5, "historical_flood_freq": 5,
                       "distance_from_coast_km": 3.0,  "storm_surge_exposure": 0.80, "historical_cyclone_freq": 5, "mangrove_cover_index": 0.40, "building_density_index": 0.40},
    "Bhadrak":       {"lat": 21.0575, "lng": 86.5151, "elevation_m": 6,   "distance_from_river_km": 2.0, "historical_flood_freq": 4,
                       "distance_from_coast_km": 12.0, "storm_surge_exposure": 0.45, "historical_cyclone_freq": 3, "mangrove_cover_index": 0.30, "building_density_index": 0.40},
    "Balasore":      {"lat": 21.4942, "lng": 86.9317, "elevation_m": 5,   "distance_from_river_km": 2.5, "historical_flood_freq": 4,
                       "distance_from_coast_km": 10.0, "storm_surge_exposure": 0.50, "historical_cyclone_freq": 4, "mangrove_cover_index": 0.25, "building_density_index": 0.45},
    "Cuttack":       {"lat": 20.4625, "lng": 85.8828, "elevation_m": 12,  "distance_from_river_km": 1.0, "historical_flood_freq": 5,
                       "distance_from_coast_km": 25.0, "storm_surge_exposure": 0.20, "historical_cyclone_freq": 1, "mangrove_cover_index": 0.10, "building_density_index": 0.70},
    "Khordha":       {"lat": 20.1830, "lng": 85.6188, "elevation_m": 45,  "distance_from_river_km": 6.0, "historical_flood_freq": 1,
                       "distance_from_coast_km": 20.0, "storm_surge_exposure": 0.15, "historical_cyclone_freq": 1, "mangrove_cover_index": 0.05, "building_density_index": 0.65},
    "Gajapati":      {"lat": 18.7768, "lng": 84.0863, "elevation_m": 300, "distance_from_river_km": 8.0, "historical_flood_freq": 1,
                       "distance_from_coast_km": 55.0, "storm_surge_exposure": 0.05, "historical_cyclone_freq": 0, "mangrove_cover_index": 0.02, "building_density_index": 0.25},
}

# Fixed (slow-changing) profile factors — used alongside live rainfall
DEFAULT_DRAINAGE_QUALITY = 0.4       # coastal Odisha generally has moderate drainage
DEFAULT_URBANIZATION_INDEX = 0.5
DEFAULT_DEFORESTATION_INDEX = 0.3


async def fetch_live_rainfall(lat: float, lng: float) -> float:
    """
    Pulls current + next-hour forecast rainfall (mm) from OpenWeatherMap
    for a given coordinate.
    """
    if not settings.openweather_api_key:
        raise ValueError("OPENWEATHER_API_KEY is not set in .env")

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": lat, "lon": lng,
        "appid": settings.openweather_api_key,
        "units": "metric",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    # OpenWeatherMap reports rain as {"1h": mm} or {"3h": mm} if present, else no rain
    rain = data.get("rain", {})
    rainfall_mm = rain.get("1h", rain.get("3h", 0.0))
    return float(rainfall_mm)


async def fetch_live_wind_and_pressure(lat: float, lng: float) -> tuple[float, float]:
    """
    Pulls current wind speed (converted to km/h) and sea-level pressure
    (hPa) from OpenWeatherMap for a given coordinate — the two live
    signals the cyclone model needs alongside the static district profile.
    """
    if not settings.openweather_api_key:
        raise ValueError("OPENWEATHER_API_KEY is not set in .env")

    url = "https://api.openweathermap.org/data/2.5/weather"
    params = {
        "lat": lat, "lon": lng,
        "appid": settings.openweather_api_key,
        "units": "metric",
    }
    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(url, params=params)
        response.raise_for_status()
        data = response.json()

    wind_speed_ms = data.get("wind", {}).get("speed", 0.0)
    wind_speed_kmph = float(wind_speed_ms) * 3.6
    pressure_hpa = float(data.get("main", {}).get("pressure", 1013))
    return wind_speed_kmph, pressure_hpa


async def update_district_risk(district: str) -> dict:
    """
    Fetches live weather for one district, scores it through the flood
    model, and returns the result (caller decides what to do with it —
    e.g. write to risk_zones, broadcast over WebSocket).
    """
    profile = DISTRICT_PROFILES[district]
    rainfall_mm = await fetch_live_rainfall(profile["lat"], profile["lng"])

    probability = predict_flood_risk(
        rainfall_mm=rainfall_mm,
        elevation_m=profile["elevation_m"],
        distance_from_river_km=profile["distance_from_river_km"],
        historical_flood_freq=profile["historical_flood_freq"],
        drainage_quality=DEFAULT_DRAINAGE_QUALITY,
        urbanization_index=DEFAULT_URBANIZATION_INDEX,
        deforestation_index=DEFAULT_DEFORESTATION_INDEX,
    )
    risk_weight = risk_probability_to_weight(probability)

    if probability < 0.25:
        impact_level = "Low"
    elif probability < 0.5:
        impact_level = "Moderate"
    elif probability < 0.75:
        impact_level = "High"
    else:
        impact_level = "Severe"

    return {
        "district": district,
        "rainfall_mm": rainfall_mm,
        "flood_probability": round(probability, 3),
        "risk_weight": risk_weight,
        "impact_level": impact_level,
    }


async def update_all_districts() -> list[dict]:
    """Runs update_district_risk for every tracked district."""
    results = []
    for district in DISTRICT_PROFILES:
        try:
            result = await update_district_risk(district)
            results.append(result)
        except Exception as e:
            results.append({"district": district, "error": str(e)})
    return results


async def update_district_cyclone_risk(district: str) -> dict:
    """
    Fetches live wind/pressure for one district, scores it through the
    cyclone model, and returns the result — same shape/pattern as
    update_district_risk(), so callers can treat flood and cyclone
    results uniformly.
    """
    profile = DISTRICT_PROFILES[district]
    wind_speed_kmph, pressure_hpa = await fetch_live_wind_and_pressure(profile["lat"], profile["lng"])

    probability = predict_cyclone_risk(
        wind_speed_kmph=wind_speed_kmph,
        pressure_hpa=pressure_hpa,
        distance_from_coast_km=profile["distance_from_coast_km"],
        storm_surge_exposure=profile["storm_surge_exposure"],
        historical_cyclone_freq=profile["historical_cyclone_freq"],
        mangrove_cover_index=profile["mangrove_cover_index"],
        building_density_index=profile["building_density_index"],
    )
    risk_weight = cyclone_risk_probability_to_weight(probability)

    return {
        "district": district,
        "wind_speed_kmph": round(wind_speed_kmph, 1),
        "pressure_hpa": round(pressure_hpa, 1),
        "cyclone_probability": round(probability, 3),
        "risk_weight": risk_weight,
        "impact_level": cyclone_impact_level(probability),
    }


async def update_all_districts_cyclone() -> list[dict]:
    """Runs update_district_cyclone_risk for every tracked district."""
    results = []
    for district in DISTRICT_PROFILES:
        try:
            result = await update_district_cyclone_risk(district)
            results.append(result)
        except Exception as e:
            results.append({"district": district, "error": str(e)})
    return results


_IMPACT_RANK = {"Low": 0, "Moderate": 1, "High": 2, "Severe": 3}


async def update_district_combined_risk(district: str) -> dict:
    """
    Runs both hazard models for one district and returns the worse of
    the two as the "overall" risk — this is what should drive the
    evacuate/don't-evacuate decision, since a district can be flood-safe
    but cyclone-severe (or vice versa).
    """
    flood_risk = await update_district_risk(district)
    cyclone_risk = await update_district_cyclone_risk(district)

    worse = cyclone_risk if _IMPACT_RANK[cyclone_risk["impact_level"]] > _IMPACT_RANK[flood_risk["impact_level"]] else flood_risk

    return {
        "district": district,
        "flood": flood_risk,
        "cyclone": cyclone_risk,
        "overall_impact_level": worse["impact_level"],
        "overall_hazard": "cyclone" if worse is cyclone_risk else "flood",
    }


def nearest_district(lat: float, lng: float) -> dict:
    """Return the tracked district centroid closest to a latitude/longitude."""
    best_district = None
    best_distance = None
    for district, profile in DISTRICT_PROFILES.items():
        distance = haversine_distance_km(lat, lng, profile["lat"], profile["lng"])
        if best_distance is None or distance < best_distance:
            best_district = district
            best_distance = distance
    return {"district": best_district, "distance_km": round(best_distance, 1)}


async def update_all_districts_combined_all() -> list[dict]:
    """
    Runs update_district_combined_risk for every tracked district. Used
    by app/risk_sync.py to refresh road_edges.risk_weight and by the
    admin dashboard's district risk overview.
    """
    results = []
    for district in DISTRICT_PROFILES:
        try:
            result = await update_district_combined_risk(district)
            results.append(result)
        except Exception as e:
            results.append({"district": district, "error": str(e)})
    return results
