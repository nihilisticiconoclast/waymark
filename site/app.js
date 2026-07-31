/* ===========================================================================
   Waymark
   =========================================================================== */

/* Styling comes from cuddly-lamp's CDN copy, linked in index.html — there is no base URL
   to configure here. Config carries the basemap choice and the OS key, nothing else.

   Whether config.js actually loaded is worth knowing separately from what it said. Absent
   (running from a checkout, where it is gitignored) and present-but-broken produce exactly
   the same silent fall to these defaults, and the second one looks from the outside like a
   deploy that ignored your OS key. The footer says which happened. */
const CFG_LOADED = window.WAYMARK_CONFIG != null && typeof window.WAYMARK_CONFIG === "object";
const CFG = Object.assign(
  { basemap: "opentopo", osApiKey: "" },
  CFG_LOADED ? window.WAYMARK_CONFIG : {}
);

const ORIGIN = { lat: 51.7447, lon: -2.2166, name: "Stroud" };   // keep in step with build_index.py
const MAX_RADIUS_KM = 90;

/* ── basemaps ──────────────────────────────────────────────────────────────
   The Leisure style — the actual 1:25 000 Explorer sheet — is published in British
   National Grid only, which is why this file carries Proj4Leaflet and why the CRS is
   chosen per profile rather than assumed. MapLibre cannot serve EPSG:27700 raster.
   Resolutions and origin below are the OS Data Hub reference values; don't tune them.  */

const BNG = () => new L.Proj.CRS(
  "EPSG:27700",
  "+proj=tmerc +lat_0=49 +lon_0=-2 +k=0.9996012717 +x_0=400000 +y_0=-100000 " +
  "+ellps=airy +towgs84=446.448,-125.157,542.06,0.15,0.247,0.842,-20.489 +units=m +no_defs",
  {
    resolutions: [896, 448, 224, 112, 56, 28, 14, 7, 3.5, 1.75, 0.875, 0.4375, 0.21875, 0.109375],
    origin: [-238375.0, 1376256.0]
  }
);

/* Every `crs` is a function, including the two plain 3857 ones that do not need to be.
   Anything evaluated here runs the moment this file is parsed, before the guard in main()
   can report a missing library — so nothing at module scope may reach into L. */
const BASEMAP_PROFILES = {
  opentopo: {
    crs: () => L.CRS.EPSG3857,
    url: "https://{s}.tile.opentopomap.org/{z}/{x}/{y}.png",
    options: { maxZoom: 17, subdomains: "abc" },
    zoom: 11, minZoom: 8, maxZoom: 17,
    attribution: "Map data © OpenStreetMap contributors, SRTM · Tiles © OpenTopoMap (CC-BY-SA)"
  },
  "os-outdoor": {
    crs: () => L.CRS.EPSG3857,
    url: "https://api.os.uk/maps/raster/v1/zxy/Outdoor_3857/{z}/{x}/{y}.png?key={key}",
    options: { maxZoom: 20 },
    zoom: 12, minZoom: 8, maxZoom: 20,
    attribution: "Contains OS data © Crown copyright and database rights " + new Date().getFullYear()
  },
  "os-leisure": {
    crs: BNG,
    // WMTS rather than ZXY: the 27700 tile matrix is served through the WMTS endpoint.
    // Verify the layer name and parameter casing against the OS Maps API technical
    // specification before the first deploy — this is the one URL most likely to bite.
    url: "https://api.os.uk/maps/raster/v1/wmts?key={key}&service=WMTS&request=GetTile" +
         "&version=2.0.0&height=256&width=256&outputFormat=image%2Fpng&style=default" +
         "&layer=Leisure_27700&tileMatrixSet=EPSG%3A27700&tileMatrix={z}&tileRow={y}&tileCol={x}",
    options: { maxZoom: 13 },
    zoom: 7, minZoom: 3, maxZoom: 13,
    attribution: "Contains OS data © Crown copyright and database rights " + new Date().getFullYear()
  }
};

/* ── state ─────────────────────────────────────────────────────────────────── */

