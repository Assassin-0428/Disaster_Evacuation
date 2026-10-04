"""Map district impact to road-risk weights and broadcast in-memory updates."""
from typing import Callable, Iterable

RISK_WEIGHTS = {0: 1.0, 1: 2.5, 2: 5.0, 3: 10.0}


class RiskStore:
    """Simple in-memory stand-in for a database, useful for a runnable demo."""
    def __init__(self):
        self._records = {}
        self._subscribers = []

    def subscribe(self, callback: Callable[[dict], None]) -> None:
        self._subscribers.append(callback)

    def upsert(self, record: dict) -> dict:
        saved = {**record, "road_risk_weight": RISK_WEIGHTS[record["impact_level"]]}
        self._records[saved["district"]] = saved
        for callback in tuple(self._subscribers):
            callback(dict(saved))
        return dict(saved)

    def all(self) -> list[dict]:
        return [dict(value) for value in self._records.values()]


def sync_impacts(records: Iterable[dict], store: RiskStore) -> list[dict]:
    """Convert, store, and broadcast each district impact record."""
    return [store.upsert(record) for record in records]
