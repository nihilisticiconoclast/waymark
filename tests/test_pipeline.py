#!/usr/bin/env python3
"""
The invariants, as executable checks.

    python -m unittest discover -s tests -v

Every test here corresponds to a numbered invariant in CLAUDE.md or to a check the
architecture argues for by name. They exist because the gate is the only thing standing
between a plausible sentence and a walker in the wrong field, and a gate nobody tests is
a gate that quietly stops closing.

Nothing in this file touches the network. The survey tests run against a synthetic graph
rather than Overpass, which is the only way to exercise the loop assembler at all — it is
the weakest part of the pipeline and, before this, the least observable.
"""

from __future__ import annotations

import copy
import json
import math
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

import brier                                                          # noqa: E402
import build_index                                                    # noqa: E402
import survey                                                         # noqa: E402
import validate                                                       # noqa: E402


# --------------------------------------------------------------------------- fixtures

def a_record(**overrides) -> dict:
    """
    A record that passes every check, to be broken one field at a time.

    The prose deliberately uses only 'Haresfield Beacon', which the fixture's
    named_features supplies, plus gazetteer terms — so a proper-noun failure in a test
    below is the change under test and not fixture drift.
    """
    rec = {
        "id": 1,
        "slug": "test-walk",
        "name": "Haresfield Beacon",
        "status": "draft",
        "geometry": {
            "start": {"lat": 51.7845, "lon": -2.2870},
            "route": {"type": "LineString",
                      "coordinates": [[-2.2870, 51.7845], [-2.2851, 51.7863]]},
            "closed": True,
        },
        "facts": {
            "distance_km": 8.0,
            "ascent_m": 240,
            "access": {
                "by_right_pct": 100.0,
                "segments": [{"designation": "public_footpath", "length_m": 8000.0}],
            },
            "surface_mix": {"sealed_pct": 10.0, "firm_pct": 40.0, "soft_pct": 50.0,
                            "untagged_pct": 0.0},
            "hazards": [],
            "named_features": ["Haresfield Beacon"],
        },
        "editorial": {
            "summary": "A loop on the escarpment above the Severn Vale, north-west of town.",
            "character": (
                "The climb is short and sits almost entirely in the second kilometre, "
                "which makes it a poor warm-up and a good place to be honest about pacing. "
                "Above the break of slope the going is firm; below it the ground holds "
                "water and stays greasy for days. It is a good walk rather than a "
                "remarkable one."
            ),
            "grain": (
                "The bench the path follows is the Inferior Oolite resting on the Lias, "
                "which is why the slope below it slips and the top stays dry."
            ),
            "conditions": (
                "Best in hard light between October and March, when the beeches are bare "
                "and the Severn Vale is legible from the edge. After a wet week the lower "
                "field sections are heavy."
            ),
            "practical": (
                "Parking is unmapped in the survey payload, so nothing is claimed about it. "
                "No refreshment was found within reach of the route, and no vegan provision "
                "can therefore be stated either way."
            ),
            "caveats": (
                "The survey found no hazards on this route, which is a weaker claim than "
                "there being none: unmapped stiles and gates are invisible to it."
            ),
            "best_months": [10, 11, 12, 1, 2, 3],
            "runnable": "mostly",
        },
        "ratings": {"difficulty": 3, "technicality": 2, "exposure": 2, "solitude": 3},
        "confidence": {
            "navigable": 0.88,
            "basis": ("Complete public footpath coverage over the whole length, with surface "
                      "tags on four fifths of it and no unmapped field-edge sections."),
            "resolved": None,
        },
        "provenance": {
            "method": "survey+author",
            "surveyed_at": "2026-07-29T00:00:00Z",
            "attribution": ["Route and feature data © OpenStreetMap contributors, ODbL"],
        },
    }
    for key, value in overrides.items():
        rec[key] = value
    return rec


def gazetteer() -> set[str]:
    return validate.load_gazetteer()