const state = {
  walks: [],
  markers: new Map(),
  queue: [],                         // areas awaiting survey — never walks
  queueMarkers: new Map(),
  showQueue: true,
  routeLayer: null,          // created in initMap; see the note on module scope below
  basemapFellBack: false,
  basemapNote: "",                   // why the basemap on screen isn't the one asked for
  selected: null,
  sector: null,                      // { b0, b1, r0, r1 } — set by the dial
  filters: {
    dist: 30, asc: 900, grad: 30, surf: 0, tech: 5, conf: 0,
    run: "", flags: new Set()
  }
};

let map;

/* Nothing at module scope may touch Leaflet. `routeLayer: L.layerGroup()` used to sit in the
   state object above, which meant that if Leaflet had not loaded — a blocked CDN, an offline
   phone, an ad blocker taking out unpkg — this file threw a ReferenceError on line one and
   the whole page died: no map, no filters, no counts, just the static shell. The libraries
   are vendored now so that should not happen, but the ordering dependency was the actual
   bug and it is worth not reintroducing. */

/* Report a failure where it can be seen. If the map is already up, the message goes in the
   rail — replacing a working map with an error panel would be a second bug on top of the
   first. Only a map that never initialised gets overwritten. */
function fatal(message) {
  console.error(message);
  const banner = `<p class="map-error" role="alert">${message}</p>`;
  if (map) {
    const note = document.getElementById("state-note");
    if (note) { note.hidden = false; note.innerHTML = banner; }
    return;
  }
  const el = document.getElementById("map");
  if (el) el.innerHTML = banner;
}

/* ── geodesy ───────────────────────────────────────────────────────────────── */

const rad = d => d * Math.PI / 180;

function crowKm(a, b) {
  const R = 6371;
  const dp = rad(b.lat - a.lat), dl = rad(b.lon - a.lon);
  const h = Math.sin(dp / 2) ** 2 +
            Math.cos(rad(a.lat)) * Math.cos(rad(b.lat)) * Math.sin(dl / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(h));
}

const COMPASS = ["N", "NNE", "NE", "ENE", "E", "ESE", "SE", "SSE",
                 "S", "SSW", "SW", "WSW", "W", "WNW", "NW", "NNW"];
const compass = deg => COMPASS[Math.round(((deg % 360) + 360) % 360 / 22.5) % 16];

/* ── map ───────────────────────────────────────────────────────────────────── */

