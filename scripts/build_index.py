#!/usr/bin/env python3
"""
Stage 4: BUILD. data/walks/*.json → site/data/walks.json

Drops the elevation profile and full route geometry into a per-walk file so the index stays
small enough to fetch on a phone on a hill with one bar. The index carries only what the
filters need; detail loads on selection.

Also emits site/data/queue.json from data/queue.yml. Until the first survey runs there are
no walks, and a map with nothing on it and no explanation reads as a broken site rather than
an empty one. The queue is real, hand-authored data about what is coming, so showing it is
honest — provided the site never lets a queued area be mistaken for a walk. It carries no
route, no distance, no ascent and no confidence, because none of those exist yet.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
WALKS = ROOT / "data" / "walks"
SURVEYS = ROOT / "data" / "surveys"
QUEUE = ROOT / "data" / "queue.yml"
OUT = ROOT / "site" / "data"

ORIGIN = (51.7447, -2.2166)          # Stroud, the Cross. Keep in step with site/app.js.


def haversine_km(a, b):
    R = 6371.0
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dp, dl = p2 - p1, math.radians(b[1] - a[1])
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


def bearing(a, b):
    p1, p2 = math.radians(a[0]), math.radians(b[0])
    dl = math.radians(b[1] - a[1])
    y = math.sin(dl) * math.cos(p2)
    x = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def build_queue(published: set[str]) -> dict:
    """
    The survey queue, as the site sees it. `centre` is a search anchor and not a route start
    — survey.py finds the start — so the site labels these as areas, never as walks.
    """
    q = yaml.safe_load(QUEUE.read_text())
    surveyed = {p.stem for p in SURVEYS.glob("*.json")}

    targets = []
    for t in q["targets"]:
        if t["slug"] in published:
            continue                       # it is a walk now; the walk index carries it
        centre = (t["centre"][0], t["centre"][1])
        targets.append({
            "slug": t["slug"], "name": t["name"],
            "lat": centre[0], "lon": centre[1],
            "crow_km": round(haversine_km(ORIGIN, centre), 1),
            "bearing": round(bearing(ORIGIN, centre)),
            "band_km": t["distance_band_km"],
            "priority": t["priority"],
            "surveyed": t["slug"] in surveyed,
            "notes": t.get("notes"),
        })

    targets.sort(key=lambda t: t["priority"])
    return {"count": len(targets),
            "surveyed": sum(1 for t in targets if t["surveyed"]),
            "targets": targets}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "walks").mkdir(exist_ok=True)

    index = []
    for p in sorted(WALKS.glob("*.json")):
        r = json.loads(p.read_text())
        if r.get("status") != "published":
            print(f"skip {p.name}: status={r.get('status')}")
            continue

        start = (r["geometry"]["start"]["lat"], r["geometry"]["start"]["lon"])
        f, a = r["facts"], r["facts"].get("amenities", {})

        index.append({
            "id": r["id"], "slug": r["slug"], "name": r["name"],
            "lat": start[0], "lon": start[1],
            "crow_km": round(haversine_km(ORIGIN, start), 1),
            "bearing": round(bearing(ORIGIN, start)),
            "distance_km": f["distance_km"],
            "ascent_m": f["ascent_m"],
            "gradient_pct": f.get("max_sustained_gradient_pct"),
            "soft_pct": f["surface_mix"].get("soft_pct", 0),
            "sealed_pct": f["surface_mix"].get("sealed_pct", 0),
            "by_right_pct": f["access"]["by_right_pct"],
            "closed": r["geometry"]["closed"],
            "nt": a.get("national_trust", False),
            "car_park": bool(a.get("car_park")),
            "car_park_free": any(cp.get("fee") is False for cp in a.get("car_park", [])),
            "toilets": a.get("toilets", False),
            "vegan": any(x.get("vegan") in ("yes", "only") for x in a.get("refreshment", [])),
            "refreshment": bool(a.get("refreshment")),
            "trig": a.get("trig_point", False),
            "viewpoints": a.get("viewpoints", 0),
            "transit": (a.get("public_transport", {}).get("nearest_stop_m") or 9e9) < 800,
            "hazards": [h["kind"] for h in f.get("hazards", [])],
            "ratings": r.get("ratings", {}),
            "runnable": r["editorial"].get("runnable"),
            "best_months": r["editorial"].get("best_months", []),
            "summary": r["editorial"]["summary"],
            "confidence": r["confidence"]["navigable"],
            "resolved": (r["confidence"].get("resolved") or {}).get("outcome"),
        })

        (OUT / "walks" / f"{r['slug']}.json").write_text(json.dumps({
            "slug": r["slug"], "name": r["name"],
            "geometry": r["geometry"], "facts": f,
            "editorial": r["editorial"], "confidence": r["confidence"],
            "provenance": r["provenance"],
        }, ensure_ascii=False))

    (OUT / "walks.json").write_text(json.dumps({
        "origin": {"lat": ORIGIN[0], "lon": ORIGIN[1], "name": "Stroud"},
        "count": len(index),
        "walks": index,
    }, ensure_ascii=False, indent=1))
    print(f"→ site/data/walks.json  ({len(index)} published)")

    queue = build_queue({w["slug"] for w in index})
    (OUT / "queue.json").write_text(json.dumps(queue, ensure_ascii=False, indent=1))
    print(f"→ site/data/queue.json  ({queue['count']} awaiting, "
          f"{queue['surveyed']} already surveyed)")


if __name__ == "__main__":
    main()
