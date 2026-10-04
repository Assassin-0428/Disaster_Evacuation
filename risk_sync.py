"""
Bridges live district risk (weather_service) to the routing graph
(road_edges.risk_weight) and to connected frontend clients (WebSocket).

Each road_node is tagged with the district it belongs to (set by
db/seed_road_network.py). Whenever we refresh a district's combined
flood+cyclone risk, every edge touching that district's nodes gets its
risk_weight updated — so A*/Dijkstra routing (routing_engine.py) starts
preferring roads away from whichever district is currently worst-hit,
automatically, without any change to the routing algorithms themselves.
"""
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.weather_service import update_all_districts_combined_all
from app.websocket_manager import manager

# impact_level -> risk_weight multiplier used by A*/Dijkstra edge costs.
# 1.0 = safe/normal road. Higher = increasingly penalized (but never
# fully removed — is_closed is the hard "don't use this road" switch,
# reserved for manually/admin-confirmed closures).
IMPACT_TO_RISK_WEIGHT = {
    "Low": 1.0,
    "Moderate": 2.5,
    "High": 5.0,
    "Severe": 10.0,
}


def apply_district_risk_to_roads(db: Session, district_impact: dict[str, str]) -> dict:
    """
    district_impact: {"Puri": "High", "Kendrapara": "Severe", ...}

    Recomputes risk_weight for every road_edge from scratch each call
    (not accumulated across calls, so risk correctly goes back down
    when conditions improve). An edge whose two endpoint nodes belong
    to different districts (a hub-to-hub backbone edge) takes the
    WORSE of the two districts' current risk. Edges with a district
    not present in district_impact (e.g. a failed weather fetch) fall
    back to risk_weight 1.0 rather than being left stale.
    """
    if not district_impact:
        return {"edges_touched": 0, "by_district": {}}

    weight_rows = [
        {"district": d, "weight": IMPACT_TO_RISK_WEIGHT.get(level, 1.0)}
        for d, level in district_impact.items()
    ]

    result = db.execute(text("""
        WITH district_weights (district, weight) AS (
            SELECT * FROM unnest(
                CAST(:districts AS TEXT[]),
                CAST(:weights AS FLOAT[])
            )
        ),
        edge_max_weight AS (
            SELECT re.id AS edge_id,
                   GREATEST(
                       COALESCE(w1.weight, 1.0),
                       COALESCE(w2.weight, 1.0)
                   ) AS new_weight
            FROM road_edges re
            JOIN road_nodes n1 ON re.from_node = n1.id
            JOIN road_nodes n2 ON re.to_node = n2.id
            LEFT JOIN district_weights w1 ON w1.district = n1.district
            LEFT JOIN district_weights w2 ON w2.district = n2.district
        )
        UPDATE road_edges
        SET risk_weight = edge_max_weight.new_weight, last_updated = now()
        FROM edge_max_weight
        WHERE road_edges.id = edge_max_weight.edge_id
        RETURNING road_edges.id
    """), {
        "districts": [r["district"] for r in weight_rows],
        "weights": [r["weight"] for r in weight_rows],
    })
    updated_edges = len(result.fetchall())
    db.commit()

    return {
        "edges_touched": updated_edges,
        "by_district": {d: IMPACT_TO_RISK_WEIGHT.get(level, 1.0) for d, level in district_impact.items()},
    }


def reset_all_road_risk(db: Session) -> dict:
    """Resets every non-closed road edge back to risk_weight 1.0 (safe)."""
    result = db.execute(text("""
        UPDATE road_edges SET risk_weight = 1.0, last_updated = now()
        RETURNING id
    """))
    count = len(result.fetchall())
    db.commit()
    return {"edges_reset": count}


async def refresh_all_risk_and_broadcast() -> dict:
    """
    The one function both the manual admin "refresh now" endpoint and
    the background scheduler call: pulls live combined flood+cyclone
    risk for every tracked district, updates road_edges accordingly,
    and pushes the new picture to every connected WebSocket client so
    the frontend can redraw road risk coloring without polling.
    """
    combined_results = await update_all_districts_combined_all()

    district_impact = {
        r["district"]: r["overall_impact_level"]
        for r in combined_results
        if "overall_impact_level" in r
    }

    db = SessionLocal()
    try:
        summary = apply_district_risk_to_roads(db, district_impact)
    finally:
        db.close()

    payload = {
        "type": "risk_updated",
        "data": {
            "districts": combined_results,
            "roads_updated": summary,
        },
    }
    await manager.broadcast(payload)

    return payload["data"]
