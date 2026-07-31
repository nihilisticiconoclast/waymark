#!/usr/bin/env python3
"""
Stage 2: AUTHOR. Claude writes prose and a calibrated confidence, and nothing else.

Two ways in, and the first is the normal one:

    # 1. Claude is already here — in a Claude Code session or a Routine — and has written the
    #    editorial block against the survey. No key, no API call, no billing.
    python scripts/author.py --survey data/surveys/haresfield-beacon.json \
                             --editorial data/editorial/haresfield-beacon.json

    # 2. Unattended, for the scheduled job, where no session exists to write it.
    ANTHROPIC_API_KEY=... python scripts/author.py --survey data/surveys/haresfield-beacon.json

Mode 1 exists because reaching for the API to do this is silly when the model reading the
survey and writing the record is the one running the command. The constraints are identical
either way — they live in prompts/author-system.md, docs/VOICE.md, and the validator — and the
validator is what actually enforces them. It does not care which mode produced the words.

Either way the model sees the survey payload and the permitted proper nouns and nothing else.
If the write-up is thin, the survey was thin, and that is the correct signal — widen the
Overpass query rather than loosening this stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WALKS = ROOT / "data" / "walks"
EDITORIAL = ROOT / "data" / "editorial"
SCHEMA = json.loads((ROOT / "schema" / "walk.schema.json").read_text())

MODEL = os.environ.get("WAYMARK_MODEL", "claude-sonnet-5")
MAX_TOKENS = 3000


def load_gazetteer() -> list[str]:
    path = ROOT / "data" / "gazetteer.txt"
    return [
        ln.strip() for ln in path.read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]


def id_and_path(slug: str) -> tuple[int, Path]:
    """
    A walk keeps its number. Re-authoring after a re-survey is routine — a better route, a
    corrected write-up — and letting the id climb each time churns the record for no reason.
    An existing record for this slug keeps its id and its filename; only a new slug takes the
    next number.
    """
    existing = sorted(WALKS.glob(f"*-{slug}.json"))
    if existing:
        return int(existing[0].name.split("-")[0]), existing[0]
    ids = [int(p.name.split("-")[0]) for p in WALKS.glob("*.json") if p.name[:4].isdigit()]
    wid = max(ids, default=0) + 1
    return wid, WALKS / f"{wid:04d}-{slug}.json"


def build_messages(survey: dict) -> tuple[str, str, str]:
    from jinja2 import Template

    system = (ROOT / "prompts" / "author-system.md").read_text()
    template = Template((ROOT / "prompts" / "author-user.md.j2").read_text())

    editorial_schema = {
        k: SCHEMA["properties"][k]
        for k in ("editorial", "ratings", "confidence")
    }

    user = template.render(
        voice_md=(ROOT / "docs" / "VOICE.md").read_text(),
        survey_json=json.dumps(survey, indent=2)[:60_000],
        named_features=survey["facts"]["named_features"],
        gazetteer=load_gazetteer(),
        editorial_schema_json=json.dumps(editorial_schema, indent=2),
    )
    prompt_sha = hashlib.sha256((system + user).encode()).hexdigest()[:12]
    return system, user, prompt_sha


def call_model(system: str, user: str) -> dict:
    from anthropic import Anthropic

    client = Anthropic()
    resp = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        system=system,
        messages=[{"role": "user", "content": user}],
    )
    text = "".join(b.text for b in resp.content if b.type == "text").strip()
    text = re.sub(r"^```(?:json)?|```$", "", text, flags=re.MULTILINE).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise SystemExit(
            f"Model did not return parseable JSON ({e}). First 400 chars:\n{text[:400]}"
        )


def read_editorial(path: Path) -> tuple[dict, str]:
    """
    An editorial block written in-session rather than fetched over the API.

    It must carry exactly the three branches the model is allowed to write. Anything else in
    the file is rejected rather than ignored, because a `facts` key here would be a person or
    a model quietly hand-editing surveyed values, which is the one thing the split exists to
    prevent.
    """
    written = json.loads(path.read_text())
    allowed = {"editorial", "ratings", "confidence", "$comment"}
    extra = set(written) - allowed
    if extra:
        raise SystemExit(
            f"{path}: may only contain editorial, ratings and confidence — found {sorted(extra)}. "
            "Surveyed values come from the survey payload and are never written by hand."
        )
    for required in ("editorial", "confidence"):
        if required not in written:
            raise SystemExit(f"{path}: missing '{required}'")
    return written, hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--survey", required=True, type=Path)
    ap.add_argument("--editorial", type=Path,
                    help="a written editorial block (no API call). Defaults to "
                         "data/editorial/<slug>.json when that file exists.")
    ap.add_argument("--api", action="store_true",
                    help="force the API path even if an editorial file is present")
    ap.add_argument("--out", type=Path, help="override output path")
    args = ap.parse_args()

    survey = json.loads(args.survey.read_text())

    editorial_path = args.editorial or (EDITORIAL / f"{survey['slug']}.json")
    if not args.api and editorial_path.exists():
        written, source_sha = read_editorial(editorial_path)
        model, prompt_sha = "claude-in-session", source_sha
        print(f"authored from {editorial_path} — no API call")
    else:
        system, user, prompt_sha = build_messages(survey)
        written = call_model(system, user)
        model = MODEL
        print(f"authored by {MODEL} over the API")

    # Merge. The model's output is confined to three branches; everything else is survey
    # provenance. If the model wrote into facts or geometry, it is discarded silently here
    # and validate.py will not see it — which is the point.
    wid, default_out = id_and_path(survey["slug"])
    record = {
        "id": wid,
        "slug": survey["slug"],
        "name": survey["name"],
        "status": "draft",
        "geometry": survey["geometry"],
        "facts": survey["facts"],
        "editorial": written["editorial"],
        "ratings": written.get("ratings", {}),
        "confidence": written["confidence"],
        "provenance": {
            **survey["provenance"],
            "authored_at": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "prompt_sha": prompt_sha,
            "validation": {"passed": False, "checks": {}},
        },
    }

    WALKS.mkdir(parents=True, exist_ok=True)
    out = args.out or default_out
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    print(f"→ {out}")
    print(f"  confidence.navigable = {record['confidence']['navigable']}")
    print(f"  now run: python scripts/validate.py {out}")


if __name__ == "__main__":
    main()