def run_checks(rec: dict) -> dict[str, list[str]]:
    """Every check validate.validate() treats as hard, without touching the filesystem."""
    return {
        "schema": validate.check_schema(rec),
        "hazards": validate.check_hazards(rec),
        "proper_nouns": validate.check_proper_nouns(rec, gazetteer()),
        "numbers": validate.check_numbers(rec),
        "access": validate.check_access(rec),
        "imperatives": validate.check_imperatives(rec),
        "banned": validate.check_banned(rec),
        "status": validate.check_status(rec),
    }


# --------------------------------------------------------------------------- the gate

class TestTheFixtureIsClean(unittest.TestCase):
    def test_a_good_record_passes_every_check(self):
        failures = {k: v for k, v in run_checks(a_record()).items() if v}
        self.assertEqual(failures, {}, f"fixture is not clean: {failures}")


class TestHazardDisclosure(unittest.TestCase):
    """Invariant: a surveyed hazard that is not disclosed fails the build."""

    def test_undisclosed_hazard_fails(self):
        rec = a_record()
        rec["facts"]["hazards"] = [
            {"kind": "major_road_crossing", "detail": "Crosses a primary road."}]
        self.assertTrue(validate.check_hazards(rec))

    def test_disclosed_hazard_passes(self):
        rec = a_record()
        rec["facts"]["hazards"] = [
            {"kind": "major_road_crossing", "detail": "Crosses a primary road."}]
        rec["editorial"]["caveats"] = (
            "The route meets a main road with no mapped crossing, and the traffic there is "
            "fast. Nothing else was flagged by the survey."
        )
        self.assertEqual(validate.check_hazards(rec), [])

    def test_every_schema_hazard_kind_has_disclosure_keywords(self):
        """A kind with no keywords would be undisclosable — silently unenforceable."""
        schema = json.loads((ROOT / "schema" / "walk.schema.json").read_text())
        kinds = (schema["properties"]["facts"]["properties"]["hazards"]
                 ["items"]["properties"]["kind"]["enum"])
        rec = a_record()
        for kind in kinds:
            with self.subTest(kind=kind):
                rec["facts"]["hazards"] = [{"kind": kind, "detail": "x"}]
                rec["editorial"]["caveats"] = "Nothing was flagged by the survey at all."
                self.assertTrue(validate.check_hazards(rec),
                                f"hazard kind '{kind}' cannot be detected as undisclosed")


class TestProperNouns(unittest.TestCase):
    """Invariant: Claude never names anything the survey didn't find."""

    def test_invented_pub_fails(self):
        rec = a_record()
        rec["editorial"]["practical"] = (
            "The Wheatsheaf Arms sits at the halfway point and does a vegan option, which "
            "makes the second half of this walk considerably more attractive than the first."
        )
        errs = validate.check_proper_nouns(rec, gazetteer())
        self.assertTrue(any("Wheatsheaf" in e for e in errs))

    def test_surveyed_name_passes(self):
        rec = a_record()
        rec["facts"]["named_features"] = ["Haresfield Beacon", "The Black Horse"]
        rec["editorial"]["practical"] = (
            "The Black Horse is the only refreshment within reach of the route, and the "
            "survey records no vegan provision there either way."
        )
        self.assertEqual(validate.check_proper_nouns(rec, gazetteer()), [])

    def test_gazetteer_name_passes(self):
        rec = a_record()
        rec["editorial"]["grain"] = (
            "The Stroudwater Navigation in the valley floor is the reason for the mills, "
            "and the mills are the reason for the lanes."
        )
        self.assertEqual(validate.check_proper_nouns(rec, gazetteer()), [])


class TestAccessConsistency(unittest.TestCase):
    """Invariant: access rights are asserted only from designation tags."""

    def test_unqualified_right_of_way_claim_on_undesignated_route_fails(self):
        rec = a_record()
        rec["facts"]["access"]["by_right_pct"] = 22.0
        rec["editorial"]["character"] = (
            "The whole loop is a public footpath and stays that way to the road, so there "
            "is nothing to think about on the ground beyond the surface underfoot."
        )
        self.assertTrue(validate.check_access(rec))

    def test_hedged_claim_passes(self):
        rec = a_record()
        rec["facts"]["access"]["by_right_pct"] = 22.0
        rec["editorial"]["character"] = (
            "Only the first stretch is a public footpath; the rest is mapped but carries no "
            "designation, so it is permissive at best and its status is unknown."
        )
        self.assertEqual(validate.check_access(rec), [])