function initMap() {
  state.routeLayer = L.layerGroup();
  const p = BASEMAP_PROFILES[CFG.basemap] || BASEMAP_PROFILES.opentopo;
  const crs = typeof p.crs === "function" ? p.crs() : p.crs;

  map = L.map("map", { crs, zoomControl: false, minZoom: p.minZoom, maxZoom: p.maxZoom })
        .setView([ORIGIN.lat, ORIGIN.lon], p.zoom);

  L.control.zoom({ position: "bottomright" }).addTo(map);
  map.on("zoomend moveend", upgradeGeometry);

  const url = p.url.replace("{key}", CFG.osApiKey);
  const base = L.tileLayer(url, Object.assign({ attribution: p.attribution }, p.options))
    .addTo(map);

  /* An OS profile can fail for several dull reasons — no key, a key not entitled to that
     product, a referrer lock that doesn't match the Pages origin, or the Leisure WMTS
     parameters being slightly off. None of them should leave a blank map, so a basemap that
     never manages to draw anything falls back to the keyless one and says so in the footer.
     A map with the wrong tiles is still a map; a map with no tiles is a bug report.

     "Never manages to draw anything" is the whole condition, and it used to be four failed
     tiles instead. That is not the same test: OS returns 404 for any tile outside Great
     Britain, so a view with coast in it — which is most of them once you zoom out — spends
     four errors on the sea and permanently downgrades a basemap that was working. One
     successful tile settles it; nothing after that can trigger the fallback. */
  if (CFG.basemap !== "opentopo") {
    let failures = 0, drew = false;
    base.on("tileload", () => { drew = true; });
    base.on("tileerror", () => {
      if (drew || state.basemapFellBack || ++failures < 6) return;
      state.basemapFellBack = true;
      state.basemapNote = `${CFG.basemap} served no tiles — showing OpenTopoMap. ` +
                          "Check the key's OS Maps API entitlement and its referrer lock.";
      console.warn(`Basemap "${CFG.basemap}" drew no tiles in ${failures} attempts; ` +
                   "falling back to OpenTopoMap.");
      map.removeLayer(base);
      const fb = BASEMAP_PROFILES.opentopo;
      L.tileLayer(fb.url, Object.assign({ attribution: fb.attribution }, fb.options)).addTo(map);
      document.getElementById("map").dataset.tint = "true";
      paintFooter(fb);
    });
  }

  // Only the keyless topographic basemap is tinted onto the paper; the OS sheets already
  // look the way they are meant to look, and are somebody else's cartography to leave alone.
  // The pane is full-bleed and fixed to the viewport rather than the map's coordinate space,
  // so it does not slide about under a pan.
  map.createPane("tint");
  const tintPane = map.getPane("tint");
  tintPane.classList.add("leaflet-tint-pane");
  // Leaflet's map pane is a 0x0 transformed div, so a percentage size collapses to nothing.
  // A flat fill can simply be enormous: no edge is reachable by panning, and because it is
  // one colour there is nothing to see moving underneath.
  Object.assign(tintPane.style, {
    zIndex: 300, position: "absolute",
    left: "-20000px", top: "-20000px", width: "40000px", height: "40000px",
  });
  document.getElementById("map").dataset.tint = String(CFG.basemap === "opentopo");

  state.routeLayer.addTo(map);
  paintFooter(p);
  if (!CFG_LOADED) {
    console.warn("config.js did not define window.WAYMARK_CONFIG — running defaults " +
                 "(basemap opentopo, no OS key). Locally: copy site/config.example.js. " +
                 "Deployed: the pages workflow writes it, so it failed to parse.");
  }
}

/* The footer states which basemap is actually on screen, which build drew it, and — when the
   answer is not the one that was asked for — why. "It is still showing OpenTopoMap" has at
   least four causes: a stale cached page, a config that did not load, a config that asked for
   OpenTopoMap, and an OS layer that refused to serve. From the outside they are identical.
   This line separates them without anyone needing to open a console or read a build log. */
function paintFooter(profile) {
  const build = document.querySelector('meta[name="waymark-build"]')?.content || "dev";
  const asked = CFG.basemap;
  const showing = state.basemapFellBack ? "opentopo" : asked;

  let why = "";
  if (!CFG_LOADED) why = "config.js did not load, so this is the default. ";
  else if (state.basemapNote) why = state.basemapNote + " ";

  document.getElementById("attribution").textContent =
    `Basemap: ${showing}${showing === asked ? "" : ` (asked for ${asked})`} · build ${build}. ` +
    why + profile.attribution + " · Walk data © OpenStreetMap contributors (ODbL)";
}

function pinIcon(w, selected) {
  const low = w.confidence < 0.6;
  return L.divIcon({
    className: "",
    html: `<div class="walk-pin" data-low="${low}" data-selected="${!!selected}"></div>`,
    iconSize: [14, 14], iconAnchor: [7, 7]
  });
}

function renderMarkers() {
  state.walks.forEach(w => {
    const m = L.marker([w.lat, w.lon], { icon: pinIcon(w), title: w.name })
               .on("click", () => select(w.slug));
    state.markers.set(w.slug, m);
  });
}

/* The pin carries the selection, so it has to be redrawn when the selection moves.
   divIcon markup is baked at creation; setIcon is the only way to change it. */
function paintSelection() {
  state.walks.forEach(w => {
    const m = state.markers.get(w.slug);
    if (m) m.setIcon(pinIcon(w, w.slug === state.selected));
  });
}

/* Zoom past this and the index's simplified line is no longer good enough: the difference
   between a path that hugs a contour and a polygon that approximates it becomes visible, and
   on a walking map that difference is the information. */
const FULL_GEOMETRY_ZOOM = 14;

