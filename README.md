# Waymark

A full-bleed Ordnance Survey map of curated walks, centred on Stroud, filtered the way you
actually choose a walk: by how far you'll drive, in which direction, what's underfoot, how
much climbing, and whether there's a car park and a toilet at the end of it.

Walks are not scraped. They are **surveyed** from open geospatial data, then **written up**
by Claude under constraints that forbid it from naming anything the survey didn't find.
Every walk carries a stated probability that it is navigable as described, and that
probability is scored against reality when you walk it.

---

## Status

Wired up and deploying; **no walks published**. The site is live and the pipeline, the gate
and the calibration all run. What is missing is data, and only one thing produces it.

The map therefore shows the **survey queue** — the twenty areas in `data/queue.yml`, drawn as
hollow markers, filterable by the dial and by nothing else, because a queued area has no
distance, no ascent and no surface for the other filters to read. They are search anchors, not
routes. Each becomes a walk the first time it is surveyed, written up and passed by the
validator, and it leaves the queue layer at that point.

`data/walks/0001-haresfield-beacon.json` is a **seed** record that demonstrates the schema.
Its geometry is seven hand-placed points that follow nothing on the ground, and the validator
refuses to publish it — it reports `SEED` rather than `FAIL`, so it does not redden every
pull request while it sits there.

### Next

1. **Survey the first area.** `python scripts/survey.py --next` takes Haresfield Beacon, the
   highest-priority entry. It needs no key. It does need `overpass-api.de`, and it is the
   only step in the whole system that cannot run from a locked-down environment. Expect to
   spend the first attempt or two widening `distance_band_km` — the loop assembler is the
   part most likely to come back empty, and the honest failure is a `SystemExit` telling you
   so rather than a forced bad loop.
2. **Write it up.** `ANTHROPIC_API_KEY=… python scripts/author.py --survey
   data/surveys/haresfield-beacon.json`.
3. **Read the write-up against the survey payload**, not on its own. The prose is designed to
   be plausible; that is exactly what makes it worth checking. Then
   `python scripts/validate.py data/walks/*.json`.
4. **Turn the weekly job on.** `.github/workflows/new-walk.yml` needs `ANTHROPIC_API_KEY` in
   repository secrets; until then it will fail every Sunday at 06:00 UTC. Nothing else is
   required — `ci.yml` and `pages.yml` are already running.
5. **Walk one, then resolve it.** The calibration panel stays empty until the ledger has
   entries, and the Brier decomposition means nothing below about n=10. This is the slow
   part of the system and it is supposed to be: the rate limit is how fast you can walk.

Optional, and only when you want the real 1:25 000 Explorer sheet rather than OpenTopoMap:
set `OS_API_KEY` in secrets and `WAYMARK_BASEMAP` in repository variables. See *Basemap*.

---

## The problem this repo is designed around

The obvious way to build this is to ask an LLM for "ten good walks near Stroud" and render
the answer. That produces plausible, confident, unwalkable routes: footpath junctions that
don't exist, pubs that closed in 2019, a "gentle riverside stretch" that is a ploughed field
with a bull in it. Walking directions are safety-adjacent. Confabulation here is not a
cosmetic failure.

So the pipeline splits hard along a provenance line:

| Layer | Source | Claude's role |
|---|---|---|
| Route geometry, rights of way, surface, gradient | OpenStreetMap via Overpass; elevation from a DEM | **None.** Claude never emits a coordinate. |
| Car parks, toilets, pubs, National Trust land, trig points | OpenStreetMap | **None.** Claude may only reference POIs present in the survey payload. |
| Description, character, what to notice, why it's worth doing | Claude | **All of it** — constrained to the survey payload. |
| Stated confidence that the route works as written | Claude | Calibrated, then scored. |

`scripts/validate.py` enforces the line mechanically: any proper noun in the prose that does
not appear in the survey payload or the gazetteer fails the build.

See [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md).

---

## Beating the Bounds

The old parish custom: once a year you walk the boundary to check the boundary is where the
record says it is. That's the feature.

Every published walk carries `confidence.navigable` — Claude's stated probability that a
competent walker with the map can follow the route as written without backtracking or
trespass. When you actually walk it, you resolve it: open a **Resolve a walk** issue, mark it
`walked_as_described`, `diverged`, or `failed`, and a workflow appends the outcome to
`data/ledger.json`.

`scripts/brier.py` then computes a Brier score over resolved walks with a Murphy
decomposition (reliability − resolution + uncertainty), and the site shows a small
calibration panel. Over time this tells you the one thing you actually want to know: how much
to trust a Waymark write-up you haven't verified.

