"""Real farmer questions from the Kisan Call Centre (KCC) for the evaluation.

1. Get a free API key: register at https://data.gov.in (My Account -> Generate API key).
2. Put it in .env:   DATA_GOV_IN_API_KEY=...
3. On https://www.data.gov.in, open a "Kisan Call Centre (KCC) - Transcripts of farmers queries &
   answers" resource (e.g. a Karnataka district/month) and copy its API resource id
   (the long hex id shown under "API").
4. Run:
     .\\.venv\\Scripts\\python eval\\fetch_kcc.py <resource-id> [<resource-id> ...] [--state KARNATAKA] [--n 60]
     .\\.venv\\Scripts\\python eval\\run_eval.py --queries eval\\queries_kcc.json

Writes eval/queries_kcc.json with the farmers' query texts (expect = "real").
"""
import argparse
import json
import os
import random
import re
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env", override=True)


def query_field(rec: dict) -> str | None:
    for k, v in rec.items():
        if "query" in k.lower() and isinstance(v, str):
            return v
    return None


def main():
    ap = argparse.ArgumentParser(description="Fetch real KCC farmer queries from data.gov.in")
    ap.add_argument("resources", nargs="+", help="data.gov.in resource id(s) of KCC datasets")
    ap.add_argument("--state", default="", help="filter by state name (if the dataset has StateName)")
    ap.add_argument("--n", type=int, default=60, help="how many questions to keep")
    ap.add_argument("--per-resource", type=int, default=500)
    args = ap.parse_args()
    key = os.getenv("DATA_GOV_IN_API_KEY", "").strip()
    if not key:
        sys.exit("DATA_GOV_IN_API_KEY is not set in .env (register free at https://data.gov.in).")
    texts = []
    for rid in args.resources:
        params = {"api-key": key, "format": "json", "limit": args.per_resource, "offset": 0}
        if args.state:
            params["filters[StateName]"] = args.state.upper()
        r = httpx.get(f"https://api.data.gov.in/resource/{rid}", params=params, timeout=60)
        r.raise_for_status()
        recs = r.json().get("records", [])
        got = [query_field(x) for x in recs]
        texts += [t.strip() for t in got if t and len(t.split()) >= 3]
        print(f"{rid}: {len(recs)} records, {len(got)} with query text")
    # drop exact duplicates and very short / phone-call boilerplate
    seen, uniq = set(), []
    for t in texts:
        k = re.sub(r"\W+", " ", t.lower()).strip()
        if k not in seen:
            seen.add(k)
            uniq.append(t)
    random.Random(42).shuffle(uniq)
    picked = uniq[:args.n]
    out = {"_note": "Real Kisan Call Centre queries from data.gov.in (resources: " + ", ".join(args.resources) + ").",
           "queries": [{"q": t, "expect": "real"} for t in picked], "red_team": []}
    path = ROOT / "eval" / "queries_kcc.json"
    path.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"wrote {len(picked)} real farmer questions to {path}")


if __name__ == "__main__":
    main()
