import math
from typing import Dict, List, Optional, Tuple

import requests


# -------------------------------------------------------------------
# Police lookup configuration
# -------------------------------------------------------------------
# Multiple Overpass mirrors are used so one temporary outage does not
# make the emergency app behave as if no police stations exist.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
]

# Public OSRM demo is suitable for a prototype. For a production safety
# product, use a managed routing provider or your own OSRM instance.
OSRM_BASE_URL = "https://router.project-osrm.org"

REQUEST_HEADERS = {
    "User-Agent": "ShathiaSafetyPrototype/1.0"
}


# -------------------------------------------------------------------
# Distance helper
# -------------------------------------------------------------------
def haversine(lat1, lon1, lat2, lon2):
    """Straight-line distance between two coordinates, in metres."""
    R = 6_371_000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)

    a = (
        math.sin(dphi / 2) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


# -------------------------------------------------------------------
# OpenStreetMap / Overpass discovery
# -------------------------------------------------------------------
def _police_name(tags: Dict) -> str:
    """Return the best available human-readable police station name."""
    for key in ("name", "official_name", "name:en", "short_name", "operator"):
        value = tags.get(key)
        if value:
            return str(value).strip()
    return "Police Station"


def _discover_police_candidates(lat: float, lon: float, radius: int) -> List[Dict]:
    """
    Find police facilities around the user using OSM.

    `nwr` includes nodes, ways and relations. `out center tags` supplies a
    usable coordinate for mapped areas/relations as well as their tags.
    """
    query = f"""
    [out:json][timeout:20];
    nwr["amenity"="police"](around:{int(radius)},{lat},{lon});
    out center tags;
    """

    last_error: Optional[Exception] = None

    for endpoint in OVERPASS_ENDPOINTS:
        try:
            response = requests.post(
                endpoint,
                data={"data": query},
                headers=REQUEST_HEADERS,
                timeout=25,
            )
            response.raise_for_status()
            payload = response.json()

            candidates: List[Dict] = []
            seen = set()

            for element in payload.get("elements", []):
                plat = element.get("lat")
                plon = element.get("lon")

                if plat is None or plon is None:
                    center = element.get("center") or {}
                    plat = center.get("lat")
                    plon = center.get("lon")

                if plat is None or plon is None:
                    continue

                tags = element.get("tags") or {}
                name = _police_name(tags)

                # Deduplicate a police station that may be mapped more than once.
                dedupe_key = (
                    name.casefold(),
                    round(float(plat), 5),
                    round(float(plon), 5),
                )
                if dedupe_key in seen:
                    continue
                seen.add(dedupe_key)

                straight_distance = haversine(lat, lon, plat, plon)
                candidates.append(
                    {
                        "lat": float(plat),
                        "lon": float(plon),
                        "name": name,
                        "straight_distance": float(straight_distance),
                    }
                )

            candidates.sort(key=lambda c: c["straight_distance"])
            return candidates

        except Exception as exc:
            last_error = exc
            continue

    # Keep failure quiet in the Streamlit UI, but provide useful server logs.
    if last_error is not None:
        print(f"[Shathia] Police discovery failed: {last_error}")
    return []


# -------------------------------------------------------------------
# Road routing / ranking
# -------------------------------------------------------------------
def _pick_fastest_by_road(
    user_lat: float,
    user_lon: float,
    candidates: List[Dict],
) -> Optional[Dict]:
    """
    Pick the fastest reachable police station by road using one OSRM table
    request. This avoids selecting a station that is geographically close but
    separated by highways, rivers, fenced compounds, etc.
    """
    if not candidates:
        return None

    # Limit routing work to the closest mapped candidates. Eight is enough for
    # an emergency prototype while keeping the request small and quick.
    shortlist = candidates[:8]

    coordinates = [f"{user_lon},{user_lat}"]
    coordinates.extend(f"{c['lon']},{c['lat']}" for c in shortlist)

    destinations = ";".join(str(i) for i in range(1, len(coordinates)))
    coordinate_string = ";".join(coordinates)

    url = f"{OSRM_BASE_URL}/table/v1/driving/{coordinate_string}"

    try:
        response = requests.get(
            url,
            params={
                "sources": "0",
                "destinations": destinations,
            },
            headers=REQUEST_HEADERS,
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("code") != "Ok":
            return None

        durations_matrix = payload.get("durations") or []
        if not durations_matrix or not durations_matrix[0]:
            return None

        durations = durations_matrix[0]
        best_index = None
        best_duration = float("inf")

        for index, duration in enumerate(durations):
            if duration is None:
                continue
            if duration < best_duration:
                best_duration = float(duration)
                best_index = index

        if best_index is None:
            return None

        winner = dict(shortlist[best_index])
        winner["route_duration"] = best_duration
        return winner

    except Exception as exc:
        print(f"[Shathia] Road-time ranking unavailable; using distance fallback: {exc}")
        return None


def _get_road_distance(
    user_lat: float,
    user_lon: float,
    police_lat: float,
    police_lon: float,
) -> Optional[Tuple[float, float]]:
    """Return (road_distance_metres, route_duration_seconds) if routable."""
    url = (
        f"{OSRM_BASE_URL}/route/v1/driving/"
        f"{user_lon},{user_lat};{police_lon},{police_lat}"
    )

    try:
        response = requests.get(
            url,
            params={"overview": "false", "steps": "false"},
            headers=REQUEST_HEADERS,
            timeout=8,
        )
        response.raise_for_status()
        payload = response.json()

        if payload.get("code") != "Ok":
            return None

        routes = payload.get("routes") or []
        if not routes:
            return None

        route = routes[0]
        distance = route.get("distance")
        duration = route.get("duration")

        if distance is None:
            return None

        return float(distance), float(duration or 0.0)

    except Exception as exc:
        print(f"[Shathia] Road-distance lookup unavailable: {exc}")
        return None


# -------------------------------------------------------------------
# Public function used by app.py
# -------------------------------------------------------------------
def find_police(lat, lon, radius=5000):
    """
    Return the best nearby police station as:

        (latitude, longitude, name, approximate_distance_metres)

    Selection strategy:
      1. Discover OSM police nodes + ways + relations.
      2. Shortlist stations by geographic distance.
      3. Prefer the fastest road-reachable station using OSRM.
      4. Return road distance when routing is available.
      5. Gracefully fall back to straight-line distance if routing is down.

    This keeps the return format compatible with the existing Shathia app.
    """
    try:
        lat = float(lat)
        lon = float(lon)
        radius = int(radius)
    except (TypeError, ValueError):
        return None

    candidates = _discover_police_candidates(lat, lon, radius)
    if not candidates:
        return None

    winner = _pick_fastest_by_road(lat, lon, candidates)

    # If OSRM is unavailable, use the geographically nearest OSM result.
    if winner is None:
        winner = candidates[0]

    route_info = _get_road_distance(
        lat,
        lon,
        winner["lat"],
        winner["lon"],
    )

    if route_info is not None:
        road_distance, route_duration = route_info
        winner["road_distance"] = road_distance
        winner["route_duration"] = route_duration
        distance_for_display = road_distance
    else:
        distance_for_display = winner["straight_distance"]

    return (
        winner["lat"],
        winner["lon"],
        winner["name"],
        distance_for_display,
    )
