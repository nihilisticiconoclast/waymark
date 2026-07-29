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
      ▲         └─→ site/data/queue.json   (unsurveyed targets, drawn hollow)
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

The gate is itself gated. `tests/test_pipeline.py` breaks a known-good record one field at a
time and asserts that each check catches it: an invented pub, an unqualified right-of-way
claim over an undesignated route, an undisclosed road crossing, "about two miles" against an
eight-kilometre loop. A check that has stopped firing still prints `ok`, which is the most
comfortable way for this system to fail, and the only defence against it is a test that fails
instead. The same file exercises the loop assembler against a synthetic graph, because the
alternative is discovering its behaviour one Overpass call at a time.

A seed record is reported as `SEED` rather than `FAIL` and does not trip `--strict`. It is an
example of the schema and is refused on purpose; letting it redden every pull request would
put steady pressure on the gate itself, which is the outcome this whole design is arranged to
avoid.

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

**The empty state.** A corpus of zero is this site's starting condition and will recur any
time the queue outruns the walking, so the map shows `site/data/queue.json` — the target areas
from `data/queue.yml`, drawn hollow and dashed. This is a deliberate concession and it has one
rule: a queued area must never be mistakable for a walk. It carries no route, no distance, no
ascent and no confidence, because none of those exist until a survey has run; its marker is a
different shape rather than a paler shade; and it answers to the dial alone, since every other
filter reads an attribute a survey produces. A queued area leaves the layer the moment a walk
with its slug is published. `tests/` asserts the first of those rules against the real queue.

The alternative was a blank map, which is indistinguishable from a broken one, and the failure
mode of a broken-looking map is that somebody starts loosening things to make walks appear.

Filtering is pure client-side over `site/data/walks.json`. At the scale this will reach —
low hundreds of walks — that's the right call and keeps the whole site a static artefact.

---

## Styling contract

cuddly-lamp owns everything visual. Waymark declares structure and consumes tokens.

The contract was a guess in the first draft — a `tokens.css` plus a `base.css` on GitHub
Pages, exporting `--cl-*` properties — and confirming it against cuddly-lamp was the first
build's first job. None of the three assumptions held. What is actually there is a single
stylesheet, served from jsDelivr because that is what cuddly-lamp's own distribution notes
ask consumers to use, exporting unprefixed names:

```html
<link rel="stylesheet"
      href="https://cdn.jsdelivr.net/gh/nihilisticiconoclast/cuddly-lamp@main/assets/tokens.css">
<link rel="stylesheet" href="./styles.css">
```

| Group | Tokens |
|---|---|
| Colour | `--paper` `--ink` `--contour` `--index` `--incident` `--amber` `--route` |
| Type | `--font-display` `--font-body` `--font-data` |
| Scale | `--step--1` `--step-0` `--step-1` `--step-2` `--step-3` `--step-4` |
| Form | `--radius` (0 — hard edges) `--rule` (a hairline border shorthand) `--measure` |

`site/styles.css` may only:

- define layout (grid, flex, positioning, z-index) and layout spacing
- reference cuddly-lamp custom properties
- carry a clearly fenced fallback block so the page is legible if the CDN 404s

It may not declare a literal colour, font stack, or radius outside the fallback fence.

Two consequences worth stating, because both are places the boundary could quietly erode.

**Spacing.** cuddly-lamp has no spacing scale — it is a document system, and a document's
rhythm comes from its type scale. An application rail needs one, so `site/styles.css` defines
`--wm-space-1` … `--wm-space-5`. Spacing is geometry and geometry is that file's job; the
prefix is there so that if cuddly-lamp ever grows a spacing vocabulary, every line to delete
is greppable.

**The fence is a cascade layer, not `@supports`.** Unlayered styles beat layered ones
regardless of source order, so tokens.css overrides the fence the moment it loads, and the
fence applies only when it doesn't. The obvious-looking alternative — `--ink: var(--ink,
#4A3823)` — is a self-reference, which makes the property invalid at computed-value time and
takes the whole palette down with it. It looked like it worked because the page still
rendered, in the browser's defaults.

If cuddly-lamp changes its vocabulary again, edit `site/styles.css` to match cuddly-lamp —
never the reverse.

The house signature is part of the contract, not decoration: the fixed `mark` logo sits in the
rail head, and one per-page `doodle`, seeded from the page and positioned by
`TunnelFigure.placeDoodle`, sits behind the rail's blocks. The rail is the only gutter the
page has — the map is opaque and full-bleed — so that is where it goes. Both mounts are
guarded, because the site has to stay usable when the CDN is unreachable.

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

Three workflows, and they do different jobs. `new-walk.yml` is the weekly generator and opens
the pull request. `ci.yml` is the gate: invariant tests, `validate.py --strict`, and a check
that `site/data` is what `build_index.py` and `brier.py` would produce from the records — a
hand-edited index would otherwise put something on the map that does not follow from
`data/walks/`. `pages.yml` deploys what survived.

Claude Routines are the better tool for the other half of the loop: a Sunday-evening nudge
that reads `data/ledger.json`, finds published walks you haven't resolved, and asks you
about the ones you're likely to have done. That's a prompt-and-notify task with no artefact
to version, which is exactly what Routines are for. Both trigger types exist — schedule and
GitHub event — so the Routine can also fire on the PR if you'd rather it summarised the new
walk into a message than a diff.

Cadence: one walk per week, Sunday 06:00 UTC. Daily is tempting and wrong — you'd accumulate
sixty unverified records inside two months and the ledger would never catch up. The rate
limit on the whole system is how fast you can walk.