/* Fetch full-resolution geometry for every walk currently on screen, once. The index line is
   for the overview — cheap enough to load on a hill with one bar — and this is what replaces
   it when someone actually looks. */
async function upgradeGeometry() {
  if (!map || map.getZoom() < FULL_GEOMETRY_ZOOM) return;
  const bounds = map.getBounds();
  const pending = state.walks.filter(w =>
    !w.fullLine && !w.fetching && passes(w) && w.line &&
    w.line.some(([lat, lon]) => bounds.contains([lat, lon])));
  if (!pending.length) return;

  await Promise.all(pending.map(async w => {
    w.fetching = true;
    try {
      const res = await fetch(`./data/walks/${w.slug}.json`);
      if (!res.ok) return;
      const d = await res.json();
      w.fullLine = d.geometry.route.coordinates.map(([lon, lat]) => [lat, lon]);
    } catch {
      /* offline or missing: the simplified line stays, which is degraded but not broken */
    } finally {
      w.fetching = false;
    }
  }));
  drawRoutes();
}

/* Every visible walk draws its route, always — the route is the walk, and a map of start
   pins tells you nothing about where a walk actually goes. Selecting one thickens it and
   opens the panel; it does not conjure the line out of nowhere. */
function drawRoutes() {
  state.routeLayer.clearLayers();
  state.walks.forEach(w => {
    if (!w.line || !passes(w)) return;
    const latlngs = w.fullLine || w.line;
    const selected = w.slug === state.selected;
    L.polyline(latlngs, { className: "route-casing", interactive: false })
      .addTo(state.routeLayer);
    L.polyline(latlngs, {
      className: selected ? "route-core is-selected" : "route-core",
    }).addTo(state.routeLayer).on("click", () => select(w.slug));
  });
}

/* Queued areas are drawn hollow and never share the walk pin's shape. A queued entry is a
   search anchor from data/queue.yml — not a route, not a start, and not checked against
   anything on the ground. The visual distinction is doing real work: the whole repo is
   arranged so that an unsurveyed area cannot be mistaken for a surveyed one. */
function renderQueue() {
  state.queue.forEach(t => {
    const m = L.marker([t.lat, t.lon], {
      icon: L.divIcon({ className: "", html: `<div class="queue-pin"></div>`,
                        iconSize: [12, 12], iconAnchor: [6, 6] }),
      title: `${t.name} — awaiting survey`,
      keyboard: false,
    }).on("click", () => showQueued(t.slug));
    state.queueMarkers.set(t.slug, m);
  });
}

/* ── filtering ─────────────────────────────────────────────────────────────── */

const unsealedPct = w => Math.max(0, 100 - (w.sealed_pct ?? 0));

function inSector(w) {
  const s = state.sector;
  if (!s) return true;
  if (w.crow_km < s.r0 || w.crow_km > s.r1) return false;
  const b = ((w.bearing % 360) + 360) % 360;
  return s.b0 <= s.b1 ? (b >= s.b0 && b <= s.b1) : (b >= s.b0 || b <= s.b1);
}

function passes(w) {
  const f = state.filters;
  if (w.distance_km > f.dist) return false;
  if (w.ascent_m > f.asc) return false;
  if (f.grad < 30 && (w.gradient_pct ?? 0) > f.grad) return false;
  // "Unsealed" is everything that is not sealed — firm and untagged count, not just soft.
  // Filtering on soft_pct alone hid every walk on a well-tagged firm track.
  if (unsealedPct(w) < f.surf) return false;
  if ((w.ratings?.technicality ?? 1) > f.tech) return false;
  if (w.confidence * 100 < f.conf) return false;
  if (f.run === "throughout" && w.runnable !== "throughout") return false;
  if (f.run === "mostly" && !["mostly", "throughout"].includes(w.runnable)) return false;
  for (const flag of f.flags) if (!w[flag]) return false;
  return inSector(w);
}

