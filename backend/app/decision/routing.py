"""
Mock Routing Service.

Spec section 174 lists the Google Maps Routes API and Weather API as
pluggable *external services*. This prototype cannot reach the real
internet, so this module implements the same contract
(computeRoutes / getWeather, spec section 172-173) deterministically:
distance via the Haversine formula, ETA via a configured average speed,
and road-segment passability from our own `road_segments` table (spec's
"DisasterOps Road State Layer", section 85). Swapping this module for a
real Google Maps client requires no change to the engines that call it.
"""
import math
from datetime import datetime, timezone
from .. import config as cfg


def _age_minutes(ts):
    """Age of a road-state record in minutes, or None if unparseable."""
    if not ts:
        return None
    try:
        dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return max(0.0, (datetime.now(timezone.utc) - dt).total_seconds() / 60.0)
    except ValueError:
        return None


def haversine_km(lat1, lon1, lat2, lon2):
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlambda / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def compute_route(origin, destination, road_segment_rows):
    """
    origin/destination: dicts with latitude/longitude.
    road_segment_rows: the specific segment(s) assumed to lie on this route
                        (in a full implementation, Google's polyline would
                        be intersected against the closure layer; here the
                        seed data assigns each shelter/warehouse pair a
                        fixed segment id, which the caller passes in).

    Returns dict: distance_km, travel_minutes, segments (list of
    {id, status, passability, age_minutes}), min_passability.
    """
    distance_km = haversine_km(origin["latitude"], origin["longitude"],
                                destination["latitude"], destination["longitude"])
    travel_minutes = (distance_km / cfg.MOCK_AVERAGE_SPEED_KMH) * 60.0

    segments = []
    for seg in road_segment_rows:
        passability = cfg.ROAD_PASSABILITY.get(seg["status"], 0.35)
        segments.append({
            "id": seg["road_segment_id"],
            "status": seg["status"],
            "passability": passability,
            "source": seg["source"],
            "age_minutes": _age_minutes(seg["last_updated_at"]),
        })
    min_passability = min((s["passability"] for s in segments), default=1.0)
    any_blocked = any(s["status"] == "BLOCKED" for s in segments)

    return {
        "distance_km": distance_km,
        "distance_metres": int(distance_km * 1000),
        "travel_minutes": travel_minutes,
        "segments": segments,
        "min_passability": min_passability,
        "blocked": any_blocked,
    }
