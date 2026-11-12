"""Tiny RAG engine: markdown chunks -> hybrid (Gemma embeddings + TF-IDF) retrieval."""
import hashlib, logging, os, re, time
from pathlib import Path
import httpx, numpy as np
from sklearn.feature_extraction.text import TfidfVectorizer

log = logging.getLogger("rag")


def load_chunks(kb_dir: Path):
    chunks = []
    for f in sorted(kb_dir.glob("*.md")):
        text = f.read_text(encoding="utf-8")
        m = re.search(r"^#\s+(.+)$", text, re.M)
        title = m.group(1).strip() if m else f.stem
        for part in re.split(r"^##\s+", text, flags=re.M)[1:]:
            head, _, body = part.partition("\n")
            if body.strip():
                chunks.append({"source": f.name, "title": f"{title} - {head.strip()}", "text": body.strip()})
    return chunks


class Retriever:
    def __init__(self, kb_dir, ollama_url, embed_model, cache_dir, emb_min=0.40, tfidf_min=0.08):
        self.chunks = load_chunks(Path(kb_dir))
        self.docs = [f"{c['title']}\n{c['text']}" for c in self.chunks]
        self.tfidf = TfidfVectorizer(ngram_range=(1, 2), stop_words="english", sublinear_tf=True)
        self.M = self.tfidf.fit_transform(self.docs)
        self.url, self.model = ollama_url.rstrip("/"), embed_model
        self.emb_min, self.tfidf_min = emb_min, tfidf_min
        # Embeddings follow the chat backend unless EMBED_BACKEND says otherwise,
        # so setting LLM_BACKEND=gemini needs no local model server at all.
        self.backend = os.getenv("EMBED_BACKEND", os.getenv("LLM_BACKEND", "ollama")).lower()
        self.E = None
        if self.model:
            try:
                self.E = self._load_embeddings(Path(cache_dir))
                log.info("Embeddings ready (%s via %s)", self.model, self.backend)
            except Exception as e:
                log.warning("Embeddings unavailable (%s) - using TF-IDF only", e)

    def _embed(self, texts, query=False):
        """Embed with whichever backend is configured, and L2-normalise, so a dot
        product is the cosine score either way."""
        v = (self._embed_gemini(texts, query) if self.backend == "gemini"
             else self._embed_ollama(texts, query))
        return v / (np.linalg.norm(v, axis=1, keepdims=True) + 1e-9)

    def _embed_ollama(self, texts, query):
        pre = "task: search result | query: " if query else "title: none | text: "
        r = httpx.post(f"{self.url}/api/embed", json={"model": self.model, "input": [pre + t for t in texts]}, timeout=120)
        r.raise_for_status()
        return np.array(r.json()["embeddings"], dtype=np.float32)

    def _embed_gemini(self, texts, query):
        """Google AI Studio embeddings, so no local model server is needed.

        batchEmbedContents accepts at most 100 items per call, and the task type
        matters: a question and a passage are embedded into the same space only
        when they are tagged RETRIEVAL_QUERY and RETRIEVAL_DOCUMENT respectively.
        """
        key = os.getenv("GEMINI_API_KEY", "").strip()
        if not key:
            raise RuntimeError("GEMINI_API_KEY is not set")
        model = self.model if self.model.startswith("models/") else f"models/{self.model}"
        task = "RETRIEVAL_QUERY" if query else "RETRIEVAL_DOCUMENT"

        out = []
        for i in range(0, len(texts), 100):
            batch = texts[i:i + 100]
            body = {"requests": [{"model": model, "content": {"parts": [{"text": t}]},
                                  "taskType": task} for t in batch]}
            # The free tier rate-limits aggressively, and a visitor standing at the
            # kiosk is worth a couple of seconds' wait rather than a silent drop to
            # keyword-only retrieval.
            for attempt in range(4):
                r = httpx.post(
                    f"https://generativelanguage.googleapis.com/v1beta/{model}:batchEmbedContents",
                    headers={"x-goog-api-key": key}, json=body, timeout=180)
                if r.status_code == 404:
                    raise RuntimeError(
                        f"embedding model '{self.model}' not available to this key - "
                        "run scripts/list_models.py to see the ids you can use")
                if r.status_code == 429 and attempt < 3:
                    # The free tier budget is per minute, and indexing the whole
                    # knowledge base can use most of it, so the last wait is long
                    # enough to cross into the next window.
                    wait = (2, 8, 30)[attempt]
                    log.warning("embedding rate-limited, retrying in %ss", wait)
                    time.sleep(wait)
                    continue
                r.raise_for_status()
                break
            out += [e["values"] for e in r.json()["embeddings"]]
        return np.array(out, dtype=np.float32)

    def _load_embeddings(self, cache_dir):
        cache_dir.mkdir(parents=True, exist_ok=True)
        key = hashlib.sha1((self.backend + self.model + "".join(self.docs)).encode()).hexdigest()[:16]
        f = cache_dir / f"emb_{key}.npy"
        if f.exists():
            return np.load(f)
        E = self._embed(self.docs)
        np.save(f, E)
        return E

    def search(self, query, k=4):
        t = (self.tfidf.transform([query]) @ self.M.T).toarray()[0]
        e = None
        if self.E is not None:
            try:
                e = self.E @ self._embed([query], query=True)[0]
            except Exception as ex:
                log.warning("query embedding failed: %s", ex)
        score = 0.7 * e + 0.3 * t if e is not None else t
        idx = np.argsort(-score)[:k]
        relevant = bool(t.max() >= self.tfidf_min or (e is not None and e.max() >= self.emb_min))
        log.info("retrieval tfidf=%.2f emb=%s relevant=%s", t.max(), None if e is None else round(float(e.max()), 2), relevant)
        return [self.chunks[i] for i in idx], relevant
