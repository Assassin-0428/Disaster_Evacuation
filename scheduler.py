"""Runnable polling loop joining mock weather, risk sync, and geo helpers."""
import argparse
import time

from config import WEATHER_POLL_INTERVAL_MINUTES
from geo_utils import nearest_district
from risk_sync import RiskStore, sync_impacts
from weather_service import DISTRICT_PROFILES, refresh_all_districts


def run_refresh(store: RiskStore | None = None) -> list[dict]:
    """Refresh every district, store/broadcast risk weights, and print a nearby lookup."""
    store = store or RiskStore()
    saved = sync_impacts(refresh_all_districts(), store)
    print(f"Refreshed {len(saved)} districts (mock data):")
    for item in saved:
        print(
            f"  {item['district']:<10} impact={item['impact_level']} "
            f"road-risk={item['road_risk_weight']:.1f}x "
            f"rain={item['rain_mm_24h']:.0f}mm wind={item['wind_kph']:.0f}kph"
        )
    nearest = nearest_district(19.0, 73.0, DISTRICT_PROFILES)
    print(f"Nearest configured district to (19.0, 73.0): {nearest}")
    return saved


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Deterministic mock district weather risk demo"
    )
    parser.add_argument("--once", action="store_true", help="run once and exit")
    args = parser.parse_args()
    store = RiskStore()

    if args.once:
        run_refresh(store)
        return

    interval = WEATHER_POLL_INTERVAL_MINUTES * 60
    print(
        f"Polling every {WEATHER_POLL_INTERVAL_MINUTES} minute(s); "
        "press Ctrl+C to stop."
    )
    try:
        while True:
            run_refresh(store)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()