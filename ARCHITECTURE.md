# Architecture

## The central problem

A walk write-up contains two kinds of claim, and they have completely different failure
modes.

The first kind is checkable and consequential: *this is a public footpath*, *this climbs
180 metres*, *there is a car park here*, *this crosses the A46*. Getting one of these wrong
sends someone somewhere they shouldn't be, or leaves them without the ascent they trained
for, or points them at a field entrance with no gate. These claims must come from a source
that can be re-queried and diffed.

The second kind is unfalsifiable and is the entire reason for building this rather than
using an existing walks site: *this section is quiet in a way the map doesn't show*,
*the beeches here are the reason to come in November*, *the climb is short but it's the only
real one, so don't spend yourself on the first mile*. These claims are editorial. They are
what makes a walk yours rather than a GPX file.

An LLM asked for both at once will produce the second kind and dress it as the first. So the
pipeline never asks for both at once.

---

## Data flow

```
data/queue.yml
      │  target area (name, centre, radius, notes)
      ▼
┌──────────────────────────────────────────────┐
│ 1. SURVEY          scripts/survey.py         │   no model, no key
│                                              │
│  Overpass ─→ ways (footpath / bridleway /    │
│              byway / track / permissive)     │
│           ─→ POIs (parking, toilets, pub,    │
│              cafe, NT land, trig, viewpoint) │
│           ─→ hazards (A-roads, level         │
│              crossings, fords, tidal)        │
│  Loop assembly ─→ closed polyline in the     │
│                   requested distance band    │
│  DEM sampling ─→ elevation profile,          │
│                  total ascent, max gradient  │
│  Surface roll-up ─→ % sealed / firm / soft   │
└──────────────────────────────────────────────┘
      │  data/surveys/{slug}.json
      │  { geometry, facts, named_features[] }
      ▼
┌──────────────────────────────────────────────┐
│ 2. AUTHOR          scripts/author.py         │   Claude, tightly bounded
│                                              │
│  Input:  facts + named_features + VOICE.md   │
│  Output: strict JSON per schema/walk.schema  │
│  Forbidden: coordinates, unlisted names,     │
│             turn-by-turn imperatives         │
│  Required: confidence.navigable ∈ (0,1)      │
└──────────────────────────────────────────────┘
      │  data/walks/{slug}.json  (status: draft)
      ▼
┌──────────────────────────────────────────────┐
│ 3. VALIDATE        scripts/validate.py       │   the gate
│                                              │
│  a. JSON Schema                              │
│  b. Proper-noun allowlist                    │
│  c. Numeric agreement: prose vs geometry     │
│  d. Access-rights consistency                │
│  e. Hazard disclosure                        │
│  f. Imperative-voice detector                │
│                                              │
│  pass → status: published                    │
│  fail → status: needs-review, PR labelled    │
└──────────────────────────────────────────────┘
      │
      ▼
  build_index.py ─→ site/data/walks.json ─→ GitHub Pages
      ▲
      │
  data/ledger.json ──→ brier.py ──→ site/data/calibration.json
      ▲
      │
  "Resolve a walk" issue, after you've actually been
```

---

## Why the validation gate looks the way it does

**(b) Proper-noun allowlist.** Extract capitalised token runs from prose, subtract a
stoplist and sentence-initial artefacts, and require each survivor to appear in
`named_features` or `data/gazetteer.txt`. Crude, and it will occasionally flag something
harmless. It also catches the single highest-frequency confabulation in this domain — the
invented pub — which is worth the false positives.

**(c) Numeric agreement.** Regex numbers out of the prose and check each against the
geometry within tolerance. "About four miles" against a 6.9 km loop passes; "about four
miles" against a 9.2 km loop fails. Models round in the wrong direction under pressure to
sound appealing.

**(e) Hazard disclosure.** If the survey found a crossing of a road tagged `primary`,
`trunk`, or above without an associated `footway` or `crossing`, the record must carry a
`hazards[]` entry mentioning it. Omission fails the gate. This is the check most worth
having and the one most likely to be quietly disabled during a frustrating debugging
session — don't.

