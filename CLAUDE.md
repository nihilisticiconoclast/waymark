# CLAUDE.md

Operating instructions for Claude Code in this repository.

Read this, then `docs/ARCHITECTURE.md`, then `docs/VOICE.md` before touching anything under
`prompts/` or `scripts/author.py`.

---

## What this repo is

A GitHub Pages site: a full-bleed OS-style map of walks around Stroud, Gloucestershire, with
store-finder style filtering. Walks are produced by a two-stage pipeline — a deterministic
geospatial **survey**, then a constrained editorial **authoring** pass — and published only
after passing a validation gate.

---

## Invariants

These are not preferences. Breaking any of them is a defect, not a style choice.

1. **Claude never emits a coordinate.** Every latitude, longitude, elevation, distance, and
   gradient in a published record traces to OSM or a DEM. If a coordinate appears in a
   model response, the pipeline is wired wrong — fix the wiring, don't hand-correct the value.

2. **Claude never names anything the survey didn't find.** No pub, farm, hill, wood, lane,
   stile, or gate may appear in prose unless it is in the survey payload's `named_features`
   or in `data/gazetteer.txt`. `scripts/validate.py` enforces this. If a write-up would be
   better with a name the survey lacks, the correct fix is to widen the Overpass query, not
   to relax the check.

3. **Nothing publishes without passing `scripts/validate.py`.** Not in CI, not locally, not
   "just to see it on the map". A failing record gets `status: needs-review` and stops.

4. **Directions describe; they do not instruct.** Waymark says what is there. It does not
   say "cross the field" as though it has checked the field this month. Register is
   descriptive-with-caveats, never imperative-with-confidence. See `docs/VOICE.md`.

5. **Access rights are asserted only from `designation` tags.** A path being mapped in OSM
   is not a right of way. Only `public_footpath`, `public_bridleway`, `restricted_byway`,
   `byway_open_to_all_traffic`, and land with an explicit open-access tag may be described as
   walkable-by-right. Everything else is `permissive` or `unknown` and is labelled as such.

6. **`confidence.navigable` is a forecast and is scored.** Do not inflate it to make a walk
   look good, and do not flatten everything to 0.8 to be safe. It feeds a Brier score with a
   Murphy decomposition; a well-behaved generator should show resolution, not just reliability.

7. **No styling lives here.** All colour, type and radius come from cuddly-lamp, whose
   vocabulary is `--paper`, `--ink`, `--contour`, `--index`, `--incident`, `--amber`,
   `--route`, `--font-display/body/data`, `--radius`, `--rule`, `--step--1` … `--step-4`.
   `site/styles.css` contains layout, layout spacing under a `--wm-` prefix — cuddly-lamp
   has no spacing scale — and a clearly-marked fallback shim. Nothing else.

---

## File map

```
docs/ARCHITECTURE.md   the design, the data flow, the styling contract
docs/VOICE.md          editorial specification — the highest-leverage file in the repo
docs/DATA.md           sources, licences, attribution, tag vocabulary
prompts/               system + user prompts for the authoring pass
data/editorial/        written editorial blocks — the API-free authoring path
data/survey-request.txt  commit a slug here and push; the survey workflow runs it
schema/walk.schema.json  the contract between authoring and the site
scripts/survey.py      Overpass + DEM → data/surveys/{id}.json   (no LLM)
scripts/author.py      survey + editorial → data/walks/{id}.json  (no API by default)
scripts/validate.py    the gate
scripts/build_index.py data/walks/*.json → site/data/walks.json + queue.json
scripts/brier.py       ledger → calibration statistics
tests/test_pipeline.py the invariants above, as executable checks
site/                  the map
site/vendor/           Leaflet + proj4, vendored on purpose — see pitfalls
index.html, .nojekyll  Pages workaround while the source is a branch — see pitfalls
data/queue.yml         target areas awaiting survey
data/ledger.json       Beating the Bounds resolutions
```

---

## Commands

