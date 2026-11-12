"""Conservative, dependency-free evidence checks used by the Gemma answer path."""
import hashlib
import hmac
import json
import re

GROUNDING_STOP = set("""
a an and are as at be been being but by can could did do does for from had has have
he her here hers him his how i in into is it its me my of on or our she should that
the their them there these they this those to us was we were what when where which
who why will with would you your according current information record records source sources
""".split())
HOURS_RANGE = re.compile(
    r"\b(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\s*(?:-|to|until)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)\b",
    re.I,
)


def context_signature(payload: dict, key: str) -> str:
    """HMAC a canonical JSON payload so local Gemma only trusts API-returned context."""
    body = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hmac.new(key.encode("utf-8"), body, hashlib.sha256).hexdigest()


def verify_context_signature(payload: dict, key: str, signature: str) -> bool:
    return bool(key and signature) and hmac.compare_digest(context_signature(payload, key), signature)


def has_conflicting_hours(hits: list[dict]) -> bool:
    """Reject separate same-title records that state different single hours ranges."""
    by_title: dict[str, list[set[tuple[str, str]]]] = {}
    for hit in hits:
        title = re.sub(r"\W+", " ", hit["title"].lower()).strip()
        ranges = {(a.lower().replace(" ", ""), b.lower().replace(" ", ""))
                  for a, b in HOURS_RANGE.findall(hit["text"])}
        if title and ranges:
            by_title.setdefault(title, []).append(ranges)
    for records in by_title.values():
        # One record may legitimately list weekday and weekend intervals.
        singleton_ranges = {next(iter(ranges)) for ranges in records if len(ranges) == 1}
        if len(singleton_ranges) > 1 and len(singleton_ranges) == len(records):
            return True
    return False


def grounded_sources(answer: str, hits: list[dict]) -> list[str] | None:
    """Require evidence for each answer sentence and exact support for numeric claims."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", answer) if s.strip()]
    evidences = [set(re.findall(r"[a-z0-9]+", f"{h['title']} {h['text']}".lower())) for h in hits]
    used: list[str] = []
    saw_claim = False
    for sentence in sentences:
        words = re.findall(r"[a-z0-9]+", sentence.lower())
        # Single digits count: "a 9 minute walk" must not pass for "2 minutes".
        claim = [w for w in words if w not in GROUNDING_STOP and (len(w) > 1 or w.isdigit())]
        if not claim:
            continue
        saw_claim = True
        combined = set().union(*evidences) if evidences else set()
        if any(w.isdigit() and w not in combined for w in claim):
            return None
        if sum(w in combined for w in claim) / len(claim) < 0.5:
            return None
        for hit, evidence in zip(hits, evidences):
            overlap = sum(w in evidence for w in claim)
            if overlap and overlap / len(claim) >= 0.2 and hit["source"] not in used:
                used.append(hit["source"])
    return used if saw_claim and used else None