class TestNumericAgreement(unittest.TestCase):
    """Prose numbers must agree with the geometry, in words as well as digits."""

    def test_word_number_disagreeing_with_geometry_fails(self):
        rec = a_record()                                  # 8.0 km ≈ five miles
        rec["editorial"]["summary"] = "A walk of about two miles on the escarpment edge."
        self.assertTrue(validate.check_numbers(rec))

    def test_word_number_agreeing_with_geometry_passes(self):
        rec = a_record()
        rec["editorial"]["summary"] = "A walk of about five miles on the escarpment edge."
        self.assertEqual(validate.check_numbers(rec), [])

    def test_inflated_ascent_fails(self):
        rec = a_record()                                  # 240 m
        rec["editorial"]["character"] = (
            "There is 600 m of ascent in the loop, all of it in one sustained pull, and the "
            "gradient never really relents until the top."
        )
        self.assertTrue(validate.check_numbers(rec))


class TestVoice(unittest.TestCase):
    """Invariant: directions describe, they do not instruct."""

    def test_sentence_initial_imperative_fails(self):
        rec = a_record()
        rec["editorial"]["conditions"] = (
            "Cross the field to the far corner and pick up the track beyond it. The going "
            "is firm once the ground rises above the break of slope."
        )
        self.assertTrue(validate.check_imperatives(rec))

    def test_descriptive_equivalent_passes(self):
        rec = a_record()
        rec["editorial"]["conditions"] = (
            "The crossing of the field runs to its far corner, where a track picks up. The "
            "going is firm once the ground rises above the break of slope."
        )
        self.assertEqual(validate.check_imperatives(rec), [])

    def test_banned_vocabulary_fails(self):
        rec = a_record()
        rec["editorial"]["summary"] = "A hidden gem of a walk on the escarpment edge."
        self.assertTrue(validate.check_banned(rec))


class TestStatusGate(unittest.TestCase):
    def test_seed_records_never_publish(self):
        self.assertTrue(validate.check_status(a_record(status="seed")))

    def test_draft_records_are_publishable(self):
        self.assertEqual(validate.check_status(a_record(status="draft")), [])

    def test_every_shipped_record_passes_the_gate(self):
        """
        Not a fixture — the records actually on the site. A published record that would
        fail the gate today means the gate changed and the corpus did not.
        """
        shipped = sorted((ROOT / "data" / "walks").glob("*.json"))
        self.assertTrue(shipped, "no walk records in the repo")
        for path in shipped:
            with self.subTest(record=path.name):
                rec = json.loads(path.read_text())
                failures = {k: v for k, v in run_checks(rec).items() if v}
                self.assertEqual(failures, {}, f"{path.name} would not pass today: {failures}")
                self.assertEqual(rec["status"], "published")

    def test_strict_mode_tolerates_a_seed_but_not_a_bad_draft(self):
        """
        The CI contract. A seed must not redden every pull request — that pressure is how
        gates get weakened — and a draft that fails a check must stop the build.
        """
        import subprocess
        import tempfile

        cli = [sys.executable, str(ROOT / "scripts" / "validate.py"), "--strict"]
        with tempfile.TemporaryDirectory() as tmp:
            seed = Path(tmp) / "seed.json"
            seed.write_text(json.dumps(a_record(status="seed")))
            self.assertEqual(subprocess.run(cli + [str(seed)]).returncode, 0)

            bad = Path(tmp) / "bad.json"
            broken = a_record()
            broken["editorial"]["summary"] = "A hidden gem of a walk on the escarpment edge."
            bad.write_text(json.dumps(broken))
            self.assertEqual(subprocess.run(cli + [str(bad)]).returncode, 1)
            self.assertEqual(json.loads(bad.read_text())["status"], "needs-review")