```bash
python scripts/survey.py --target <slug>          # or --next to pull from data/queue.yml
python scripts/author.py --survey data/surveys/<slug>.json   # uses data/editorial/<slug>.json
python scripts/validate.py data/walks/*.json      # --strict in CI
python scripts/build_index.py
python scripts/brier.py                           # calibration report
python -m unittest discover -s tests -v           # no key, no network, no survey
python -m http.server 8000 --directory site
```

---

## Working style

Small, reviewable commits. One walk per pull request — the weekly Actions job
(`.github/workflows/new-walk.yml`, not a Claude Routine; the reasoning is in
`docs/ARCHITECTURE.md` → *Scheduling*) opens a PR titled `walk: <slug>`, and the diff should
be one new JSON file plus a regenerated index.

When changing `prompts/` or `docs/VOICE.md`, regenerate at least two existing walks with the
new prompt and put the before/after in the PR description. Prompt changes are model changes;
they get evidence, not assertions.

When a validation gate fires, the default response is to tighten the survey or the prompt.
Loosening the gate requires a note in the PR explaining what class of error is now permitted
and why that's acceptable.

Prose in docs, not bullets, where the content is argument rather than enumeration.

---

## Common pitfalls

- **Overpass rate limits.** The public endpoint will refuse you. Back off, cache to
  `data/surveys/.cache/`, and never call it from the site at runtime.
- **`highway=path` is not a right of way.** See invariant 5.
- **Route-finding asks for cycles, not for a way home.** `find_circuit` contracts the path
  network to its junctions and searches for actual closed walks. The heuristic it replaced
  walked out to a turning point and looked for a different way back, which is not a circuit
  and never behaved like one — four rounds of re-weighting bought a flat vale loop with a
  Costa on it. If it needs improving, improve the cycle search; don't reintroduce the other.
- **Roads are removed from the graph, not made expensive.** With a lane in the graph the
  shortest path is free to use it, and a lane that saves two kilometres beats a footpath on
  every term except the penalty. The first pass deletes road classes outright, so a walk is
  road-free by construction. Lanes come back only if nothing else exists, capped at 25%.
- **Open-access land is a multipolygon.** An estate boundary's member ways are open segments
  that close only when stitched. Skipping unclosed rings discarded every National Trust
  boundary in the extract, and paths walkable by right because of the land they cross got
  priced as "status unknown". `access_polygons` merges and polygonises.
- **The Leisure basemap is EPSG:27700 only.** Don't "simplify" the CRS handling by dropping
  Proj4Leaflet; you'll lose the Explorer style entirely.
- **`site/config.js` is gitignored.** If the map is blank locally, copy
  `site/config.example.js` across.
- **Authoring does not need the API.** Claude is already the thing reading the survey; write
  `data/editorial/<slug>.json` and `author.py` merges it. `--api` is for the unattended job.
- **An Overpass extract is mostly fragments.** The loop search starts from the largest
  connected component; the node nearest the anchor is often an orphaned driveway stub.
- **Queued areas on the map are not walks.** They come from `data/queue.yml` via
  `site/data/queue.json`, carry no surveyed facts, and answer to the dial only. Giving one a
  distance or a confidence to make the map look fuller breaks the line the repo is built on.
- **The CSS fallback fence is a cascade layer.** `--ink: var(--ink, #4A3823)` looks like a
  neat shim and is a self-reference: the property goes invalid and takes the palette with it.
- **Nothing in `site/app.js` may touch `L` at module scope.** `routeLayer: L.layerGroup()` in
  a state object, or `L.CRS.EPSG3857` in a config table, runs the moment the file is parsed —
  so a Leaflet that hasn't loaded takes the entire page down, rail and all, with one
  ReferenceError. Leaflet and proj4 are vendored in `site/vendor/` for the same reason: they
  are load-bearing, and a static site should not put third-party origins between a walker and
  the map. Test the site with **every external origin blocked** before believing it works.
- **Check what is *served*, not what is *deployed*.** A green `pages` run means the artifact
  uploaded. It does not mean anyone can see it: with Pages source set to "Deploy from a
  branch", Jekyll renders `README.md` as the site and the artifact goes nowhere. The tell is
  a `pages build and deployment` run with event `dynamic` sitting beside your own — that is
  the legacy builder, and it only exists under branch deployment.
