"""Background live-risk scheduler.

Polls all tracked districts, persists weather/risk snapshots, updates the
risk-weighted routing graph, and broadcasts WebSocket updates. Risk alerts
are emitted only when a district's overall impact level changes.
"""
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import text

from app.config import settings
from app.database import SessionLocal
from app.risk_sync import apply_district_risk_to_roads
from app.weather_service import DISTRICT_PROFILES, update_district_combined_risk
from app.websocket_manager import manager

_ZONE_HALF_WIDTH_DEG = 0.15
_RISK_LEVEL_BY_IMPACT = {"Low": 1, "Moderate": 2, "High": 3, "Severe": 4}
_last_impact_level: dict[str, str] = {}

scheduler = AsyncIOScheduler()


def _insert_weather_snapshot(db, district: str, flood: dict, cyclone: dict) -> None:
    db.execute(text("""
        INSERT INTO weather_snapshots (district, rainfall_mm, wind_speed_kmph, forecast_summary)
        VALUES (:district, :rainfall_mm, :wind_speed_kmph, :forecast_summary)
    """), {
        "district": district,
        "rainfall_mm": flood.get("rainfall_mm"),
        "wind_speed_kmph": cyclone.get("wind_speed_kmph"),
        "forecast_summary": f"flood={flood.get('impact_level')} cyclone={cyclone.get('impact_level')}",
    })


def _upsert_risk_zone(db, district: str, zone_type: str, impact_level: str, probability: float) -> None:
    profile = DISTRICT_PROFILES[district]
    west = profile["lng"] - _ZONE_HALF_WIDTH_DEG
    east = profile["lng"] + _ZONE_HALF_WIDTH_DEG
    south = profile["lat"] - _ZONE_HALF_WIDTH_DEG
    north = profile["lat"] + _ZONE_HALF_WIDTH_DEG

    db.execute(text("""
        DELETE FROM risk_zones WHERE district = :district AND zone_type = :zone_type
    """), {"district": district, "zone_type": zone_type})

    db.execute(text("""
        INSERT INTO risk_zones (zone_type, risk_level, risk_probability, district, geom)
        VALUES (
            :zone_type, :risk_level, :risk_probability, :district,
            ST_MakeEnvelope(:west, :south, :east, :north, 4326)::geography
        )
    """), {
        "zone_type": zone_type,
        "risk_level": _RISK_LEVEL_BY_IMPACT.get(impact_level, 1),
        "risk_probability": probability,
        "district": district,
        "west": west, "south": south, "east": east, "north": north,
    })


async def poll_all_districts() -> None:
    results = []
    district_impact = {}

    for district in DISTRICT_PROFILES:
        try:
            combined = await update_district_combined_risk(district)
        except Exception as exc:
            print(f"[scheduler] weather poll failed for {district}: {exc}")
            continue

        results.append(combined)
        flood = combined["flood"]
        cyclone = combined["cyclone"]
        overall_level = combined["overall_impact_level"]
        district_impact[district] = overall_level

        db = SessionLocal()
        try:
            _insert_weather_snapshot(db, district, flood, cyclone)
            _upsert_risk_zone(db, district, "flood", flood["impact_level"], flood["flood_probability"])
            _upsert_risk_zone(db, district, "cyclone", cyclone["impact_level"], cyclone["cyclone_probability"])
            db.commit()
        except Exception as exc:
            db.rollback()
            print(f"[scheduler] DB write failed for {district}: {exc}")
        finally:
            db.close()

        previous_level = _last_impact_level.get(district)
        if previous_level != overall_level:
            _last_impact_level[district] = overall_level
            await manager.broadcast({
                "type": "risk_alert",
                "data": {
                    "district": district,
                    "impact_level": overall_level,
                    "driving_hazard": combined["overall_hazard"],
                    "flood_probability": flood["flood_probability"],
                    "cyclone_probability": cyclone["cyclone_probability"],
                    "should_evacuate": overall_level in ("High", "Severe"),
                    "previous_level": previous_level,
                },
            })
            print(f"[scheduler] {district}: {previous_level} -> {overall_level}")

    if district_impact:
        db = SessionLocal()
        try:
            road_summary = apply_district_risk_to_roads(db, district_impact)
        except Exception as exc:
            db.rollback()
            road_summary = {"edges_touched": 0, "by_district": {}, "error": str(exc)}
            print(f"[scheduler] road-risk sync failed: {exc}")
        finally:
            db.close()

        await manager.broadcast({
            "type": "risk_updated",
            "data": {"districts": results, "roads_updated": road_summary},
        })


def start_scheduler() -> None:
    if scheduler.running:
        return
    interval = settings.weather_poll_interval_minutes
    scheduler.add_job(
        poll_all_districts,
        "interval",
        minutes=interval,
        id="weather_poll",
        replace_existing=True,
    )
    scheduler.start()
    print(f"[scheduler] started — polling every {interval} minute(s) for {len(DISTRICT_PROFILES)} districts")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)
        print("[scheduler] stopped")
