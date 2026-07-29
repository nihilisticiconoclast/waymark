#!/usr/bin/env python3
"""
Stage 2: AUTHOR. The model writes prose and a calibrated confidence, and nothing else.

    ANTHROPIC_API_KEY=... python scripts/author.py --survey data/surveys/haresfield-beacon.json

The model sees the survey payload, the voice specification, and the permitted proper nouns.
It does not see the internet, previous walks, or anything that would let it fill a gap with
something plausible. If the write-up is thin, the survey was thin, and that is the correct
signal — widen the Overpass query rather than loosening this stage.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path

from anthropic import Anthropic
from jinja2 import Template

ROOT = Path(__file__).resolve().parent.parent
WALKS = ROOT / "data" / "walks"
SCHEMA = json.loads((ROOT / "schema" / "walk.schema.json").read_text())

MODEL = os.environ.get("WAYMARK_MODEL", "claude-sonnet-5")
MAX_TOKENS = 3000


def load_gazetteer() -> list[str]:
    path = ROOT / "data" / "gazetteer.txt"
    return [
        ln.strip() for ln in path.read_text().splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]


def next_id() -> int:
    ids = [int(p.name.split("-")[0]) for p in WALKS.glob("*.json") if p.name[:4].isdigit()]
    return max(ids, default=0) + 1


def build_messages(survey: dict) -> tuple[str, str, str]:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--survey", required=True, type=Path)
    ap.add_argument("--out", type=Path, help="override output path")
    args = ap.parse_args()

    survey = json.loads(args.survey.read_text())
    system, user, prompt_sha = build_messages(survey)
    written = call_model(system, user)

    # Merge. The model's output is confined to three branches; everything else is survey
    # provenance. If the model wrote into facts or geometry, it is discarded silently here
    # and validate.py will not see it — which is the point.
    wid = next_id()
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
            "model": MODEL,
            "prompt_sha": prompt_sha,
            "validation": {"passed": False, "checks": {}},
        },
    }

    WALKS.mkdir(parents=True, exist_ok=True)
    out = args.out or WALKS / f"{wid:04d}-{survey['slug']}.json"
    out.write_text(json.dumps(record, indent=2, ensure_ascii=False))
    print(f"→ {out}")
    print(f"  confidence.navigable = {record['confidence']['navigable']}")
    print(f"  now run: python scripts/validate.py {out}")


if __name__ == "__main__":
    main()
