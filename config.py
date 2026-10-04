"""Tiny .env reader and application settings; uses only the Python standard library."""
from pathlib import Path
import os

PROJECT_ROOT = Path(__file__).resolve().parent


def _load_env_file(path: Path = PROJECT_ROOT / ".env") -> None:
    """Load KEY=VALUE entries without overwriting variables already in the process."""
    if not path.exists():
        return
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip("\"'")
        if key:
            os.environ.setdefault(key, value)


_load_env_file()
# Kept for structural compatibility with a real weather service. The mock never uses it.
OPENWEATHER_API_KEY = os.getenv("OPENWEATHER_API_KEY", "")
WEATHER_POLL_INTERVAL_MINUTES = max(1, int(os.getenv("WEATHER_POLL_INTERVAL_MINUTES", "60")))
