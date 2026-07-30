# Waymark

A full-bleed Ordnance Survey map of curated walks, centred on Stroud, filtered the way you
actually choose a walk: by how far you'll drive, in which direction, what's underfoot, how
much climbing, and whether there's a car park and a toilet at the end of it.

Walks are not scraped. They are **surveyed** from open geospatial data, then **written up**
by Claude under constraints that forbid it from naming anything the survey didn't find.
Every walk carries a stated probability that it is navigable as described, and that
probability is scored against reality when you walk it.

---

## Where the site is

<https://nihilisticiconoclast.github.io/waymark/>

**If that shows this README rather than a map, Pages is set to "Deploy from a branch".**
Under that setting GitHub runs Jekyll over the repository and renders `README.md` as the
index, while the `pages` workflow builds and deploys an artifact nothing is serving. The root
`index.html` and `.nojekyll` in this repository work around it by redirecting to `site/`, but
the fix is one dropdown — *Settings → Pages → Build and deployment → Source: **GitHub
Actions***. It matters beyond tidiness: `site/config.js` is written during the workflow and is
deliberately not committed, so under branch deployment no OS API key reaches the page.

---

## Status

Live, with **one walk on it**: Haresfield Beacon, a 5.22 km circuit with 261 m of ascent and
**not one metre of sealed surface** — seven tenths designated public footpath, the rest
National Trust open-access land. It reaches 219 m on a 215 m escarpment, so it goes over the
top rather than round the foot. Its route is drawn on the map as a line, not a pin on a start.

The other nineteen entries in `data/queue.yml` show as hollow markers: areas awaiting survey,
answering to the dial and to none of the other filters, because a queued area has no distance,
ascent or surface for them to read. Each becomes a walk the first time it is surveyed, written
up and passed by the validator, and leaves the queue layer at that point.

### How that walk was made, and how the next one is

```bash
# 1. Survey. Overpass + a DEM, no key, no model. Runs on Actions because that is where
#    the open internet is: .github/workflows/survey.yml, dispatch with a target slug.
python scripts/survey.py --target haresfield-beacon

# 2. Write. Claude reads data/surveys/<slug>.json and writes
#    data/editorial/<slug>.json, then this merges it with the surveyed facts.
python scripts/author.py --survey data/surveys/haresfield-beacon.json

# 3. Gate, build, and it is on the map.
python scripts/validate.py data/walks/*.json && python scripts/build_index.py
```

Step 2 is Claude in a session or a Routine. **No API key and no billing** — the constraints
live in the prompt, `docs/VOICE.md` and the validator, and the validator cannot tell which
mode produced the words. `author.py --api` exists only for the unattended weekly job.

### Next

1. **Point Pages at the workflow** (see above), if it is still on branch deployment.
2. **The second walk.** Standish Wood is next in the queue. Put its slug in
   `data/survey-request.txt` and push, or dispatch the `survey` workflow.
3. **Walk it, then resolve it**, so `confidence.navigable` starts being scored. 0.72 on
   Haresfield Beacon is a real forecast: the access is well recorded, but half the route has
   no surface tag and there is a ford of unknown depth.
4. **The real Explorer sheet**, if you want it: an OS Data Hub key in `OS_API_KEY`, and
   `WAYMARK_BASEMAP` set to `os-leisure` only if you have the Premium plan. Until then the basemap is OpenTopoMap, tinted onto
   cuddly-lamp's paper so it reads as a sheet rather than a generic web map. This is the one
   thing on the site that genuinely needs something from you — OS will not issue a key to
   anyone but the account holder.
5. **`ANTHROPIC_API_KEY`**, only if you want the unattended Sunday job. Everything above
   works without it.

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

Claude does the writing in a session or a Routine, reading the survey and committing the
editorial block — **no API key, no billing**. The gate is what enforces the constraints, and
it cannot tell which mode produced the words, so there is nothing to buy. `author.py --api`
exists only for the unattended weekly job, where no session is present to do the writing.

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

# 1. Survey a target area (no LLM, no API key — but it does need Overpass)
python scripts/survey.py --target haresfield-beacon

# 2. Write it up. Claude reads the survey and writes data/editorial/<slug>.json;
#    this merges it with the surveyed facts. No key, no API call.
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

### Getting a key

Nothing about this is automatable — OS issues keys to an account holder, and that is you.

1. Register at <https://osdatahub.os.uk> and create a **project**.
2. Add the **OS Maps API** to it. The plan you pick decides which styles you get: the
   **OS OpenData** plan is free and serves `Outdoor_3857` — the OS house style, not the
   Explorer sheet. The **Premium** plan is what serves `Leisure_27700`, the actual 1:25 000
   raster, and carries a monthly free credit allowance; confirm the current allowance and
   whether it wants card details at <https://osdatahub.os.uk/plans> before wiring a public
   site to it.
3. In the project settings, **lock the key to a referrer**:
   `https://nihilisticiconoclast.github.io/*`. The key is delivered to the browser by design
   — that is the intended pattern for this API — but referrer-locking is what stops it being
   useful to anyone else. Don't reuse it across projects.
4. In this repo, add **one secret and nothing else**:

   *Settings → Secrets and variables → Actions →* the **Secrets** tab *→ New repository secret*

   | Field | Value |
   |---|---|
   | Name | `OS_API_KEY` |
   | Secret | the key from the Data Hub |

   That is the entire configuration. The basemap follows from whether the key exists — with
   it, the site uses `os-outdoor`; without it, OpenTopoMap. There is no second entry to add.

5. *Actions → pages → Run workflow* to redeploy.

If you want the 1:25 000 Explorer sheet instead of the OS house style, that is the one
optional extra, and it is a **variable**, not a secret — same page, the **Variables** tab
next to Secrets: name `WAYMARK_BASEMAP`, value `os-leisure`. It needs the Premium plan. The
`pages` run logs a notice saying which basemap it wrote and whether it saw a key, so you can
confirm from the run summary rather than by squinting at the map.

Start with `os-outdoor`. It needs only the free plan, it is EPSG:3857 like the default, and
it will tell you the key and referrer lock are right before the projection changes underneath
you as well. **The `os-leisure` URL in `site/app.js` is unverified** — the WMTS layer name and
parameter casing are written from the API specification and have never been run against a live
key, and that is the single line most likely to need adjusting. If tiles fail, the site falls
back to OpenTopoMap after a few errors and says so in the footer rather than showing a blank
map, so a wrong key degrades instead of breaking.

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
