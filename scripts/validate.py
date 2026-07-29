#!/usr/bin/env python3
"""
Stage 3: VALIDATE. The gate. Nothing publishes without passing this.

    python scripts/validate.py data/walks/*.json
    python scripts/validate.py --strict data/walks/*.json     # CI: non-zero exit on any fail

Checks, in order of how much they matter:

  e. hazard disclosure      — every surveyed hazard appears in the caveats
  b. proper-noun allowlist  — no invented pubs, hills, farms or lanes
  d. access consistency     — no right-of-way claim the designations don't support
  c. numeric agreement      — prose numbers match the geometry
  f. imperative voice       — the record isn't drifting into navigation instructions
  g. banned vocabulary      — the stoplist from docs/VOICE.md
  a. JSON Schema            — structural

Loosening a check requires a note in the PR saying what class of error is now permitted.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((ROOT / "schema" / "walk.schema.json").read_text())

BANNED = [
    "hidden gem", "must-see", "must see", "stunning", "breathtaking", "nestled", "boasts",
    "picturesque", "gateway to", "paradise", "oasis", "magical", "iconic",
    "feast for the senses", "tranquil haven", "well worth", "perfect for",
    "something for everyone", "escape the hustle", "not just", "whether you're",
]

# Words that legitimately start a sentence and would otherwise look like an imperative.
IMPERATIVE_VERBS = {
    "turn", "head", "follow", "take", "cross", "climb", "descend", "bear", "keep",
    "continue", "go", "walk", "start", "park", "ignore", "look", "retrace", "join",
}

# Capitalised tokens that are not proper nouns for our purposes.
STOP_CAPS = {
    "The", "A", "An", "This", "That", "These", "Those", "It", "There", "Here", "In", "On",
    "At", "From", "To", "For", "With", "Without", "After", "Before", "Between", "Under",
    "Over", "By", "As", "But", "And", "Or", "If", "When", "Where", "What", "While", "Most",
    "Much", "More", "Less", "No", "Not", "Nothing", "Some", "Any", "Both", "Either",
    "January", "February", "March", "April", "May", "June", "July", "August", "September",
    "October", "November", "December", "Monday", "Tuesday", "Wednesday", "Thursday",
    "Friday", "Saturday", "Sunday", "North", "South", "East", "West", "OpenStreetMap",
    "OS", "PRoW", "Add", "Nearly", "Almost", "Only", "Even", "Once", "Rather", "Neither",
}

PROSE_FIELDS = ("summary", "character", "grain", "conditions", "practical", "caveats")

BY_RIGHT = {"public_footpath", "public_bridleway", "restricted_byway",
            "byway_open_to_all_traffic", "access_land"}


def prose_of(rec: dict) -> str:
    return " ".join(str(rec["editorial"].get(f) or "") for f in PROSE_FIELDS)


def load_gazetteer() -> set[str]:
    path = ROOT / "data" / "gazetteer.txt"
    out: set[str] = set()
    for ln in path.read_text().splitlines():
        ln = ln.strip()
        if ln and not ln.startswith("#"):
            out.add(ln)
            out.update(ln.split())          # accept components: "Golden Valley" → Golden, Valley
    return out


# ------------------------------------------------------------------------------- checks

def check_schema(rec: dict) -> list[str]:
    v = Draft202012Validator(SCHEMA)
    return [f"schema: {'/'.join(str(p) for p in e.path)}: {e.message}"
            for e in v.iter_errors(rec)]


def check_hazards(rec: dict) -> list[str]:
    """The check whose failure mode is not embarrassment. Do not disable."""
    hazards = rec["facts"].get("hazards", [])
    caveats = (rec["editorial"].get("caveats") or "").lower()
    errs = []
    keywords = {
        "major_road_crossing": ["road", "carriageway", "traffic", "a-road"],
        "ford": ["ford", "water"],
        "level_crossing": ["level crossing", "railway", "line"],
        "tidal": ["tide", "tidal"],
        "flood_prone": ["flood", "wet", "inundat"],
        "steep_drop": ["drop", "edge", "cliff", "quarry"],
        "livestock_likely": ["livestock", "cattle", "cow", "sheep", "stock"],
        "barrier": ["gate", "barrier", "stile", "fence"],
    }
    for h in hazards:
        if not any(k in caveats for k in keywords.get(h["kind"], [h["kind"]])):
            errs.append(f"hazard: surveyed '{h['kind']}' is not disclosed in caveats")
    return errs


def check_proper_nouns(rec: dict, gazetteer: set[str]) -> list[str]:
    allowed = set(rec["facts"].get("named_features", [])) | gazetteer
    for n in list(allowed):
        allowed.update(n.split())
    allowed |= STOP_CAPS | {rec["name"], *rec["name"].split()}

    text = prose_of(rec)
    # Strip sentence-initial capitals before extracting, so "The climb" doesn't register.
    candidates = re.findall(r"\b([A-Z][a-z']+(?:\s+[A-Z][a-z']+)*)\b", text)
    unknown = []
    for c in candidates:
        if c in allowed:
            continue
        if all(part in allowed for part in c.split()):
            continue
        # Sentence-initial single word that is otherwise a common word: let it go.
        if " " not in c and re.search(rf"(?:^|[.!?]\s+){re.escape(c)}\b", text):
            continue
        unknown.append(c)
    return [f"proper-noun: '{u}' is in the prose but not in named_features or the gazetteer"
            for u in sorted(set(unknown))]


WORD_NUMBERS = {
    "half": 0.5, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20,
}
NUM = r"(\d+(?:\.\d+)?|" + "|".join(WORD_NUMBERS) + r")"


def _num(tok: str) -> float:
    return WORD_NUMBERS[tok.lower()] if tok.lower() in WORD_NUMBERS else float(tok)


def check_numbers(rec: dict) -> list[str]:
    """
    Prose numbers must agree with the geometry. Models round toward the appealing figure.

    Word-numbers are handled because docs/VOICE.md encourages approximate prose — "about
    four miles" is good writing and must still be checkable. Fractions beyond "half" are
    not parsed; if that starts mattering, the fix is here rather than a looser tolerance.
    """
    errs = []
    text = prose_of(rec)
    km = rec["facts"]["distance_km"]
    ascent = rec["facts"]["ascent_m"]

    pattern = NUM + r"\s*(?:and a half\s*)?(km|kilometre|kilometres|mile|miles)\b"
    for m in re.finditer(pattern, text, re.I):
        val = _num(m.group(1)) + (0.5 if "and a half" in m.group(0).lower() else 0)
        as_km = val * 1.60934 if m.group(2).lower().startswith("mile") else val
        if abs(as_km - km) / km > 0.20:
            errs.append(f"number: prose says {m.group(0)} (~{as_km:.1f} km), geometry says {km} km")

    for m in re.finditer(r"(\d{2,4})\s*(?:m|metres|metre)s?\s+(?:of\s+)?(?:ascent|climb|climbing)",
                         text, re.I):
        val = float(m.group(1))
        if ascent and abs(val - ascent) / max(ascent, 1) > 0.20:
            errs.append(f"number: prose says {val:.0f} m ascent, geometry says {ascent} m")
    return errs


def check_access(rec: dict) -> list[str]:
    """A path being mapped is not a right of way. See docs/DATA.md."""
    by_right = rec["facts"]["access"]["by_right_pct"]
    text = prose_of(rec).lower()
    errs = []
    claims = ["right of way", "public footpath", "public bridleway", "by right",
              "rights of way", "open access"]
    if by_right < 90 and any(c in text for c in claims):
        hedged = any(w in text for w in ["permissive", "unknown", "not a right",
                                         "no designation", "untagged", "unclear",
                                         "may not", "isn't recorded", "not recorded"])
        if not hedged:
            errs.append(
                f"access: only {by_right}% of the route carries a designation, but the prose "
                "claims rights of way without qualification"
            )
    return errs


def check_imperatives(rec: dict) -> list[str]:
    errs = []
    for field in PROSE_FIELDS:
        text = rec["editorial"].get(field) or ""
        for sent in re.split(r"(?<=[.!?])\s+", text):
            first = re.match(r"([A-Za-z]+)", sent.strip())
            if first and first.group(1).lower() in IMPERATIVE_VERBS:
                errs.append(f"voice: '{field}' has a sentence-initial imperative: "
                            f"\"{sent.strip()[:60]}…\"")
    return errs


def check_banned(rec: dict) -> list[str]:
    text = prose_of(rec).lower()
    return [f"voice: banned phrase '{b}'" for b in BANNED if b in text]


def check_confidence(rec: dict) -> list[str]:
    """Not a pass/fail — a nudge. Flat confidence across a corpus is a real defect."""
    c = rec["confidence"]["navigable"]
    if len(rec["confidence"]["basis"]) < 40:
        return ["confidence: basis is too thin to be a real justification"]
    if 0.79 <= c <= 0.81:
        return ["confidence: 0.80 exactly — check this is a judgement and not an anchor "
                "(warning only)"]
    return []


# --------------------------------------------------------------------------------- main

def validate(path: Path, gazetteer: set[str]) -> tuple[bool, dict[str, list[str]]]:
    rec = json.loads(path.read_text())
    results = {
        "schema": check_schema(rec),
        "hazards": check_hazards(rec),
        "proper_nouns": check_proper_nouns(rec, gazetteer),
        "numbers": check_numbers(rec),
        "access": check_access(rec),
        "imperatives": check_imperatives(rec),
        "banned": check_banned(rec),
        "confidence": check_confidence(rec),
    }
    hard = {k: v for k, v in results.items() if v and k != "confidence"}
    passed = not hard and rec.get("status") != "seed"

    rec.setdefault("provenance", {})["validation"] = {
        "passed": passed,
        "checks": {k: ("ok" if not v else "; ".join(v)[:300]) for k, v in results.items()},
    }
    if rec.get("status") in ("draft", "needs-review", "published"):
        rec["status"] = "published" if passed else "needs-review"
    path.write_text(json.dumps(rec, indent=2, ensure_ascii=False))
    return passed, results


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--strict", action="store_true", help="exit non-zero on any failure")
    args = ap.parse_args()

    gazetteer = load_gazetteer()
    any_failed = False

    for p in args.paths:
        passed, results = validate(p, gazetteer)
        mark = "PASS" if passed else "FAIL"
        print(f"\n{mark}  {p.name}")
        for check, errs in results.items():
            for e in errs:
                print(f"       {e}")
        if not passed:
            any_failed = True

    if any_failed:
        print("\nRecords marked needs-review. Widen the survey or tighten the prompt; "
              "loosening a check needs a note in the PR.")
    sys.exit(1 if (any_failed and args.strict) else 0)


if __name__ == "__main__":
    main()
