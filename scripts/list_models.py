"""List the models your Google AI Studio key can actually call.

    python scripts/list_models.py

Model ids change between releases, so rather than guessing what to put in
GEMMA_MODEL / EMBED_MODEL, ask the API. Needs GEMINI_API_KEY in .env.
"""
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

KEY = os.getenv("GEMINI_API_KEY", "").strip()
if not KEY:
    sys.exit(
        "No GEMINI_API_KEY found.\n"
        "  1. Get a free key at https://aistudio.google.com/apikey\n"
        "  2. Put it in .env as:  GEMINI_API_KEY=your_key_here"
    )


def fetch():
    models, page = [], ""
    with httpx.Client(timeout=60) as c:
        while True:
            r = c.get(
                "https://generativelanguage.googleapis.com/v1beta/models",
                headers={"x-goog-api-key": KEY},
                params={"pageSize": 200, **({"pageToken": page} if page else {})},
            )
            if r.status_code in (400, 403):
                sys.exit(f"The API key was rejected ({r.status_code}). Check GEMINI_API_KEY in .env.")
            r.raise_for_status()
            data = r.json()
            models += data.get("models", [])
            page = data.get("nextPageToken", "")
            if not page:
                return models


def show(title, rows, hint):
    print(f"\n{title}")
    print("-" * len(title))
    if not rows:
        print("  (none available to this key)")
        return
    for m in rows:
        name = m["name"].removeprefix("models/")
        print(f"  {name:42s} {m.get('displayName', '')}")
    print(f"\n  -> {hint}")


models = fetch()
gen = [m for m in models if "generateContent" in m.get("supportedGenerationMethods", [])]
emb = [m for m in models if "embedContent" in m.get("supportedGenerationMethods", [])]

print(f"{len(models)} models visible to this key.")

show("Gemma chat models", [m for m in gen if "gemma" in m["name"].lower()],
     "put one of these in .env as  GEMMA_MODEL=<id>   (with LLM_BACKEND=gemini)")

show("Embedding models", emb,
     "put one of these in .env as  EMBED_MODEL=<id>")

other = [m for m in gen if "gemma" not in m["name"].lower()]
if other:
    print(f"\n({len(other)} other chat models are also available, e.g. "
          f"{', '.join(m['name'].removeprefix('models/') for m in other[:3])})")