function apply() {
  let shown = 0;
  state.walks.forEach(w => {
    const ok = passes(w);
    const m = state.markers.get(w.slug);
    if (ok) { if (!map.hasLayer(m)) m.addTo(map); shown++; }
    else if (map.hasLayer(m)) map.removeLayer(m);
  });

  // Queued areas answer only to the dial. The other filters read attributes a survey
  // produces — distance, ascent, surface — and a queued area has none of them, so
  // filtering on those would silently hide things for reasons that aren't true of them.
  let queued = 0;
  state.queue.forEach(t => {
    const ok = state.showQueue && inSector(t);
    const m = state.queueMarkers.get(t.slug);
    if (!m) return;
    if (ok) { if (!map.hasLayer(m)) m.addTo(map); queued++; }
    else if (map.hasLayer(m)) map.removeLayer(m);
  });

  document.getElementById("count").textContent = shown;
  const qc = document.getElementById("queue-count");
  if (qc) qc.textContent = queued;
  drawRoutes();
  drawDots();
  upgradeGeometry();
}

/* ── the dial ──────────────────────────────────────────────────────────────
   Every walk is a dot in polar coordinates about Stroud: angle is bearing, radius is
   distance as the crow flies. Drag across it and the bounding sector of the drag becomes
   the filter — one gesture, two dimensions. A radius slider can't do that, and nobody
   chooses a walk by radius anyway.                                                       */

const DIAL_R = 92;
const svg = id => document.getElementById(id);
const kmToPx = km => Math.min(km, MAX_RADIUS_KM) / MAX_RADIUS_KM * DIAL_R;
const pxToKm = px => px / DIAL_R * MAX_RADIUS_KM;

function polar(bearingDeg, km) {
  const a = rad(bearingDeg - 90);
  const r = kmToPx(km);
  return [r * Math.cos(a), r * Math.sin(a)];
}

function drawChrome() {
  const rings = svg("dial-rings"), ticks = svg("dial-ticks");
  rings.innerHTML = ""; ticks.innerHTML = "";

  [15, 30, 45, 60, 90].forEach(km => {
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("r", kmToPx(km));
    rings.appendChild(c);
  });

  ["N", "E", "S", "W"].forEach((label, i) => {
    const deg = i * 90;
    const [x1, y1] = polar(deg, MAX_RADIUS_KM * 0.92);
    const [x2, y2] = polar(deg, MAX_RADIUS_KM);
    const ln = document.createElementNS("http://www.w3.org/2000/svg", "line");
    ln.setAttribute("x1", x1); ln.setAttribute("y1", y1);
    ln.setAttribute("x2", x2); ln.setAttribute("y2", y2);
    ticks.appendChild(ln);

    const [tx, ty] = polar(deg, MAX_RADIUS_KM * 1.09);
    const t = document.createElementNS("http://www.w3.org/2000/svg", "text");
    t.setAttribute("x", tx); t.setAttribute("y", ty);
    t.textContent = label;
    ticks.appendChild(t);
  });
}

function drawDots() {
  const g = svg("dial-dots");
  g.innerHTML = "";

  if (state.showQueue) {
    state.queue.forEach(t => {
      const [x, y] = polar(t.bearing, t.crow_km);
      const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
      c.setAttribute("cx", x); c.setAttribute("cy", y);
      c.setAttribute("class", "queue-dot");
      c.setAttribute("data-in", inSector(t));
      c.setAttribute("role", "img");
      c.setAttribute("aria-label",
        `${t.name}, awaiting survey, ${t.crow_km} km ${compass(t.bearing)}`);
      c.addEventListener("click", e => { e.stopPropagation(); showQueued(t.slug); });
      g.appendChild(c);
    });
  }

  state.walks.forEach(w => {
    const [x, y] = polar(w.bearing, w.crow_km);
    const c = document.createElementNS("http://www.w3.org/2000/svg", "circle");
    c.setAttribute("cx", x); c.setAttribute("cy", y);
    c.setAttribute("data-in", passes(w));
    c.setAttribute("role", "img");
    c.setAttribute("aria-label", `${w.name}, ${w.crow_km} km ${compass(w.bearing)}`);
    c.addEventListener("click", e => { e.stopPropagation(); select(w.slug); });
    g.appendChild(c);
  });
}

