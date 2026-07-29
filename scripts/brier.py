#!/usr/bin/env python3
"""
Beating the Bounds: score the generator's stated navigability against what actually happened.

    python scripts/brier.py                 # report to stdout
    python scripts/brier.py --write         # also emit site/data/calibration.json

Reads data/ledger.json and the published walks. Outcome coding:

    walked_as_described → 1
    diverged            → 0
    failed              → 0
    not_attempted       → excluded

`diverged` scoring as 0 is deliberate and slightly harsh. The forecast is "follows this as
written, without backtracking or access problem" — a route you completed by ignoring the
write-up did not vindicate the write-up.

Murphy decomposition:   BS = REL − RES + UNC

    REL  reliability   — mean squared gap between stated probability and observed rate in bin
    RES  resolution    — how far bin rates depart from base rate; this is the informative term
    UNC  uncertainty   — base rate variance; a property of the corpus, not the generator

A generator that says 0.85 to everything scores well on REL and zero on RES. That is the
failure mode the decomposition exists to expose, so read RES first.
"""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LEDGER = ROOT / "data" / "ledger.json"
WALKS = ROOT / "data" / "walks"
OUT = ROOT / "site" / "data" / "calibration.json"

SCORE = {"walked_as_described": 1, "diverged": 0, "failed": 0}
BINS = [(i / 10, (i + 1) / 10) for i in range(10)]


def collect() -> list[tuple[str, float, int]]:
    """→ [(slug, forecast, outcome)] for resolved walks only."""
    entries = json.loads(LEDGER.read_text()).get("entries", [])
    latest = {}
    for e in entries:                       # append-only ledger; last word wins
        if e.get("outcome") in SCORE:
            latest[e["slug"]] = e

    out = []
    for p in WALKS.glob("*.json"):
        r = json.loads(p.read_text())
        e = latest.get(r["slug"])
        if e and r.get("status") == "published":
            out.append((r["slug"], r["confidence"]["navigable"], SCORE[e["outcome"]]))
    return out


def decompose(pairs: list[tuple[str, float, int]]) -> dict:
    n = len(pairs)
    if n == 0:
        return {"n": 0}

    bs = sum((f - o) ** 2 for _, f, o in pairs) / n
    base = sum(o for _, _, o in pairs) / n
    unc = base * (1 - base)

    buckets: dict[tuple[float, float], list[tuple[float, int]]] = defaultdict(list)
    for _, f, o in pairs:
        for lo, hi in BINS:
            if lo <= f < hi or (hi == 1.0 and f == 1.0):
                buckets[(lo, hi)].append((f, o))
                break

    rel = res = 0.0
    diagram = []
    for (lo, hi), members in sorted(buckets.items()):
        k = len(members)
        mean_f = sum(f for f, _ in members) / k
        obs = sum(o for _, o in members) / k
        rel += k * (mean_f - obs) ** 2
        res += k * (obs - base) ** 2
        diagram.append({"bin": f"{lo:.1f}–{hi:.1f}", "n": k,
                        "mean_forecast": round(mean_f, 3), "observed": round(obs, 3)})
    rel /= n
    res /= n

    return {
        "n": n,
        "brier": round(bs, 4),
        "reliability": round(rel, 4),
        "resolution": round(res, 4),
        "uncertainty": round(unc, 4),
        "base_rate": round(base, 3),
        "identity_check": round(rel - res + unc, 4),      # should equal brier
        "reliability_diagram": diagram,
        "worst": sorted(
            [{"slug": s, "forecast": f, "outcome": o, "loss": round((f - o) ** 2, 3)}
             for s, f, o in pairs],
            key=lambda d: -d["loss"],
        )[:5],
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--write", action="store_true")
    args = ap.parse_args()

    pairs = collect()
    stats = decompose(pairs)

    if stats["n"] == 0:
        print("No resolved walks yet. Nothing to score — go for a walk.")
    else:
        print(f"n = {stats['n']}   base rate = {stats['base_rate']}")
        print(f"Brier       {stats['brier']}")
        print(f"  reliability  {stats['reliability']}   (lower better — are you calibrated)")
        print(f"  resolution   {stats['resolution']}   (HIGHER better — are you informative)")
        print(f"  uncertainty  {stats['uncertainty']}   (corpus property, not yours)")
        print(f"  identity     {stats['identity_check']} vs {stats['brier']}")
        if stats["n"] < 10:
            print("\n  Treat all of the above as decorative below n=10.")
        if stats["resolution"] < 0.01 and stats["n"] >= 10:
            print("\n  Resolution near zero: the generator is not discriminating between "
                  "walks. Check whether confidence.navigable is anchored.")

    if args.write:
        OUT.parent.mkdir(parents=True, exist_ok=True)
        OUT.write_text(json.dumps(stats, indent=1))
        print(f"\n→ {OUT}")


if __name__ == "__main__":
    main()
