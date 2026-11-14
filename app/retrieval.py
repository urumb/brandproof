"""Light keyword retrieval (BM25). No model download, no cost, fits free hosting."""
import math
import re

_TOK = re.compile(r"[a-z0-9]+")


def tokens(text: str):
    return _TOK.findall(text.lower())


def top_k(query: str, docs, k: int = 8, k1: float = 1.5, b: float = 0.75):
    """docs: list of (id, text). Returns ids ranked by BM25 score (score > 0 only)."""
    toks = [tokens(t) for _, t in docs]
    n = len(docs)
    if n == 0:
        return []
    avgdl = sum(len(t) for t in toks) / n or 1
    df = {}
    for t in toks:
        for w in set(t):
            df[w] = df.get(w, 0) + 1
    q = set(tokens(query))
    scored = []
    for (doc_id, _), t in zip(docs, toks):
        score = 0.0
        for w in q:
            f = t.count(w)
            if not f:
                continue
            idf = math.log(1 + (n - df[w] + 0.5) / (df[w] + 0.5))
            score += idf * f * (k1 + 1) / (f + k1 * (1 - b + b * len(t) / avgdl))
        if score > 0:
            scored.append((score, doc_id))
    scored.sort(reverse=True)
    return [doc_id for _, doc_id in scored[:k]]