function drawWedge() {
  const path = svg("dial-wedge");
  const s = state.sector;
  if (!s) { path.setAttribute("d", ""); return; }

  const [ax, ay] = polar(s.b0, s.r1), [bx, by] = polar(s.b1, s.r1);
  const [cx, cy] = polar(s.b1, s.r0), [dx, dy] = polar(s.b0, s.r0);
  const span = (s.b1 - s.b0 + 360) % 360;
  const large = span > 180 ? 1 : 0;

  path.setAttribute("d",
    `M ${ax} ${ay} A ${kmToPx(s.r1)} ${kmToPx(s.r1)} 0 ${large} 1 ${bx} ${by} ` +
    `L ${cx} ${cy} A ${kmToPx(s.r0)} ${kmToPx(s.r0)} 0 ${large} 0 ${dx} ${dy} Z`);
}

function readSector() {
  const el = svg("dial-read"), s = state.sector;
  el.textContent = s
    ? `${compass(s.b0)}–${compass(s.b1)}, ${Math.round(s.r0)}–${Math.round(s.r1)} km`
    : "All directions, any distance";
}

function initDial() {
  const el = svg("dial");
  let drag = null;

  const at = ev => {
    const r = el.getBoundingClientRect();
    const x = (ev.clientX - r.left) / r.width * 220 - 110;
    const y = (ev.clientY - r.top) / r.height * 220 - 110;
    return {
      bearing: ((Math.atan2(y, x) * 180 / Math.PI + 90) % 360 + 360) % 360,
      km: pxToKm(Math.hypot(x, y))
    };
  };

  el.addEventListener("pointerdown", ev => {
    el.setPointerCapture(ev.pointerId);
    drag = { from: at(ev), moved: false };
  });

  el.addEventListener("pointermove", ev => {
    if (!drag) return;
    const to = at(ev);
    drag.moved = true;
    const b0 = drag.from.bearing, b1 = to.bearing;
    // Take the shorter arc between the two — dragging clockwise past north should not
    // select 340 degrees of the compass.
    const cw = (b1 - b0 + 360) % 360;
    state.sector = {
      b0: cw <= 180 ? b0 : b1,
      b1: cw <= 180 ? b1 : b0,
      r0: Math.max(0, Math.min(drag.from.km, to.km)),
      r1: Math.min(MAX_RADIUS_KM, Math.max(drag.from.km, to.km))
    };
    drawWedge(); readSector(); apply();
  });

  const end = () => {
    if (drag && !drag.moved) { state.sector = null; drawWedge(); readSector(); apply(); }
    drag = null;
  };
  el.addEventListener("pointerup", end);
  el.addEventListener("pointercancel", end);

  document.getElementById("dial-clear").addEventListener("click", () => {
    state.sector = null; drawWedge(); readSector(); apply();
  });

  drawChrome(); drawWedge(); readSector();
}

/* ── detail ────────────────────────────────────────────────────────────────── */

/* Editorial prose is model-written and passes through a validator that checks meaning,
   not markup. It is interpolated into innerHTML below, so it is escaped here: a stray
   angle bracket in a write-up should render as an angle bracket, not as an element. */
const esc = v => String(v ?? "").replace(/[&<>"']/g, ch => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
}[ch]));