It reuses the scoring conventions from Dead Reckoning. Same idea, different question class.

---

## The bearing dial

Store finders give you a radius slider. Nobody chooses a walk that way. You choose it as
"somewhere about forty minutes away, and not towards Gloucester today."

So the distance-from-Stroud control is a dial: drag the arc to set a bearing sector, drag the
rim to set an inner and outer radius. One gesture, two dimensions. The origin is the Cross in
Stroud (51.7447 N, 2.2166 W); change it in `site/app.js` → `ORIGIN`.

---

## Quick start

```bash
git clone <this repo> && cd waymark
python -m venv .venv && source .venv/bin/activate
pip install -r scripts/requirements.txt

# 1. Survey a target area (no LLM, no API key needed)
python scripts/survey.py --target haresfield-beacon

# 2. Write it up (needs ANTHROPIC_API_KEY)
python scripts/author.py --survey data/surveys/haresfield-beacon.json

# 3. Gate it
python scripts/validate.py data/walks/*.json

# 4. Build the site payload and serve
python scripts/build_index.py
python -m http.server 8000 --directory site
```

The invariants the gate exists to enforce are executable, and they need no key, no network
and no survey:

```bash
python -m unittest discover -s tests -v
```

The site runs with **no API key at all** on an OpenTopoMap basemap. To get the real 1:25 000
Explorer look, see *Basemap* below.

---

## Basemap

Three profiles in `site/app.js` → `BASEMAP_PROFILES`:

| Profile | Look | Projection | Key |
|---|---|---|---|
| `opentopo` | Generic topographic | EPSG:3857 | none — **default** |
| `os-outdoor` | OS Outdoor house style | EPSG:3857 | OS Data Hub, Open Data plan |
| `os-leisure` | The 1:25 000 Explorer sheet | EPSG:27700 | OS Data Hub, **Premium** plan |

Two things to know before you reach for `os-leisure`:

1. The 1:25 000 Scale Colour Raster is **Premium** OS data, not open data. It is available
   through the Data Hub's Premium plan, which carries a monthly free credit allowance —
   confirm the current allowance and terms at <https://osdatahub.os.uk/plans> before wiring
   a public site to it.
2. Leisure is published in **British National Grid only**. That's why the site uses Leaflet
   with Proj4Leaflet rather than MapLibre: MapLibre won't give you EPSG:27700 raster tiles.
   The CRS is selected per profile at init, so switching profiles switches projection.

The API key is referrer-locked in the OS Data Hub project settings and read from
`site/config.js` (gitignored; `site/config.example.js` is committed). A referrer-locked key
in client-side JS is the intended deployment pattern for this API, but it is not a secret —
don't reuse a key across projects.

---

## Data licensing

OpenStreetMap data is ODbL — attribution required, and derived geodata you publish inherits
the licence. OS Open products are under the Open Government Licence with a required
attribution string. Both are rendered in the map footer and stated per-walk in the record.
See [`docs/DATA.md`](docs/DATA.md). This is not a formality: the site republishes derived
route geometry, so the attribution is load-bearing.

---

## Repository name

`waymark`, kept — it fits the existing naming (Tunnel, Transit, Cairn, Traverse, Dead
Reckoning, Mast) and it is the word for the thing this site is about. The alternatives
considered and not taken were `trigpoint`, `perambulation` and `beating-the-bounds`; the last
of those survives as the name of the calibration feature, which is where it belongs.

---

## Aesthetic

Styling is delegated to **cuddly-lamp**'s Tunnel system, linked from its jsDelivr copy rather
than vendored, so an update there reaches this page without a commit here. Waymark ships
structure, layout and a fallback shim that keeps the site legible if the CDN is unreachable.

The token vocabulary is confirmed, not assumed: one stylesheet (`assets/tokens.css` — there is
no `base.css`) exporting unprefixed names — `--paper`, `--ink`, `--contour`, `--index`,
`--incident`, `--amber`, `--route`, `--font-display/body/data`, `--radius`, `--rule`,
`--measure`, `--step--1` … `--step-4`. Nothing in this repo redefines a colour, a typeface or
a radius. Layout spacing is the one thing cuddly-lamp does not provide, and it lives in
`site/styles.css` under a `--wm-` prefix so the boundary stays visible.

The house signature is mounted as cuddly-lamp asks: the fixed `mark` logo in the rail head,
and one seeded `doodle` placed by `placeDoodle` into a random edge slot of the rail — the map
is opaque and full-bleed, so the rail is the only gutter this page has. Wiring is documented
in `docs/ARCHITECTURE.md` → *Styling contract*.
