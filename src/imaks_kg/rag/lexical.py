"""Okapi BM25 for the small mixed Korean/English corpus.

graph_v2 used an IDF-weighted overlap score. v3 uses standard BM25 so the
lexical half of the hybrid retriever is a well-known, defensible baseline,
and the *same* retriever is shared by the vector and graph systems.
"""
from __future__ import annotations

import math
import re
from collections import Counter

_TOKEN = re.compile(r"[a-z0-9]+(?:[-_.][a-z0-9]+)*|[가-힣]+")


def tokenize(text: str) -> list[str]:
    """Lower-cased tokens. Compound IDs also emit their parts.

    ``ST02_SEALING-CUR`` -> ``st02_sealing-cur``, ``st02``, ``sealing``, ``cur``
    so that a question saying "ST02 CUR" still matches the document form.
    Korean words are kept whole; particles are trimmed by ``_korean_stems``.
    """
    tokens = []
    for token in _TOKEN.findall(text.lower()):
        tokens.append(token)
        if re.search(r"[-_]", token):
            tokens.extend(part for part in re.split(r"[-_]", token) if part)
        if re.match(r"[가-힣]", token):
            tokens.extend(_korean_stems(token))
    return tokens


_PARTICLES = ("에서는", "으로는", "에서", "으로", "에게", "까지", "부터", "보다", "은", "는", "이", "가",
              "을", "를", "의", "에", "와", "과", "도", "로", "만")


def _korean_stems(word: str) -> list[str]:
    for particle in _PARTICLES:
        if word.endswith(particle) and len(word) - len(particle) >= 2:
            return [word[: -len(particle)]]
    return []


class BM25:
    def __init__(self, documents: list[str], k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self.docs = [Counter(tokenize(d)) for d in documents]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.avg_length = sum(self.lengths) / max(len(self.lengths), 1)
        df = Counter(term for doc in self.docs for term in doc)
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}

    def scores(self, query: str) -> list[float]:
        terms = set(tokenize(query))
        result = []
        for doc, length in zip(self.docs, self.lengths):
            score = 0.0
            for term in terms & doc.keys():
                tf = doc[term]
                norm = tf + self.k1 * (1 - self.b + self.b * length / self.avg_length)
                score += self.idf[term] * tf * (self.k1 + 1) / norm
            result.append(score)
        return result


def rrf(rankings: list[list[str]], k: int = 60) -> list[str]:
    """Reciprocal rank fusion; ties broken by ID for determinism."""
    score: dict[str, float] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            score[item] = score.get(item, 0.0) + 1.0 / (k + rank)
    return sorted(score, key=lambda item: (-score[item], item))