async function select(slug) {
  const res = await fetch(`./data/walks/${slug}.json`);
  if (!res.ok) return;
  const w = await res.json();

  // The line is already on the map — apply() drew it. Selecting reframes and highlights it,
  // and swaps the index's simplified geometry for the full-resolution one.
  const latlngs = w.geometry.route.coordinates.map(([lon, lat]) => [lat, lon]);
  const indexed = state.walks.find(x => x.slug === slug);
  if (indexed) indexed.fullLine = latlngs;
  state.selected = slug;
  drawRoutes();
  map.fitBounds(L.latLngBounds(latlngs).pad(0.15));

  const f = w.facts, e = w.editorial, c = w.confidence;
  const amen = f.amenities || {};
  const refreshment = amen.refreshment || [];
  const veg = refreshment.find(r => ["yes", "only"].includes(r.vegan));
  const unsealed = Math.max(0, 100 - (f.surface_mix.sealed_pct ?? 0));

  document.getElementById("detail-body").innerHTML = `
    <h2>${esc(w.name)}</h2>
    <p>${esc(e.summary)}</p>

    <div class="stat-grid">
      <div><span class="k">Distance</span><span>${esc(f.distance_km)} km</span></div>
      <div><span class="k">Ascent</span><span>${esc(f.ascent_m)} m</span></div>
      <div><span class="k">Steepest</span><span>${esc(f.max_sustained_gradient_pct ?? "—")}%</span></div>
      <div><span class="k">By right</span><span>${esc(f.access.by_right_pct)}%</span></div>
      <div><span class="k">Unsealed</span><span>${esc(unsealed)}%</span></div>
      <div><span class="k">Confidence</span><span>${esc(c.navigable)}</span></div>
    </div>

    <h3>Character</h3><p>${esc(e.character)}</p>
    ${e.grain ? `<h3>Grain</h3><p>${esc(e.grain)}</p>` : ""}
    <h3>Conditions</h3><p>${esc(e.conditions)}</p>
    <h3>Practical</h3><p>${esc(e.practical)}</p>
    ${refreshment.length && !veg
        ? `<p><span class="chip">no vegan option recorded</span></p>` : ""}
    <h3>Caveats</h3><p>${esc(e.caveats)}</p>

    <h3>Confidence</h3>
    <p>${esc(c.basis)}</p>
    <p>${c.resolved
        ? `<span class="chip">resolved ${esc(c.resolved.date)}: ${esc(c.resolved.outcome.replace(/_/g, " "))}</span>`
        : `<span class="chip" data-tone="warn">unresolved — not yet walked</span>`}</p>

    <p><small>${esc(w.provenance.attribution.join(" · "))}</small></p>
  `;
  document.getElementById("detail").hidden = false;
  paintSelection();
}

/* A queued area's panel says what is known and stops. There is no route to draw, no
   distance to state and no confidence to quote, so none of those appear — the point of
   showing the queue is to make the site's emptiness legible, not to dress it up. */
function showQueued(slug) {
  const t = state.queue.find(q => q.slug === slug);
  if (!t) return;

  state.selected = null;
  drawRoutes();
  paintSelection();

  document.getElementById("detail-body").innerHTML = `
    <h2>${esc(t.name)}</h2>
    <p><span class="chip" data-tone="warn">awaiting survey</span></p>
    <p>An area in the survey queue, not a walk. Nothing here has been checked against
       OpenStreetMap yet, so there is no route, no distance and no ascent to report — the
       marker sits on a search anchor, and the survey chooses the actual start.</p>

    <div class="stat-grid">
      <div><span class="k">From Stroud</span><span>${esc(t.crow_km)} km ${esc(compass(t.bearing))}</span></div>
      <div><span class="k">Target length</span><span>${esc(t.band_km[0])}–${esc(t.band_km[1])} km</span></div>
      <div><span class="k">Queue position</span><span>${esc(t.priority)}</span></div>
      <div><span class="k">Surveyed</span><span>${t.surveyed ? "yes, not yet written up" : "no"}</span></div>
    </div>

    ${t.notes ? `<h3>Note in the queue</h3><p>${esc(t.notes)}</p>` : ""}

    <h3>What happens next</h3>
    <p>A survey of this area assembles a loop from rights of way and samples its elevation.
       The write-up follows from that survey and nothing else, and reaches the map only after
       it has passed the validator.</p>
  `;
  document.getElementById("detail").hidden = false;
}

/* ── wiring ────────────────────────────────────────────────────────────────── */