class TestSchemaRejectsModelWrittenFacts(unittest.TestCase):
    """Invariant: the model's output is confined to editorial, ratings and confidence."""

    def test_unknown_top_level_branch_is_rejected(self):
        rec = a_record()
        rec["route_description"] = "Head north from the car park."
        self.assertTrue(validate.check_schema(rec))

    def test_coordinate_smuggled_into_editorial_is_rejected(self):
        rec = a_record()
        rec["editorial"]["start_latlon"] = [51.78, -2.28]
        self.assertTrue(validate.check_schema(rec))

    def test_confidence_of_zero_or_one_is_rejected(self):
        for value in (0, 1):
            with self.subTest(navigable=value):
                rec = a_record()
                rec["confidence"]["navigable"] = value
                self.assertTrue(validate.check_schema(rec))


# --------------------------------------------------------------------------- the survey

def square_ways(centre: tuple[float, float], side_km: float, step_m: float = 100.0):
    """
    Overpass-shaped ways forming a closed square of the requested side, subdivided so the
    graph has nodes at realistic spacing. Tagged as a public footpath on three sides and an
    undesignated path on the fourth, so the designation roll-up has something to roll up.
    """
    lat, lon = centre
    dlat = side_km / 111.0
    dlon = side_km / (111.0 * math.cos(math.radians(lat)))
    corners = [(lat, lon), (lat + dlat, lon), (lat + dlat, lon + dlon), (lat, lon + dlon)]

    ways = []
    for i, (a, b) in enumerate(zip(corners, corners[1:] + corners[:1])):
        n = max(2, int(side_km * 1000 / step_m))
        geom = [{"lat": a[0] + (b[0] - a[0]) * t / n, "lon": a[1] + (b[1] - a[1]) * t / n}
                for t in range(n + 1)]
        tags = ({"highway": "footway", "designation": "public_footpath", "surface": "grass"}
                if i < 3 else {"highway": "path"})
        ways.append({"type": "way", "id": 1000 + i, "geometry": geom, "tags": tags})
    return ways


class TestLoopAssembly(unittest.TestCase):
    """
    Loop-finding is the hard part of survey.py, and a naive shortest path returns an
    out-and-back. These are the two properties that distinguish the two.
    """

    CENTRE = (51.7845, -2.2870)

    def setUp(self):
        self.graph = survey.build_graph(square_ways(self.CENTRE, side_km=1.0))

    def test_graph_joins_ways_that_share_endpoints(self):
        self.assertTrue(self.graph.number_of_nodes() > 30)
        self.assertEqual(len(list(__import__("networkx").connected_components(self.graph))), 1)

    def test_finds_a_loop_inside_the_requested_band(self):
        loop = survey.find_loop(self.graph, self.CENTRE, (3.5, 4.5))
        self.assertIsNotNone(loop, "no loop found on a graph that is nothing but a loop")
        total = sum(self.graph[u][v]["length"] for u, v in zip(loop, loop[1:]))
        self.assertGreaterEqual(total, 3500)
        self.assertLessEqual(total, 4500)

    def test_the_loop_returns_to_its_start(self):
        loop = survey.find_loop(self.graph, self.CENTRE, (3.5, 4.5))
        self.assertLess(survey.haversine_m(loop[0], loop[-1]), 150)

    def test_the_loop_is_not_an_out_and_back(self):
        loop = survey.find_loop(self.graph, self.CENTRE, (3.5, 4.5))
        edges = [frozenset(e) for e in zip(loop, loop[1:])]
        self.assertLess(len(edges) - len(set(edges)), 0.1 * len(edges),
                        "more than a tenth of the loop is walked twice")

    def test_out_of_band_request_finds_nothing_rather_than_forcing_it(self):
        self.assertIsNone(survey.find_loop(self.graph, self.CENTRE, (20.0, 30.0)))

    def test_an_orphan_fragment_at_the_anchor_does_not_capture_the_search(self):
        """
        Regression, and the one that actually stopped the first real survey.

        An Overpass extract is mostly fragments: driveway stubs, paths that leave the bbox
        and come back, footways drawn as their own islands. The start used to be the node
        geometrically nearest the anchor, which on a real extract of 4,145 ways was a
        two-node stub — so the search explored a graph 100 m across and reported that no
        loop existed. That is true of the stub and false of the place.
        """
        lat, lon = self.CENTRE
        ways = square_ways((lat + 0.01, lon + 0.01), side_km=1.0)      # the real network
        ways.append({                                                   # a stub on the anchor
            "type": "way", "id": 9999, "tags": {"highway": "service"},
            "geometry": [{"lat": lat, "lon": lon},
                         {"lat": lat + 0.0005, "lon": lon}],
        })
        graph = survey.build_graph(ways)
        self.assertGreater(__import__("networkx").number_connected_components(graph), 1)

        loop = survey.find_loop(graph, self.CENTRE, (3.5, 4.5))
        self.assertIsNotNone(loop, "the orphan stub captured the search")
        total = sum(graph[u][v]["length"] for u, v in zip(loop, loop[1:]))
        self.assertGreaterEqual(total, 3500)

    def test_the_band_is_reachable_at_every_scale(self):
        """
        Regression. The turning point used to be sought at 0.20–0.35 of the target, which
        caps an assembled loop at roughly 0.4–0.7 of the band — so a correctly specified
        target returned "no loop found" and the response was to widen the queue entry until
        the numbers happened to line up. The turning point belongs near half the target:
        on a loop of circumference L the far side is L/2 away by the shorter arc.
        """
        for side_km, band in [(1.0, (3.5, 4.5)), (1.5, (5.0, 7.0)), (2.0, (7.0, 9.0))]:
            with self.subTest(side_km=side_km, band=band):
                graph = survey.build_graph(square_ways(self.CENTRE, side_km=side_km))
                loop = survey.find_loop(graph, self.CENTRE, band)
                self.assertIsNotNone(loop, f"no loop in {band} km on a {side_km * 4} km circuit")
                total = sum(graph[u][v]["length"] for u, v in zip(loop, loop[1:])) / 1000
                self.assertGreaterEqual(total, band[0])
                self.assertLessEqual(total, band[1])


