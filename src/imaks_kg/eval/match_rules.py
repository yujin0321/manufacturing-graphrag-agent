"""Match predicted rules to ground truth with a thresholded bipartite matcher."""
from collections import defaultdict

from imaks_kg.eval.normalize import lexical_similarity


def build_edges(predictions, truths, threshold):
    edges = defaultdict(list)
    scores = {}
    for i, p in enumerate(predictions):
        for j, t in enumerate(truths):
            if p.get("class") != t.get("class"):
                continue
            score = lexical_similarity(p, t)
            if score >= threshold:
                edges[i].append(j)
                scores[(i, j)] = score
    for i in edges:
        edges[i].sort(key=lambda j: scores[(i, j)], reverse=True)
    return edges, scores


def max_match(predictions, truths, threshold=0.6):
    edges, scores = build_edges(predictions, truths, threshold)
    match_to_pred = {}

    def dfs(i, seen):
        for j in edges.get(i, []):
            if j in seen:
                continue
            seen.add(j)
            if j not in match_to_pred or dfs(match_to_pred[j], seen):
                match_to_pred[j] = i
                return True
        return False

    for i in range(len(predictions)):
        dfs(i, set())

    pairs = [(i, j, scores[(i, j)]) for j, i in match_to_pred.items()]
    pairs.sort(key=lambda x: (predictions[x[0]].get("class", ""), x[1]))
    return pairs
