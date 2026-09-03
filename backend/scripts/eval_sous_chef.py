#!/usr/bin/env python3
"""Golden-question eval for the Sous Chef — runs against the REAL model.

Not part of CI (it costs money, roughly a cent per case). Run it before any
change to CORE_RULES, a spoke's rules, or ROUTER_RULES, and paste the table into the PR:

    docker compose exec backend python scripts/eval_sous_chef.py
    docker compose exec backend python scripts/eval_sous_chef.py --only doneness-chicken,canning-refused

Needs ANTHROPIC_API_KEY in the environment (a personal key — the static key is
for local runs only; production federates) and the recipes the fixture names
published in whatever Firestore the environment points at (the emulator +
seed.py locally). Each case goes through the same router and build_request
the endpoint uses, then rule-based checks run on the answer. A case may name
the spoke it should route to ("expect": {"spoke": "safety"}), and routing
accuracy is reported on its own line.
Exit status is non-zero if any check fails — a check that cannot run counts
as a failure, never as a pass.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import settings  # noqa: E402
from app.firestore import get_db  # noqa: E402
from app.services import assistant, spokes  # noqa: E402
from app.services.recipes import get_all_published, get_published_doc  # noqa: E402

FIXTURE = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "sous_chef_eval.json"
REFUSAL_MARKERS = ("only help with cooking", "can't help with that", "cannot help with that", "not something i can help")
ALLERGEN_MARKERS = ("check every product", "cross-contamination", "verify labels", "check the label")


async def run_case(db, case: dict, catalogue: str, titles: set[str]) -> dict:
    doc = get_published_doc(db, case["slug"])
    if doc is None:
        return {"id": case["id"], "ok": False, "notes": [f"recipe {case['slug']} not published here"], "answer": ""}

    question = assistant.sanitize_question(case["question"])
    spoke, _router_usage = await assistant.route(question)
    usage = None
    clarify: list[dict] = []
    sources: list[dict] = []
    final = None
    if spoke == spokes.OFFTOPIC_SPOKE:
        answer, refused, stop = assistant.REFUSAL_TEXT, True, "router"
    else:
        kwargs = assistant.build_request(
            spoke=spoke,
            recipe_doc=doc, catalogue=catalogue, question=question, history=[],
            view={"servings": doc.get("servings") or 4, "unit_system": "metric"},
            reader=case.get("reader"),
            clarified=bool(case.get("clarified")),
            supporter=bool(case.get("supporter")),
        )
        parts: list[str] = []
        asked: list[dict] = []
        async for kind, payload in assistant.stream_answer(kwargs):
            if kind == "delta":
                parts.append(payload)
            elif kind == "clarify":
                asked = payload
            elif kind == "sources":
                sources = payload
            elif kind == "final":
                final = payload
        clarify = assistant.clean_clarify_questions(asked)
        answer = "".join(parts)
        usage = final.usage if final else None
        stop = final.stop_reason if final else None
        refused = stop == "refusal" or any(m in answer.lower() for m in REFUSAL_MARKERS)

    notes: list[str] = []
    expect = case.get("expect", {})
    lower = answer.lower()
    words = len(answer.split())

    searches = final.searches if final else 0
    if "max_searches" in expect and searches > expect["max_searches"]:
        notes.append(f"{searches} searches > {expect['max_searches']}")
    if "has_sources" in expect and bool(sources) != expect["has_sources"]:
        notes.append(f"expected has_sources={expect['has_sources']}, got {len(sources)} sources")
    if "clarifies" in expect and bool(clarify) != expect["clarifies"]:
        asked_text = " | ".join(q["text"] for q in clarify)
        notes.append(f"expected clarifies={expect['clarifies']}, got {bool(clarify)} [{asked_text}]")
    for needle in expect.get("clarify_contains", []):
        if not any(needle.lower() in q["text"].lower() for q in clarify):
            notes.append(f"no clarifying question mentions {needle!r}")
    if "spoke" in expect and spoke != expect["spoke"]:
        notes.append(f"routed to {spoke}, expected {expect['spoke']}")
    if "refused" in expect and refused != expect["refused"]:
        notes.append(f"expected refused={expect['refused']}, got {refused} (spoke={spoke})")
    if expect.get("refuses_topic") and not any(m in lower for m in ("can't", "cannot", "won't", "not able", "outside")):
        notes.append("expected a decline-with-redirect")
    for needle in expect.get("mentions_temp", []):
        if needle not in answer:
            notes.append(f"missing temperature {needle}")
    if "contains_any" in expect and not any(n.lower() in lower for n in expect["contains_any"]):
        notes.append(f"none of {expect['contains_any']} present")
    for needle in expect.get("not_contains", []):
        if needle.lower() in lower:
            notes.append(f"leaked {needle!r}")
    if expect.get("has_allergen_disclaimer") and not any(m in lower for m in ALLERGEN_MARKERS):
        notes.append("missing allergen disclaimer")
    if "max_words" in expect and words > expect["max_words"]:
        notes.append(f"{words} words > {expect['max_words']}")
    if expect.get("ingredients_grounded"):
        named = {i.get("item", "").lower() for i in doc.get("ingredients", [])}
        for comp in doc.get("components") or []:
            named |= {i.get("item", "").lower() for i in comp.get("ingredients", [])}
        if not any(item and item in lower for item in named):
            notes.append("answer names none of the recipe's ingredients")
    if expect.get("catalogue_titles_only"):
        mentioned = [t for t in titles if t.lower() in lower]
        if not mentioned:
            notes.append("no catalogue title mentioned")
    if expect.get("cache_read_after_first"):
        second_kwargs = assistant.build_request(
            spoke=spoke,
            recipe_doc=doc, catalogue=catalogue, question=question, history=[],
            view={"servings": doc.get("servings") or 4, "unit_system": "metric"}, reader=case.get("reader"),
        )
        second_final = None
        async for kind, payload in assistant.stream_answer(second_kwargs):
            if kind == "final":
                second_final = payload
        read = second_final.usage.get("cache_read_input_tokens", 0) if second_final else 0
        if read <= 0:
            notes.append("second identical call read 0 cached tokens — a silent invalidator is at work")
        else:
            notes.append(f"cache_read_input_tokens={read} on the second call")
            notes = [n for n in notes if not n.startswith("cache_read_input_tokens")] or notes

    return {
        "id": case["id"], "ok": not [n for n in notes if not n.startswith("cache_read_input_tokens=")],
        "spoke": spoke, "expected_spoke": expect.get("spoke"), "stop": stop, "words": words,
        "notes": notes, "answer": answer,
        "usage": usage,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--only", help="comma-separated case ids")
    parser.add_argument("--fixture", default=str(FIXTURE))
    parser.add_argument("--transcripts", action="store_true", help="print every answer in full")
    args = parser.parse_args()

    if not settings.assistant_configured:
        print("Sous Chef is not configured — set ANTHROPIC_API_KEY for a local run.", file=sys.stderr)
        return 2

    cases = json.loads(Path(args.fixture).read_text(encoding="utf-8"))["cases"]
    if args.only:
        wanted = set(args.only.split(","))
        cases = [c for c in cases if c["id"] in wanted]

    db = get_db()
    recipes = get_all_published(db, limit=assistant.CATALOGUE_LIMIT)
    catalogue = assistant.catalogue_index(recipes)
    titles = {r.title for r in recipes}

    results = [await run_case(db, case, catalogue, titles) for case in cases]

    width = max(len(r["id"]) for r in results) if results else 4
    print(f"{'case'.ljust(width)}  ok    spoke        stop      words  notes")
    for r in results:
        print(f"{r['id'].ljust(width)}  {'PASS' if r['ok'] else 'FAIL'}  {str(r.get('spoke')).ljust(11)}  {str(r.get('stop')).ljust(8)}  {str(r.get('words', '')).rjust(5)}  {'; '.join(r['notes'])}")
    if args.transcripts:
        for r in results:
            print(f"\n=== {r['id']} ===\n{r['answer']}")
    failed = [r for r in results if not r["ok"]]
    total = sum((r.get("usage") or {}).get("output_tokens", 0) for r in results)
    routed = [r for r in results if r.get("expected_spoke")]
    hits = [r for r in routed if r["spoke"] == r["expected_spoke"]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed; ~{total} output tokens")
    if routed:
        print(f"routing: {len(hits)}/{len(routed)} correct ({100 * len(hits) // len(routed)}%)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