class TestRoutePreference(unittest.TestCase):
    """
    These are walking directions. The assembler minimises a weighted cost, not raw length,
    so a right of way beats a lane even when the lane is shorter — which is the whole point
    and the opposite of what a driving router would do.
    """

    def test_a_right_of_way_beats_a_shorter_lane(self):
        cheap = survey.classify({"highway": "footway", "designation": "public_footpath"}, False)
        lane = survey.classify({"highway": "unclassified"}, False)
        self.assertEqual(cheap, "prow")
        self.assertEqual(lane, "unclassified")
        # A kilometre of lane must cost more than five kilometres of footpath.
        self.assertGreater(survey.COST_MULTIPLIER[lane],
                           5 * survey.COST_MULTIPLIER[cheap])

    def test_the_assembler_takes_the_longer_path_over_the_road(self):
        """A road shortcut and a longer footpath between the same two points."""
        lat, lon = 51.7845, -2.2870
        d = 0.009
        def leg(pts, tags, wid):
            return {"type": "way", "id": wid, "tags": tags,
                    "geometry": [{"lat": p[0], "lon": p[1]} for p in pts]}
        a, b = (lat, lon), (lat + d, lon)
        road = [a, (lat + d / 2, lon), b]                          # straight, short
        path = [a, (lat + d / 3, lon + d), (lat + 2 * d / 3, lon + d), b]   # dog-leg, long
        graph = survey.build_graph([
            leg(road, {"highway": "unclassified"}, 1),
            leg(path, {"highway": "footway", "designation": "public_footpath"}, 2),
        ])
        import networkx as nx
        chosen = nx.shortest_path(graph, min(graph.nodes, key=lambda n: survey.haversine_m(n, a)),
                                  min(graph.nodes, key=lambda n: survey.haversine_m(n, b)),
                                  weight="cost")
        kinds = {graph[u][v]["kind"] for u, v in zip(chosen, chosen[1:])}
        self.assertIn("prow", kinds)
        self.assertNotIn("unclassified", kinds, "the router took the road")

    def test_open_access_land_confers_a_right_the_way_does_not_carry(self):
        """
        A path with no designation, inside National Trust open land, is walkable by right.
        Reading the way alone reports an escarpment common as 'unknown'.
        """
        tags = {"highway": "path"}
        self.assertEqual(survey.classify(tags, False), "path")
        self.assertEqual(survey.classify(tags, True), "access_land")
        self.assertIn("access_land", survey.BY_RIGHT_CLASSES)
        self.assertNotIn("path", survey.BY_RIGHT_CLASSES)

    def test_a_lane_inside_access_land_is_still_a_lane(self):
        """Open access is a right to roam over land, not a reclassification of the road."""
        self.assertEqual(survey.classify({"highway": "unclassified"}, True), "unclassified")

    def test_access_polygons_ignore_unclosed_ways(self):
        """A boundary fragment is not an area, and must not be guessed into one."""
        closed = {"type": "way", "id": 1, "geometry": [
            {"lat": 51.78, "lon": -2.29}, {"lat": 51.79, "lon": -2.29},
            {"lat": 51.79, "lon": -2.28}, {"lat": 51.78, "lon": -2.29}]}
        open_way = {"type": "way", "id": 2, "geometry": [
            {"lat": 51.70, "lon": -2.20}, {"lat": 51.71, "lon": -2.20},
            {"lat": 51.71, "lon": -2.19}, {"lat": 51.72, "lon": -2.18}]}
        from shapely.geometry import Point
        area = survey.access_polygons([closed, open_way])
        self.assertIsNotNone(area)
        self.assertTrue(area.contains(Point(-2.2887, 51.7867)))
        self.assertFalse(area.contains(Point(-2.195, 51.710)))
        self.assertIsNone(survey.access_polygons([open_way]))


