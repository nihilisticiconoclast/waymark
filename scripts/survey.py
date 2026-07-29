#!/usr/bin/env python3
"""
Stage 1: SURVEY. Deterministic. No model, no API key.

Pulls path geometry and POIs from OpenStreetMap via Overpass, assembles a closed loop in the
requested distance band, samples elevation, and writes a survey payload that is the ONLY
thing the authoring stage is allowed to see.

    python scripts/survey.py --target haresfield-beacon
    python scripts/survey.py --next          # highest-priority unsurveyed entry in queue.yml

Nothing in this file may call a language model. If you find yourself wanting to, the answer
is a better Overpass query.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path

import networkx as nx
import requests
import yaml

ROOT = Path(__file__).resolve().parent.parent
QUEUE = ROOT / "data" / "queue.yml"
OUT_DIR = ROOT / "data" / "surveys"
CACHE_DIR = OUT_DIR / ".cache"

# Overpass etiquette asks callers to identify themselves, and the main instance enforces it:
# a default `python-requests/2.x` User-Agent is answered with 406 Not Acceptable, which reads
# like a malformed query and is not. Anything descriptive with a contact URL is accepted.
USER_AGENT = "waymark/0.1 (+https://github.com/nihilisticiconoclast/waymark)"

# Mirrors, tried in order. The main instance is the busiest and the first to refuse a runner
# on a shared IP; the others run the same software over the same planet file.
OVERPASS_ENDPOINTS = [
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
]
ELEVATION = "https://api.opentopodata.org/v1/eudem25m"

# Designations that confer a public right of way in England and Wales. See docs/DATA.md.
# `highway=path` is deliberately absent — a mapped path is not a right of way.
PROW = (
    "public_footpath|public_bridleway|restricted_byway|byway_open_to_all_traffic"
)

WAYS_QL = """
[out:json][timeout:120];
(
  way["designation"~"^({prow})$"]({bbox});
  way["highway"~"^(footway|path|bridleway|track|steps|cycleway)$"]({bbox});
  way["highway"~"^(residential|unclassified|service|living_street)$"]["foot"!~"^(no|private)$"]({bbox});
);
out geom;
"""

POI_QL = """
[out:json][timeout:90];
(
  nwr["amenity"="parking"]({bbox});
  node["amenity"="toilets"]({bbox});
  nwr["amenity"~"^(pub|cafe|restaurant)$"]({bbox});
  nwr["shop"="convenience"]({bbox});
  nwr["operator"="National Trust"]({bbox});
  nwr["operator:wikidata"="Q333515"]({bbox});
  nwr["designation"="access_land"]({bbox});
  node["man_made"="survey_point"]({bbox});
  node["natural"="peak"]({bbox});
  node["tourism"="viewpoint"]({bbox});
  node["highway"="bus_stop"]({bbox});
  node["railway"="station"]({bbox});
);
out center tags;
"""

HAZARD_QL = """
[out:json][timeout:90];
(
  way["highway"~"^(motorway|trunk|primary)$"]({bbox});
  node["railway"="level_crossing"]({bbox});
  way["ford"="yes"]({bbox});
  node["ford"="yes"]({bbox});
  way["tidal"="yes"]({bbox});
);
out geom tags;
"""

SURFACE_CLASS = {
    "asphalt": "sealed", "concrete": "sealed", "paved": "sealed", "paving_stones": "sealed",
    "chipseal": "sealed", "sett": "sealed",
    "compacted": "firm", "fine_gravel": "firm", "gravel": "firm", "pebblestone": "firm",
    "limestone": "firm", "unpaved": "firm",
    "ground": "soft", "dirt": "soft", "earth": "soft", "grass": "soft", "mud": "soft",
    "sand": "soft", "woodchips": "soft",
}


# --------------------------------------------------------------------------- geodesy

def haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Great-circle distance in metres. (lat, lon) pairs."""
    R = 6_371_000.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp = p2 - p1
    dl = math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def bearing_deg(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Initial bearing from a to b, degrees clockwise from true north."""
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def bbox_around(lat: float, lon: float, radius_km: float) -> str:
    dlat = radius_km / 111.0
    dlon = radius_km / (111.0 * math.cos(math.radians(lat)))
    return f"{lat - dlat},{lon - dlon},{lat + dlat},{lon + dlon}"


# --------------------------------------------------------------------------- overpass

def overpass(query: str, cache_key: str) -> dict:
    """Query Overpass with on-disk caching. Never called from the site at runtime."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{cache_key}.json"
    if cached.exists():
        return json.loads(cached.read_text())

    headers = {"User-Agent": USER_AGENT}
    problems = []
    for endpoint in OVERPASS_ENDPOINTS:
        for attempt in range(3):
            try:
                r = requests.post(endpoint, data={"data": query},
                                  headers=headers, timeout=180)
            except requests.RequestException as e:
                problems.append(f"{endpoint}: {e}")
                break
            if r.status_code == 200:
                cached.write_text(r.text)
                return r.json()
            if r.status_code in (429, 504):
                wait = 15 * (attempt + 1)
                print(f"  {endpoint} {r.status_code}, backing off {wait}s")
                time.sleep(wait)
                continue
            problems.append(f"{endpoint}: {r.status_code} {r.reason}")
            break                       # not a rate limit — a different mirror may do better
        else:
            problems.append(f"{endpoint}: rate limited after 3 attempts")
        print(f"  {endpoint} did not answer; trying the next mirror")

    raise RuntimeError(
        "Every Overpass mirror refused:\n  " + "\n  ".join(problems) +
        "\nThis is usually load rather than a bad query. Try again later, or self-host."
    )


# --------------------------------------------------------------------------- assembly

def build_graph(ways: list[dict]) -> nx.Graph:
    """
    Node key is a rounded (lat, lon) tuple — ~1 m precision. Rounding is how ways that share
    an endpoint get joined; loosen it and you connect things that aren't connected on the
    ground, which is the worst possible bug in this file.
    """
    G = nx.Graph()
    for w in ways:
        geom = w.get("geometry") or []
        tags = w.get("tags", {})
        for a, b in zip(geom, geom[1:]):
            na = (round(a["lat"], 5), round(a["lon"], 5))
            nb = (round(b["lat"], 5), round(b["lon"], 5))
            if na == nb:
                continue
            G.add_edge(na, nb, length=haversine_m(na, nb), tags=tags, osm_id=f"way/{w['id']}")
    return G


def find_loop(G: nx.Graph, anchor: tuple[float, float], band_km: tuple[float, float]):
    """
    Loop assembly heuristic.

    Naive shortest-path returns out-and-backs, which are not walks. This instead: pick a
    start node near the anchor, walk outward to a set of candidate "far" nodes at roughly
    a quarter of the target distance, then find a return path that shares as few edges as
    possible with the outward leg. Score candidates on total length within band and on edge
    disjointness, and take the best.

    This is the weakest part of the pipeline and the right place to spend effort. Improve
    it here rather than filtering bad loops downstream.
    """
    lo_m, hi_m = band_km[0] * 1000, band_km[1] * 1000
    target = (lo_m + hi_m) / 2

    if not G.nodes:
        return None
    start = min(G.nodes, key=lambda n: haversine_m(n, anchor))

    lengths = nx.single_source_dijkstra_path_length(G, start, cutoff=target * 0.6, weight="length")
    far = [n for n, d in lengths.items() if target * 0.20 < d < target * 0.35]
    if not far:
        return None

    best, best_score = None, -1.0
    for mid in far[:200]:
        try:
            out = nx.shortest_path(G, start, mid, weight="length")
        except nx.NetworkXNoPath:
            continue
        out_edges = {frozenset(e) for e in zip(out, out[1:])}

        H = G.copy()
        for u, v in zip(out, out[1:]):
            if H.has_edge(u, v):
                H[u][v]["length"] *= 6.0          # penalise, don't forbid — cul-de-sacs exist
        try:
            back = nx.shortest_path(H, mid, start, weight="length")
        except nx.NetworkXNoPath:
            continue

        loop = out + back[1:]
        total = sum(G[u][v]["length"] for u, v in zip(loop, loop[1:]) if G.has_edge(u, v))
        if not (lo_m <= total <= hi_m):
            continue

        back_edges = {frozenset(e) for e in zip(back, back[1:])}
        overlap = len(out_edges & back_edges) / max(len(out_edges), 1)
        score = (1 - overlap) - abs(total - target) / target
        if score > best_score:
            best, best_score = loop, score

    return best


# --------------------------------------------------------------------------- attributes

def summarise_route(G: nx.Graph, loop: list) -> dict:
    """Roll up designation, surface and named features along the assembled loop."""
    segments: dict[str, float] = {}
    surface: dict[str, float] = {"sealed": 0.0, "firm": 0.0, "soft": 0.0, "untagged": 0.0}
    names: set[str] = set()
    total = 0.0

    for u, v in zip(loop, loop[1:]):
        if not G.has_edge(u, v):
            continue
        e = G[u][v]
        tags, ln = e["tags"], e["length"]
        total += ln

        des = tags.get("designation")
        if des in PROW.split("|"):
            key = des
        elif tags.get("designation") == "access_land" or tags.get("access") == "yes":
            key = "access_land"
        elif tags.get("foot") == "permissive" or tags.get("access") == "permissive":
            key = "permissive"
        elif tags.get("highway") in ("residential", "unclassified", "service", "living_street"):
            key = "highway_with_footway" if tags.get("sidewalk") else "unknown"
        else:
            key = "unknown"
        segments[key] = segments.get(key, 0.0) + ln

        surface[SURFACE_CLASS.get(tags.get("surface", ""), "untagged")] += ln

        if tags.get("name"):
            names.add(tags["name"])

    by_right = sum(
        v for k, v in segments.items()
        if k in PROW.split("|") + ["access_land"]
    )
    return {
        "total_m": total,
        "segments": [{"designation": k, "length_m": round(v, 1), "prow_ref": None}
                     for k, v in sorted(segments.items(), key=lambda x: -x[1])],
        "by_right_pct": round(100 * by_right / total, 1) if total else 0.0,
        "surface_mix": {f"{k}_pct": round(100 * v / total, 1) if total else 0.0
                        for k, v in surface.items()},
        "named_features": sorted(names),
    }


def sample_elevation(coords: list[tuple[float, float]], cache_key: str) -> list[list[float]]:
    """
    Elevation profile, batched 100 points per request per the public opentopodata limit.

    Cached on disk like the Overpass calls. The public instance allows one call a second
    and a thousand a day; a re-run of a survey that only changed the loop heuristic should
    not spend that budget again, and CI should not depend on the endpoint being up.

    For anything beyond casual use, download OS Terrain 50 (OGL) once and sample locally —
    it is better data over GB and it removes the network dependency altogether.
    """
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    cached = CACHE_DIR / f"{cache_key}-elevation.json"
    if cached.exists():
        return json.loads(cached.read_text())

    profile, cum = [], 0.0
    step = max(1, len(coords) // 300)
    pts = coords[::step]
    for i in range(0, len(pts), 100):
        chunk = pts[i:i + 100]
        locs = "|".join(f"{lat},{lon}" for lat, lon in chunk)
        try:
            r = requests.get(ELEVATION, params={"locations": locs},
                             headers={"User-Agent": USER_AGENT}, timeout=60)
            r.raise_for_status()
        except requests.RequestException as e:
            # The elevation service is a shared public instance with a daily cap, and it is
            # the least important thing in the payload. Losing a whole survey — the route,
            # the designations, the amenities, all of it — because a DEM lookup was rate
            # limited is the wrong trade. The record reports no ascent rather than a guess,
            # which the write-up then has to be honest about.
            print(f"  elevation unavailable ({e}); continuing without a profile")
            return []
        for j, res in enumerate(r.json().get("results", [])):
            idx = i + j
            if idx > 0:
                cum += haversine_m(pts[idx - 1], pts[idx])
            profile.append([round(cum / 1000, 3), res.get("elevation")])
        time.sleep(1.1)                                    # public instance: 1 call/sec

    profile = [p for p in profile if p[1] is not None]
    cached.write_text(json.dumps(profile))
    return profile


def ascent_descent(profile: list[list[float]], threshold: float = 3.0) -> tuple[float, float]:
    """Threshold suppresses DEM noise. Without it a flat towpath 'climbs' 40 m."""
    up = down = 0.0
    anchor = profile[0][1] if profile else 0.0
    for _, e in profile:
        d = e - anchor
        if abs(d) >= threshold:
            (up := up + d) if d > 0 else (down := down - d)
            anchor = e
    return round(up), round(down)


def max_sustained_gradient(profile: list[list[float]], window_m: float = 200.0) -> float | None:
    best = None
    for i, (d0, e0) in enumerate(profile):
        for d1, e1 in profile[i + 1:]:
            run = (d1 - d0) * 1000
            if run < window_m:
                continue
            g = abs(e1 - e0) / run * 100
            best = g if best is None else max(best, g)
            break
    return round(best, 1) if best is not None else None


# --------------------------------------------------------------------------- main

def survey(target: dict, origin: dict) -> dict:
    slug = target["slug"]
    lat, lon = target["centre"]
    bbox = bbox_around(lat, lon, target["radius_km"])
    print(f"surveying {slug} …")

    ways = overpass(WAYS_QL.format(prow=PROW, bbox=bbox), f"{slug}-ways")["elements"]
    pois = overpass(POI_QL.format(bbox=bbox), f"{slug}-pois")["elements"]
    hazards_raw = overpass(HAZARD_QL.format(bbox=bbox), f"{slug}-hazards")["elements"]
    print(f"  {len(ways)} ways, {len(pois)} pois")

    G = build_graph(ways)
    loop = find_loop(G, (lat, lon), tuple(target["distance_band_km"]))
    if loop is None:
        raise SystemExit(
            f"No loop found for {slug} in {target['distance_band_km']} km. "
            "Widen distance_band_km or radius_km in data/queue.yml, or the path density here "
            "is genuinely too low and the target should be dropped."
        )

    attrs = summarise_route(G, loop)
    profile = sample_elevation(loop, slug)
    up, down = ascent_descent(profile)
    start = loop[0]

    # POIs are attached only if genuinely near the route. Distance is computed, never guessed.
    #
    # Overpass returns nodes with lat/lon, ways and relations with `center` under `out center`
    # and a `geometry` array under `out geom`. All three have to be understood here: the
    # hazard query uses `out geom`, so an earlier lat/lon-only version silently dropped every
    # ford and tidal section that happened to be mapped as a way rather than a node — a hazard
    # check that misses hazards is worse than no check.
    def points_of(p) -> list[tuple[float, float]]:
        if p.get("lat") is not None:
            return [(p["lat"], p["lon"])]
        if p.get("center"):
            return [(p["center"]["lat"], p["center"]["lon"])]
        return [(g["lat"], g["lon"]) for g in p.get("geometry") or []]

    def near(p, limit_m):
        pts = points_of(p)
        if not pts:
            return None
        d = min(haversine_m(pt, n) for pt in pts for n in loop)
        return round(d) if d <= limit_m else None

    car_parks, refreshment = [], []
    toilets = nt = trig = False
    viewpoints = 0
    for p in pois:
        t = p.get("tags", {})
        if t.get("amenity") == "parking":
            if (d := near(p, 400)) is not None:
                car_parks.append({
                    "name": t.get("name"), "operator": t.get("operator"),
                    "fee": {"yes": True, "no": False}.get(t.get("fee")),
                    "capacity": int(t["capacity"]) if t.get("capacity", "").isdigit() else None,
                    "distance_from_start_m": round(
                        min(haversine_m(pt, start) for pt in points_of(p))),
                    "osm_id": f"{p['type']}/{p['id']}",
                })
        elif t.get("amenity") in ("pub", "cafe", "restaurant") and t.get("name"):
            if (d := near(p, 300)) is not None:
                refreshment.append({
                    "name": t["name"], "type": t["amenity"],
                    "vegan": t.get("diet:vegan", "unknown"),
                    "distance_from_route_m": d,
                    "osm_id": f"{p['type']}/{p['id']}",
                })
        elif t.get("amenity") == "toilets" and near(p, 300) is not None:
            toilets = True
        elif t.get("man_made") == "survey_point" and near(p, 100) is not None:
            trig = True
        elif t.get("tourism") == "viewpoint" and near(p, 150) is not None:
            viewpoints += 1
        if t.get("operator") == "National Trust" or t.get("operator:wikidata") == "Q333515":
            nt = True

    hazards = []
    for h in hazards_raw:
        t = h.get("tags", {})
        if t.get("highway") in ("motorway", "trunk", "primary"):
            geom = h.get("geometry") or []
            crossing = any(
                min(haversine_m((g["lat"], g["lon"]), n) for n in loop) < 15 for g in geom
            )
            if crossing and not t.get("footway") and not t.get("sidewalk"):
                hazards.append({
                    "kind": "major_road_crossing",
                    "detail": f"Route meets a {t['highway']} road with no mapped footway or crossing.",
                    "osm_id": f"way/{h['id']}",
                })
        elif t.get("ford") == "yes" and near(h, 30) is not None:
            hazards.append({"kind": "ford", "detail": "Ford on or adjacent to the route.",
                            "osm_id": f"{h['type']}/{h['id']}"})
        elif t.get("railway") == "level_crossing" and near(h, 30) is not None:
            hazards.append({"kind": "level_crossing", "detail": "Level crossing on the route.",
                            "osm_id": f"node/{h['id']}"})
        # The query asks for tidal ways and the schema has a `tidal` kind, so the result has
        # to be read back out. Left unhandled, the survey collected the evidence and threw it
        # away, and the disclosure check downstream had nothing to enforce.
        elif t.get("tidal") == "yes" and near(h, 30) is not None:
            hazards.append({"kind": "tidal",
                            "detail": "Route runs along or across a tidal section.",
                            "osm_id": f"{h['type']}/{h['id']}"})

    # Names of nearby POIs join the allowlist — this is how a pub becomes mentionable.
    named = set(attrs["named_features"])
    named.update(cp["name"] for cp in car_parks if cp["name"])
    named.update(r["name"] for r in refreshment)
    named.add(target["name"])

    payload = {
        "slug": slug,
        "name": target["name"],
        "geometry": {
            "start": {"lat": start[0], "lon": start[1], "osgb_grid_ref": None, "what3words": None},
            "route": {"type": "LineString", "coordinates": [[n[1], n[0]] for n in loop]},
            "closed": haversine_m(loop[0], loop[-1]) < 150,
            "bearing_from_origin_deg": round(bearing_deg((origin["lat"], origin["lon"]), start), 1),
            "drive_km_from_origin": None,
            "drive_minutes_from_origin": None,
        },
        "facts": {
            "distance_km": round(attrs["total_m"] / 1000, 2),
            "ascent_m": up,
            "descent_m": down,
            "max_elevation_m": max((e for _, e in profile), default=None),
            "min_elevation_m": min((e for _, e in profile), default=None),
            "max_sustained_gradient_pct": max_sustained_gradient(profile),
            "elevation_profile": profile,
            "access": {"by_right_pct": attrs["by_right_pct"], "segments": attrs["segments"]},
            "surface_mix": attrs["surface_mix"],
            "amenities": {
                "car_park": car_parks, "toilets": toilets, "refreshment": refreshment,
                "national_trust": nt, "trig_point": trig, "viewpoints": viewpoints,
                "public_transport": {"nearest_stop_m": None, "nearest_station_m": None},
                "dogs": "unknown",
            },
            "hazards": hazards,
            "named_features": sorted(named),
        },
        "provenance": {
            "method": "survey+author",
            "surveyed_at": datetime.now(timezone.utc).isoformat(),
            "overpass_query_sha": hashlib.sha256(
                (WAYS_QL + POI_QL + HAZARD_QL).encode()).hexdigest()[:12],
            "attribution": [
                "Route and feature data © OpenStreetMap contributors, ODbL",
                "Elevation derived from EU-DEM via opentopodata",
            ],
        },
    }

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{slug}.json"
    out.write_text(json.dumps(payload, indent=2))
    print(f"  → {out}  ({payload['facts']['distance_km']} km, {up} m ascent, "
          f"{attrs['by_right_pct']}% by right)")
    return payload


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--target", help="slug from data/queue.yml")
    ap.add_argument("--next", action="store_true", help="highest-priority unsurveyed target")
    ap.add_argument("--band", help="override distance_band_km, e.g. 6:14 — for retrying a "
                                   "target the assembler couldn't fit without editing the queue")
    ap.add_argument("--radius-km", type=float, help="override the search radius")
    args = ap.parse_args()

    q = yaml.safe_load(QUEUE.read_text())
    origin = q["origin"]

    if args.next:
        done = {p.stem for p in OUT_DIR.glob("*.json")}
        remaining = [t for t in q["targets"] if t["slug"] not in done]
        if not remaining:
            print("Queue exhausted. Add targets to data/queue.yml.")
            return
        target = min(remaining, key=lambda t: t["priority"])
    elif args.target:
        target = next(t for t in q["targets"] if t["slug"] == args.target)
    else:
        ap.error("pass --target <slug> or --next")

    if args.band:
        lo, hi = args.band.split(":")
        target = {**target, "distance_band_km": [float(lo), float(hi)]}
    if args.radius_km:
        target = {**target, "radius_km": args.radius_km}

    survey(target, origin)


if __name__ == "__main__":
    main()