function initControls() {
  const bind = (id, key, fmt) => {
    const input = document.getElementById(id);
    const out = document.getElementById(id.replace("f-", "out-"));
    const sync = () => {
      state.filters[key] = Number(input.value);
      out.textContent = fmt(Number(input.value));
      apply();
    };
    input.addEventListener("input", sync);
    sync();
  };

  bind("f-dist", "dist", v => v >= 30 ? "any" : `≤ ${v} km`);
  bind("f-asc",  "asc",  v => v >= 900 ? "any" : `≤ ${v} m`);
  bind("f-grad", "grad", v => v >= 30 ? "any" : `≤ ${v}%`);
  bind("f-surf", "surf", v => v === 0 ? "any" : `≥ ${v}% unsealed`);
  bind("f-tech", "tech", v => v >= 5 ? "any" : `${v} of 5`);
  bind("f-conf", "conf", v => v === 0 ? "any" : `${v}%`);

  document.querySelectorAll("[data-flag]").forEach(cb => {
    cb.addEventListener("change", () => {
      cb.checked ? state.filters.flags.add(cb.dataset.flag)
                 : state.filters.flags.delete(cb.dataset.flag);
      apply();
    });
  });

  document.querySelectorAll("input[name=run]").forEach(r => {
    r.addEventListener("change", () => { state.filters.run = r.value; apply(); });
  });

  const queueToggle = document.getElementById("f-queue");
  if (queueToggle) {
    queueToggle.addEventListener("change", () => {
      state.showQueue = queueToggle.checked;
      apply();
    });
  }

  document.getElementById("detail-close").addEventListener("click", () => {
    document.getElementById("detail").hidden = true;
    state.selected = null;
    drawRoutes();
    paintSelection();
  });

  // Bottom sheet detents on small screens.
  const rail = document.getElementById("rail");
  const grip = document.getElementById("rail-grip");
  const cycle = () => {
    const order = ["peek", "half", "full"];
    const now = rail.dataset.detent || "peek";
    rail.dataset.detent = order[(order.indexOf(now) + 1) % order.length];
  };
  grip.addEventListener("click", cycle);
  grip.addEventListener("keydown", ev => {
    if (ev.key === "Enter" || ev.key === " ") { ev.preventDefault(); cycle(); }
  });
}

async function loadCalibration() {
  const el = document.getElementById("calibration");
  try {
    const s = await (await fetch("./data/calibration.json")).json();
    if (!s.n) { el.textContent = "No walks resolved yet."; return; }
    el.innerHTML =
      `n ${s.n} · Brier ${s.brier}<br>` +
      `reliability ${s.reliability} · resolution ${s.resolution}` +
      (s.n < 10 ? "<br>below n=10, treat as decorative" : "");
  } catch {
    el.textContent = "No walks resolved yet.";
  }
}

/* Says what the map is showing and, when it is showing nothing, why. A corpus of zero is
   the expected state of this site until the first survey runs, and a blank map with no
   explanation is indistinguishable from a broken one. */
function describeState() {
  const note = document.getElementById("state-note");
  if (!note) return;
  if (state.walks.length) { note.hidden = true; return; }
  note.hidden = false;
  note.innerHTML = state.queue.length
    ? `No walks published yet. The hollow markers are the
       <strong id="queue-count">${state.queue.length}</strong> areas in the survey queue;
       each becomes a walk once it has been surveyed, written up and passed the validator.`
    : `No walks published yet, and the survey queue is empty.`;
}

async function loadQueue() {
  try {
    const q = await (await fetch("./data/queue.json")).json();
    state.queue = q.targets || [];
  } catch {
    state.queue = [];            // an older build without a queue payload; not an error
  }
}

async function main() {
  if (typeof L === "undefined") {
    fatal("The map library did not load, so there is no map on this page. " +
          "Reload, and if it persists the deployment is missing site/vendor/leaflet.js.");
    return;
  }
  initMap();
  const data = await (await fetch("./data/walks.json")).json();
  state.walks = data.walks;
  await loadQueue();
  document.getElementById("total").textContent = state.walks.length;
  renderMarkers();
  renderQueue();
  describeState();
  initDial();
  initControls();
  apply();
  loadCalibration();
}

/* Any failure past this point should say so on the page. A blank map with a clean console
   in someone else's browser is the hardest kind of bug to be told about. */
main().catch(err => {
  fatal("Something went wrong loading the walks: " + err.message);
});