class TestRouteRollUp(unittest.TestCase):
    def test_designation_and_surface_are_apportioned_by_length(self):
        graph = survey.build_graph(square_ways((51.7845, -2.2870), side_km=1.0))
        loop = survey.find_loop(graph, (51.7845, -2.2870), (3.5, 4.5))
        attrs = survey.summarise_route(graph, loop)

        designations = {s["designation"] for s in attrs["segments"]}
        self.assertIn("public_footpath", designations)
        self.assertIn("unknown", designations,
                      "an undesignated path must not be counted as a right of way")
        # Three sides designated, one not: by-right share should be near three quarters.
        self.assertAlmostEqual(attrs["by_right_pct"], 75.0, delta=6.0)
        self.assertAlmostEqual(attrs["surface_mix"]["soft_pct"], 75.0, delta=6.0)


class TestElevation(unittest.TestCase):
    def test_threshold_suppresses_dem_noise(self):
        flat = [[i / 10, 100 + (i % 2)] for i in range(60)]     # ±1 m jitter, no real climb
        self.assertEqual(survey.ascent_descent(flat), (0, 0))

    def test_real_climb_is_counted_once(self):
        profile = [[0.0, 100], [0.5, 150], [1.0, 200], [1.5, 150], [2.0, 100]]
        up, down = survey.ascent_descent(profile)
        self.assertEqual((up, down), (100, 100))

    def test_sustained_gradient_ignores_short_pitches(self):
        # 20 m of climb in 50 m of run, then flat: steep, but not sustained over 200 m.
        profile = [[0.0, 100], [0.05, 120]] + [[0.05 + i * 0.1, 120] for i in range(1, 10)]
        self.assertLess(survey.max_sustained_gradient(profile, window_m=200.0), 10.0)


class TestPointExtraction(unittest.TestCase):
    """Ways and relations must be located as reliably as nodes; hazards arrive as ways."""

    def test_node_way_and_relation_shapes(self):
        loop = [(51.7845, -2.2870), (51.7846, -2.2871)]
        payloads = [
            {"type": "node", "id": 1, "lat": 51.7845, "lon": -2.2870},
            {"type": "way", "id": 2, "geometry": [{"lat": 51.7845, "lon": -2.2870},
                                                  {"lat": 51.7900, "lon": -2.2900}]},
            {"type": "relation", "id": 3, "center": {"lat": 51.7845, "lon": -2.2870}},
        ]
        for p in payloads:
            with self.subTest(kind=p["type"]):
                pts = ([(p["lat"], p["lon"])] if p.get("lat") is not None
                       else [(p["center"]["lat"], p["center"]["lon"])] if p.get("center")
                       else [(g["lat"], g["lon"]) for g in p["geometry"]])
                self.assertTrue(pts)
                self.assertLess(min(survey.haversine_m(pt, n) for pt in pts for n in loop), 30)


# --------------------------------------------------------------------------- calibration

