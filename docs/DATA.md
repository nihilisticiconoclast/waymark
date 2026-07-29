# Data

## Sources

| What | Source | Licence | Notes |
|---|---|---|---|
| Paths, rights of way, POIs, land cover | OpenStreetMap via Overpass API | ODbL 1.0 | Attribution required; share-alike applies to derived geodata |
| Elevation | OS Terrain 50 (preferred) or opentopodata `eudem25m` | OGL v3 / EU-DEM terms | Terrain 50 is a one-off download; opentopodata is easier to start with |
| Basemap tiles | OS Maps API, or OpenTopoMap | OS Data Hub terms / CC-BY-SA | See README → *Basemap* |
| Editorial prose | Claude, constrained | — | Not a source of fact; see `docs/ARCHITECTURE.md` |

**Attribution strings** are rendered in the map footer and stored per-record in
`provenance.attribution`. They are load-bearing, not decorative: the site republishes route
geometry derived from OSM, which is exactly the case ODbL's share-alike provision covers.
If you ever change the geometry pipeline to mix in a non-open source, check the licence
interaction before publishing.

---

## Rights of way: the tag that matters

England and Wales record public rights of way in OSM with `designation`, not `highway`.
This distinction is the single most important thing in the whole data model.

| `designation` | Right |
|---|---|
| `public_footpath` | On foot |
| `public_bridleway` | On foot, horse, bicycle |
| `restricted_byway` | On foot, horse, bicycle, non-mechanically-propelled vehicle |
| `byway_open_to_all_traffic` | All, including motor vehicles |

`highway=path` or `highway=footway` **on its own means nothing about access.** It means
someone mapped a path. It may be a permissive route, a desire line across a field, or a
private drive. Records must classify these as `permissive` or `unknown` and say so.

Open access land carries `access=yes` with `designation=access_land`, or is mapped as a CRoW
access area. National Trust land is usually `operator=National Trust` and/or
`operator:wikidata=Q333515` — **verify the QID against Wikidata before relying on it**, and
match on both since tagging is inconsistent.

Also collected: `prow_ref` (the council's PRoW reference — useful for cross-checking against
the definitive map), `sac_scale`, `trail_visibility`, `surface`, `smoothness`, `width`.

---

## Hazards

`survey.py` flags, and the record must disclose:

- crossings of `highway=primary|trunk|motorway` without an associated `footway` or `crossing`
- `ford=yes` on the route
- level crossings (`railway=level_crossing`)
- tidal or flood-liable sections (`tidal=yes`, `flood_prone=yes`, within Severn floodplain
  polygons where available)
- `barrier` values that imply an obstacle rather than a passage

A missing hazard disclosure fails validation. This check exists because it is the one whose
failure mode is not embarrassment.

---

## The gazetteer

`data/gazetteer.txt` is a hand-maintained allowlist of proper nouns the validator will
accept in prose beyond what the survey found: local names for features, historical names,
things you know exist and OSM hasn't caught up with.

One entry per line. Comment with `#`. Adding a name is an assertion that you have verified
it — the gazetteer is the one place in the pipeline where trust is manual, so keep it small
and keep it honest.

---

## What we deliberately do not collect

Anything about private individuals, anything behind a login, and anything from a
commercial walks site. Route geometry is derived from open data or it doesn't exist. If a
walk you like isn't reproducible from OSM, the answer is to improve OSM, not to copy someone
else's GPX into this repo — their route is their work, and in most cases their licence.