**(f) Imperative-voice detector.** Sentence-initial bare imperatives ("Turn left at the
gate") signal that the model has slipped from describing to navigating. Waymark is not a
navigation aid and should never read like one.

---

## Calibration: Beating the Bounds

Each published record carries:

```json
"confidence": {
  "navigable": 0.82,
  "basis": "Complete PRoW coverage, two stiles unmapped, one field-edge section with no
            surface tag.",
  "resolved": null
}
```

`resolved` is filled from `data/ledger.json` when you walk it. Outcomes:

| Outcome | Score | Meaning |
|---|---|---|
| `walked_as_described` | 1 | Route followed as written, no backtracking, no access problem |
| `diverged` | 0 | Navigable but the write-up was wrong somewhere material |
| `failed` | 0 | Blocked, unwalkable, or access was not as stated |
| `not_attempted` | — | Excluded from scoring |

`scripts/brier.py` reports the Brier score and its Murphy decomposition —
`BS = REL − RES + UNC` — over resolved walks, plus a reliability diagram binned at 0.1. A
generator that always says 0.85 will show good reliability and no resolution; that is a
failure mode, and the decomposition is there to make it visible rather than letting a
respectable-looking aggregate hide it.

The reference class is deliberately narrow (walks in this corpus, resolved by one walker),
so treat the numbers as an internal control chart rather than a general claim about the
model. `n` is displayed alongside every statistic for that reason.

---

## Front end

**Leaflet 1.9 + Proj4Leaflet.** Not MapLibre. The OS Leisure style — the actual 1:25 000
Explorer sheet, with the orange PRoW dashes and the access-land wash — is published in
British National Grid only. MapLibre cannot serve EPSG:27700 raster tiles. Leaflet with
Proj4Leaflet can, and is also the better fit for a few hundred markers with client-side
filtering.

The CRS is chosen per basemap profile at init:

```js
BASEMAP_PROFILES = {
  opentopo:   { crs: L.CRS.EPSG3857, ... },   // default, no key
  'os-outdoor':{ crs: L.CRS.EPSG3857, ... },  // OS Open Data plan
  'os-leisure':{ crs: BNG,            ... }   // OS Premium plan
}
```

BNG resolutions and origin follow the OS Data Hub reference values; they're in `app.js` with
a comment saying so. Don't tune them.

**Layout.** Map is the page. A left rail holds filters on desktop; below 900 px it becomes a
bottom sheet with three detents (peek / half / full) so the map stays usable one-handed.

**Filters.**

*Toggles* — National Trust land, car park within 200 m of the start, toilets, refreshment
with a vegan option, dog-friendly, public transport reachable, circular, trig point on route.

*Ranges* — distance walked, total ascent, maximum sustained gradient, surface mix
(sealed ↔ soft), technicality, exposure.

*Dial* — bearing sector and radius from the Stroud origin. Replaces the usual radius slider.

Filtering is pure client-side over `site/data/walks.json`. At the scale this will reach —
low hundreds of walks — that's the right call and keeps the whole site a static artefact.

---

## Styling contract

cuddly-lamp owns everything visual. Waymark declares structure and consumes tokens.

`site/index.html` imports, in order:

```html
<link rel="stylesheet" href="https://<user>.github.io/cuddly-lamp/tokens.css">
<link rel="stylesheet" href="https://<user>.github.io/cuddly-lamp/base.css">
<link rel="stylesheet" href="./styles.css">
```

`site/styles.css` may only:

- define layout (grid, flex, positioning, z-index)
- reference cuddly-lamp custom properties
- carry a `@supports not (--x: 1)`-style fallback block, clearly fenced, so the page is
  legible if the import 404s

It may not declare a literal colour, font stack, or radius outside the fallback fence.

If cuddly-lamp exposes a token vocabulary other than what the stub assumes, edit
`site/styles.css` to match cuddly-lamp — never the reverse. **Confirm the actual token names
and file paths before the first build**; the stub assumes a `tokens.css` exporting
`--cl-*` custom properties, which is a guess.

Map tiles are raster and cannot be restyled. The palette therefore has to work *against* a
fixed OS sheet rather than with it, which is a real constraint on cuddly-lamp's side: route
lines, markers, and rail chrome need to hold up over pale green woodland wash and orange
PRoW dashes. Route geometry is drawn twice — a wide low-opacity casing beneath a narrow
solid core — so it stays legible over both the Explorer sheet and OpenTopoMap without
changing colour between profiles.

---

## Scheduling

The weekly job is a **GitHub Actions scheduled workflow**, not a Claude Routine, and the
choice matters.

Actions gives a durable audit trail, deterministic re-runs from a commit SHA, schema
validation in CI, and — most importantly — a pull request you review before anything reaches
the site. The generator is on probation permanently; it should not have write access to
`main`.

Claude Routines are the better tool for the other half of the loop: a Sunday-evening nudge
that reads `data/ledger.json`, finds published walks you haven't resolved, and asks you
about the ones you're likely to have done. That's a prompt-and-notify task with no artefact
to version, which is exactly what Routines are for. Both trigger types exist — schedule and
GitHub event — so the Routine can also fire on the PR if you'd rather it summarised the new
walk into a message than a diff.

Cadence: one walk per week, Sunday 06:00 UTC. Daily is tempting and wrong — you'd accumulate
sixty unverified records inside two months and the ledger would never catch up. The rate
limit on the whole system is how fast you can walk.