class TestBrier(unittest.TestCase):
    def test_murphy_identity_holds(self):
        pairs = [("a", 0.9, 1), ("b", 0.8, 1), ("c", 0.55, 0), ("d", 0.3, 0),
                 ("e", 0.95, 1), ("f", 0.4, 1), ("g", 0.75, 0), ("h", 0.6, 1)]
        s = brier.decompose(pairs)
        self.assertAlmostEqual(s["identity_check"], s["brier"], places=3)

    def test_a_flat_forecaster_shows_no_resolution(self):
        """The failure mode the decomposition exists to expose."""
        pairs = [(str(i), 0.8, i % 2) for i in range(10)]
        self.assertAlmostEqual(brier.decompose(pairs)["resolution"], 0.0, places=6)

    def test_a_discriminating_forecaster_shows_resolution(self):
        pairs = [("a", 0.95, 1), ("b", 0.9, 1), ("c", 0.92, 1),
                 ("d", 0.2, 0), ("e", 0.15, 0), ("f", 0.25, 0)]
        self.assertGreater(brier.decompose(pairs)["resolution"], 0.2)

    def test_diverged_and_failed_both_score_zero(self):
        self.assertEqual(brier.SCORE["diverged"], 0)
        self.assertEqual(brier.SCORE["failed"], 0)
        self.assertNotIn("not_attempted", brier.SCORE)

    def test_empty_ledger_is_not_an_error(self):
        self.assertEqual(brier.decompose([]), {"n": 0})


# --------------------------------------------------------------------------- the index

class TestIndexBuild(unittest.TestCase):
    def test_unsealed_share_is_everything_that_is_not_sealed(self):
        """
        The site filters on 'unsealed', and the index has to carry enough to compute it.
        A firm limestone track is unsealed; reading soft_pct alone loses it.
        """
        rec = a_record()
        mix = rec["facts"]["surface_mix"]
        self.assertEqual(100 - mix["sealed_pct"], mix["firm_pct"] + mix["soft_pct"])


class TestQueuePayload(unittest.TestCase):
    """
    The queue is shown on the map so an empty corpus reads as empty rather than broken.
    That only stays honest if a queued area can never be confused with a surveyed one.
    """

    def test_a_queued_area_carries_no_surveyed_facts(self):
        forbidden = {"distance_km", "ascent_m", "descent_m", "route", "geometry",
                     "confidence", "surface_mix", "by_right_pct", "hazards", "editorial",
                     "gradient_pct", "max_sustained_gradient_pct"}
        for t in build_index.build_queue(set())["targets"]:
            with self.subTest(slug=t["slug"]):
                self.assertEqual(forbidden & set(t), set(),
                                 "a queued area is advertising facts no survey has produced")

    def test_published_slugs_leave_the_queue(self):
        """Otherwise a walk would appear twice: once real, once as a pending marker."""
        all_slugs = {t["slug"] for t in build_index.build_queue(set())["targets"]}
        self.assertIn("haresfield-beacon", all_slugs)
        remaining = {t["slug"] for t in build_index.build_queue({"haresfield-beacon"})["targets"]}
        self.assertNotIn("haresfield-beacon", remaining)
        self.assertEqual(len(remaining), len(all_slugs) - 1)

    def test_queue_is_ordered_by_priority(self):
        priorities = [t["priority"] for t in build_index.build_queue(set())["targets"]]
        self.assertEqual(priorities, sorted(priorities))

    def test_bearings_and_distances_are_computed_not_copied(self):
        """The dial places these; a wrong bearing puts an area in the wrong quadrant."""
        for t in build_index.build_queue(set())["targets"]:
            with self.subTest(slug=t["slug"]):
                self.assertEqual(t["crow_km"],
                                 round(build_index.haversine_km(build_index.ORIGIN,
                                                                (t["lat"], t["lon"])), 1))
                self.assertEqual(t["bearing"],
                                 round(build_index.bearing(build_index.ORIGIN,
                                                           (t["lat"], t["lon"]))))
                self.assertGreaterEqual(t["bearing"], 0)
                self.assertLess(t["bearing"], 360)


if __name__ == "__main__":
    unittest.main()
