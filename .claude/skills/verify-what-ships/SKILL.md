---
name: verify-what-ships
description: >-
  Checks to run before claiming a static site, page, or deployed artifact works — and how to
  debug one without guessing. Use when deploying to GitHub Pages, Netlify, Cloudflare Pages
  or similar; when a page "should be live" but somebody says it is blank, missing, or showing
  the wrong thing; when a site depends on a CDN at runtime; or when tuning a heuristic whose
  only feedback loop is a slow CI job. Not for backend services or anything with a server.
---

# Verify what ships

Every rule here was paid for. Each one is a specific failure that survived several rounds of
confident, incorrect reassurance because the wrong thing was being checked.

---

## 1. A green deploy is not a live site

**Check what is *served*, not what is *deployed*.** These are different claims and only one
of them is what the user is looking at.

The case that took a day: a GitHub Pages workflow uploaded an artifact and reported
`Reported success!` with the correct environment URL, on every push, for a week. The site
served the repository's `README.md` the whole time, because Pages was set to **Deploy from a
branch**, and under that setting GitHub runs Jekyll over the repo and renders `README.md` as
the index. The artifact was built, uploaded, deployed, and served to nobody.

- The tell, which was visible in the run list from the first hour: a **`pages build and
  deployment` run with event `dynamic`** sitting alongside the workflow's own run. That is
  the legacy Jekyll builder and it exists *only* under branch deployment.
- If the deploying environment cannot reach the public internet, say so and ask the user what
  they see, rather than inferring liveness from the workflow's exit code. "The deploy
  succeeded" is not an answer to "the page is blank".
- Under branch deployment, `.nojekyll` plus a root `index.html` redirect makes a site in a
  subdirectory work; the source setting is still the actual fix, because anything generated
  during the workflow — a config file, an injected API key — does not exist in a branch build.

**Never tell someone to hard-refresh as a first response.** It is right often enough to be a
habit and it burns the user's trust when the cause is structural.

---

## 2. A generated config that fails to parse fails silently

If the build writes a file the page then loads — a config, an injected key, a feature flag —
nothing about a broken one announces itself. A `<script>` that fails to parse simply does not
run: no network error, no missing file, no red anywhere in the deploy. The application falls
back to its defaults, and defaults look deliberate.

The case: a Pages workflow wrote `site/config.js` with

```yaml
run: python - <<'PY' > site/config.js
```

and the script printed *both* its log annotations and the payload. Every `print` went into the
file:

```js
::notice::basemap=os-outdoor (OS key present)   // SyntaxError: Unexpected token ':'
window.WAYMARK_CONFIG = { ... };                // never reached
```

The API key was configured correctly the whole time. The site served the keyless fallback
basemap for a week and reported no error to anyone.

- **Never redirect a generator's stdout into the artifact it generates.** Log lines and
  payload are two channels sharing one pipe. Write the file; print to the log.
- **Syntax-check generated code in the build.** `node --check out.js` is one line and would
  have failed the run on the first push. Assert the *shape* too — that the file is the single
  statement it is meant to be — which also catches a partial or doubled write.
- **Distinguish "absent" from "broken" in the consuming code.** A config legitimately missing
  in development and a corrupt one in production take the same silent path to the same
  defaults. Say which happened, in the page.

**A log line you added to prove a fact, then missing from the log, is itself the finding.**
The `::notice::` above existed specifically to answer "did the runner see the key". When it
wasn't in the log the first assumption was a too-short tail. It wasn't: its absence *was* the
bug, sitting in full view.

---

## 3. Nothing at module scope may touch a library that might not load

A page that links a library from a CDN and then uses it while the module is being parsed has
no failure mode short of total. This kills the whole page, not the feature:

```js
const state = { layer: L.layerGroup() };            // throws on parse if L is absent
const PROFILES = { a: { crs: L.CRS.EPSG3857 } };    // so does this
```

One `ReferenceError` before the first function definition means every line after it never
runs. Static markup still renders, so the page looks present and is completely inert — the
hardest failure to diagnose from a screenshot and the easiest to misread as "nothing loaded".

- Touch the library inside the init function, never at module scope. Make config entries that
  reference it lazy (`crs: () => L.CRS.EPSG3857`).
- **Vendor load-bearing runtime dependencies.** If the page is meaningless without it, a
  third-party origin should not stand between the user and it. A map library is load-bearing;
  a stylesheet with a local fallback is not.
- Fail loudly *in the page*. A blank rectangle and a clean console in somebody else's browser
  is the hardest kind of bug to be told about.

---

## 4. Test with every external origin blocked

The single highest-value test for a static site, and the one that would have caught the above
immediately:

```js
await page.route('**/*', r =>
  r.request().url().startsWith('http://127.0.0.1') ? r.continue() : r.abort());
```

Load the page, then assert on what exists: library present, root component mounted, data
rendered, zero page errors. Proxying CDNs from a local checkout — the obvious way to test
offline — *hides* this class of bug, because it makes the library available. That is exactly
how a broken page passed local verification repeatedly.

Run it before *and* after a fix, and quote both. "It works now" is worth far less than a
before/after on the same probe.

---

## 5. Cache-bust local assets at build time

A broken asset plus a browser cache is a site that stays broken specifically for the person
who already visited — the person reporting it. Stamp the build's commit onto local asset URLs
so fresh HTML can never pair with a stale script:

```
./app.js  →  ./app.js?v=<short-sha>
```

---

## 6. Do not tune a heuristic through a slow feedback loop

Iterating on an algorithm through six-minute CI runs against a rate-limited public API is not
debugging. It is guessing slowly, and it produces confident theories that each cost a round
trip to disprove.

- Get the input data local, once — commit the fixture, publish it as an artifact, whatever it
  takes — then iterate in seconds. Delete it when the algorithm settles.
- Make failures say **what was found**, not just that nothing was. "No loop found" cost
  several runs; "17 loops in band but more than 25% road, 230 in band but none within 500 m of
  the target" identified two separate bugs in one.
- Write the regression test at the moment you understand the bug, against a synthetic input.
  Two real bugs here were found by tests before CI ever saw them.

---

## 7. Remove the option rather than penalising it

When a search keeps choosing something it should not, weighting it more heavily is usually
the wrong fix and always the slower one. A penalty can be outvoted by every other term in the
score, so the argument repeats with new numbers each round.

Take the option out of the search space, and fall back only if nothing is found without it.
The result is then correct *by construction* rather than by hoping the scoring holds — and
that is a property you can assert in a test.

---

## Before saying it works

- [ ] Loaded the real deployed URL, or said plainly that you could not and why.
- [ ] Confirmed which source the host is serving from, not just that the job passed.
- [ ] Anything the build generates and the page loads was syntax-checked by the build.
- [ ] Ran the page with all external origins blocked; zero page errors.
- [ ] Local assets are cache-busted.
- [ ] Quoted a before/after from the same probe, not a description of the change.
