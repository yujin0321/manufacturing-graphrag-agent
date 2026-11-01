"""Retrieval v3: one shared hybrid retriever, three systems.

Design rule (learned from the v2 ablation): the vector and graph systems must
share *everything* except the graph. graph_v2 improved lexical fusion, ID
handling and candidate count together with the graph, so its 120/120 could
not be attributed to the graph. Here:

* ``vector_v3``   - BM25 + dense (RRF) over table-row chunks. No KG access.
* ``graph_v3``    - exactly the same candidates, plus rows reached through the
                    KG (linked entities -> traversal -> provenance rows) inserted
                    before the generic fused results, plus merged entity cards.
* ``full_context``- every original chunk, no retrieval. The corpus is only 86
                    chunks, so this is the honest upper bound any RAG must beat
                    on cost, not necessarily on accuracy.

Nothing here reads answer keys, benchmark files or scores.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

import numpy as np
import tiktoken
from rdflib import RDF, URIRef

from . import comparison as c
from . import linking
from . import vector as v
from .chunking import parent_of, provenance_row_number, row_chunk_id, split_table_rows
from .lexical import BM25, rrf

POLICY_PATH = v.REPO_ROOT / "docs/graphrag_v3/policy.json"
ROW_INDEX = v.REPO_ROOT / "kg_build/retrieval_v3_rows"
INSTRUCTIONS = v.REPO_ROOT / "docs/vector_rag_v1/answer_instructions.txt"  # shared with v1/v2 on purpose


def load_policy() -> dict:
    return v.read(POLICY_PATH)


def row_corpus() -> list[dict]:
    records, _ = v.source_records()  # verifies the frozen chunks.jsonl hash
    return split_table_rows(records)


# --------------------------------------------------------------- dense index
def build_row_index(index: Path = ROW_INDEX, call=v.api_call) -> dict:
    """Embeds row chunks once (paid API call, ~8k tokens). Re-running reuses the cache."""
    index = Path(index)
    rows = row_corpus()
    policy = load_policy()
    config = {"embedding_model": policy["dense_embedding_model"], "dimensions": policy["dense_dimensions"]}
    vectors, api = v.embed([v.embedding_text(r) for r in rows], config, index / "api_cache", call)
    index.mkdir(parents=True, exist_ok=True)
    np.save(index / "vectors.npy", vectors, allow_pickle=False)
    manifest = {"policy_version": policy["version"], "row_ids": [r["chunk_id"] for r in rows],
                "corpus_sha256": v.digest(v.encoded(rows)),
                "vectors_sha256": v.digest((index / "vectors.npy").read_bytes()), "config": config, "api": api}
    v.write(index / "manifest.json", manifest)
    return manifest


def dense_ranking(question: str, rows: list[dict], index: Path = ROW_INDEX, call=v.api_call) -> list[str]:
    index = Path(index)
    manifest = v.read(index / "manifest.json")
    if manifest["row_ids"] != [r["chunk_id"] for r in rows] or manifest["corpus_sha256"] != v.digest(v.encoded(rows)):
        raise ValueError("Row index does not match the current corpus; rebuild into a new directory")
    vectors = np.load(index / "vectors.npy", allow_pickle=False)
    if v.digest((index / "vectors.npy").read_bytes()) != manifest["vectors_sha256"]:
        raise ValueError("Row index vectors changed")
    query, _ = v.embed([question], manifest["config"], index / "query_cache", call)
    hits = v.retrieve(rows, v.normalized(vectors, len(rows), manifest["config"]["dimensions"]), query[0], len(rows))
    return [h["chunk_id"] for h in hits]


# ----------------------------------------------------------- shared ranking
def fused_ranking(question: str, rows: list[dict], dense: list[str] | None, policy: dict) -> list[str]:
    bm25 = BM25([v.embedding_text(r) for r in rows])
    scores = bm25.scores(question)
    lexical = [r["chunk_id"] for s, r in sorted(zip(scores, rows), key=lambda t: (-t[0], t[1]["chunk_id"])) if s > 0]
    rankings = [lexical] + ([dense] if dense else [])
    fused = rrf(rankings, policy["rrf_constant"])
    rest = sorted(r["chunk_id"] for r in rows if r["chunk_id"] not in set(fused))
    return fused + rest


def shared_prefix(question: str, rows: list[dict], ranked: list[str], policy: dict) -> list[str]:
    """Literal document identifiers and named documents, derived from the raw
    text only (no KG), identical for vector_v3 and graph_v3."""
    by_id = {r["chunk_id"]: r for r in rows}
    doc_ids = {r["doc_id"] for r in rows}
    vocabulary = {t for r in rows for t in re.findall(r"[A-Z][A-Z0-9]*(?:[-_][A-Z0-9]+)+", r["text"])}
    literal = sorted(t for t in vocabulary - doc_ids if linking.find_spans(t, question))
    prefix: list[str] = []
    for cid in ranked:
        if any(linking.find_spans(t, by_id[cid]["text"]) for t in literal) and cid not in prefix:
            prefix.append(cid)
    named = sorted(d for d in doc_ids if linking.find_spans(d, question))
    for i in range(policy["per_explicit_document"]):
        for doc in named:
            hits = [cid for cid in ranked if by_id[cid]["doc_id"] == doc]
            if i < len(hits) and hits[i] not in prefix:
                prefix.append(hits[i])
    return prefix


# ------------------------------------------------------------ graph pieces
def provenance_rows(graph, rows: list[dict]) -> dict[str, list[str]]:
    """node -> exact row chunk(s). Table provenance uses tableId+rowIndex, so
    MAINT-04 points at row 4 of the SOP-003 table, not the whole table."""
    by_parent: dict[str, list[dict]] = {}
    for r in rows:
        by_parent.setdefault(r["parent_chunk_id"], []).append(r)
    table_parent = {r["table_id"]: r["parent_chunk_id"] for r in rows if r.get("table_id")}
    links: dict[str, list[str]] = {}
    for node in set(graph.subjects(c.IM.hasProvenance, None)):
        found: list[str] = []
        for p in graph.objects(node, c.IM.hasProvenance):
            if str(graph.value(p, c.IM.sourceKind)) != "document":
                continue
            table = str(graph.value(p, c.IM.tableId) or "")
            number = provenance_row_number(graph.value(p, c.IM.rowIndex))
            quote = " ".join(str(graph.value(p, c.IM.sourceQuote) or "").split())
            sha = str(graph.value(p, c.IM.fileSha256) or "")
            if table and table in table_parent:
                parent = table_parent[table]
                candidate = row_chunk_id(parent, number) if number else None
                if candidate and any(r["chunk_id"] == candidate for r in by_parent[parent]):
                    found.append(candidate)
                    continue
            for r in rows:
                if r["source_file_sha256"] == sha and quote and quote in " ".join(r["text"].split()):
                    found.append(r["chunk_id"])
        links[str(node)] = sorted(set(found))
    return links


def traverse(graph, index: linking.EntityIndex, seeds: list[str], policy: dict) -> tuple[list[str], list[dict]]:
    """Breadth-first over stored edges. Text references to RULE-/MAINT- IDs are
    followed as *retrieval hints* and logged as such - never asserted as facts."""
    g_policy = policy["graph"]
    allowed = {c.IM[p] for p in g_policy["traverse_predicates"]}
    rule_nodes = {n: a for n, a in index.identifier_aliases.items()
                  if any(x.startswith(("RULE-", "MAINT-")) for x in a)}
    queue = [(s, 0) for s in seeds[: g_policy["max_seed_entities"]]]
    seen: set[str] = set()
    visited: list[str] = []
    edges: list[dict] = []
    while queue and len(visited) < g_policy["max_graph_entities"]:
        node, depth = queue.pop(0)
        group = index.group_of(node) if g_policy["merge_duplicate_entities"] else [node]
        key = group[0]
        if key in seen:
            continue
        seen.add(key)
        visited.append(key)
        if depth >= g_policy["graph_hops"]:
            continue
        neighbours = []
        for member in map(URIRef, group):
            for p, o in graph.predicate_objects(member):
                if p in allowed and isinstance(o, URIRef):
                    neighbours.append((str(member), str(p), str(o), str(o)))
            for s, p in graph.subject_predicates(member):
                if p in allowed:
                    neighbours.append((str(s), str(p), str(member), str(s)))
        for s, p, o, nxt in sorted(set(neighbours)):
            edges.append({"kind": "stored_edge", "s": s, "p": p, "o": o, "depth": depth + 1})
            queue.append((nxt, depth + 1))
        if g_policy["follow_text_rule_references"]:
            text = " ".join(str(x) for m in map(URIRef, group)
                            for pred in (c.IM.conditionText, c.IM.responseText) for x in graph.objects(m, pred))
            for other, aliases in sorted(rule_nodes.items()):
                if other in group:
                    continue
                if any(a.startswith(("RULE-", "MAINT-")) and linking.find_spans(a, text) for a in aliases):
                    edges.append({"kind": "text_reference_not_new_fact", "s": key, "o": other, "depth": depth + 1})
                    queue.append((other, depth + 1))
    return visited, edges


def _seeds(graph, index: linking.EntityIndex, question: str) -> tuple[list[str], list[dict]]:
    mentions = index.link(question)
    # Specific before general: sensors and rules first, stations last, so a
    # station's 3 sensors do not crowd out the sensor the question named.
    def priority(m):
        node = URIRef(m.node)
        if (node, RDF.type, c.IM.Station) in graph:
            return 2
        return 0 if m.kind == "sensor_composed" or (node, RDF.type, c.IM.Sensor) not in graph else 1
    ordered = [m.node for m in sorted(mentions, key=lambda m: (priority(m), m.start, m.node))]
    seeds = list(dict.fromkeys(ordered))
    return seeds, [m.__dict__ for m in mentions]


# ----------------------------------------------------------- context build
def _render(rows_by_id: dict, cid: str) -> str:
    r = rows_by_id[cid]
    return f"[{cid}] {r['doc_id']} p.{r['page']} | {r.get('section') or ''}\n{r['text']}"


def expand_query(question: str, graph) -> tuple[str, list[str]]:
    """Name-only query expansion: append the canonical IDs of stations/sensors
    named in the question ("서버실 온도" -> "SRV01_SERVERROOM_TMP").

    Uses the KG purely as a *dictionary of names*; no edges, rules or
    provenance are read. This isolates "the lexicon helped" from "the graph
    traversal helped" - the confound that made graph_v2's gain unattributable.
    """
    index = linking.EntityIndex.build(graph)
    names = []
    for m in index.link(question):
        node = URIRef(m.node)
        if (node, RDF.type, c.IM.Station) in graph or (node, RDF.type, c.IM.Sensor) in graph:
            names.append(str(graph.value(node, c.IM.identifier)))
    names = list(dict.fromkeys(names))
    return (question + "\n" + " ".join(names)) if names else question, names


def build_context(system: str, question: str, rows: list[dict], dense: list[str] | None,
                  graph=None, policy: dict | None = None) -> dict:
    """``dense`` must be computed from the *original* question for every system,
    so only the lexical half sees the expanded query in vector_v3_lex/graph_v3."""
    if system not in {"vector_v3", "vector_v3_lex", "graph_v3"}:
        raise ValueError("build_context is for retrieval systems; use full_context_text for full_context")
    policy = policy or load_policy()
    enc = tiktoken.get_encoding(policy["context_encoding"])
    count = lambda text: len(enc.encode(text, disallowed_special=()))
    by_id = {r["chunk_id"]: r for r in rows}
    lexical_query, expansion = question, []
    if system in {"vector_v3_lex", "graph_v3"}:
        if graph is None:
            raise ValueError(f"{system} needs the KG name dictionary")
        lexical_query, expansion = expand_query(question, graph)
    ranked = fused_ranking(lexical_query, rows, dense, policy)
    prefix = shared_prefix(question, rows, ranked, policy)

    budget = policy["context_token_budget"]
    trace: dict = {"graph_used": system == "graph_v3", "query_expansion": expansion}
    graph_rows: list[str] = []
    visited: list[str] = []
    if system == "graph_v3":
        if graph is None:
            raise ValueError("graph_v3 needs the KG")
        index = linking.EntityIndex.build(graph)
        seeds, mentions = _seeds(graph, index, question)
        visited, edges = traverse(graph, index, seeds, policy)
        links = provenance_rows(graph, rows)
        for key in visited:
            for member in index.group_of(key):
                for cid in links.get(member, []):
                    if cid not in graph_rows:
                        graph_rows.append(cid)
        trace.update(mentions=mentions, seeds=seeds, visited_entities=visited, traversed_edges=edges,
                     graph_rows=graph_rows)

    # 1) Source text first. The original wording is the answer authority.
    candidates = list(dict.fromkeys(prefix + graph_rows + ranked))[: policy["max_source_candidates"]]
    blocks, selected, skipped = [], [], []
    for cid in candidates:
        block = _render(by_id, cid)
        if count("\n\n".join(blocks + [block])) > budget:
            skipped.append(cid)
            continue
        blocks.append(block)
        selected.append(cid)

    # 2) Merged KG cards only in what is left, capped by max_graph_tokens.
    cards, card_entities = [], []
    if system == "graph_v3":
        card_cap = policy["graph"]["max_graph_tokens"]
        for key in visited:
            block = "[KG entity]\n" + json.dumps(linking.merged_card(graph, index.group_of(key), links),
                                                 ensure_ascii=False, sort_keys=True)
            if (count("\n\n".join(cards + [block])) <= card_cap
                    and count("\n\n".join(blocks + cards + [block])) <= budget):
                cards.append(block)
                card_entities.append(key)
        trace["card_entities"] = card_entities
    text = "\n\n".join(blocks + cards)
    return {"system": system, "context": text, "context_tokens": count(text), "selected_ids": selected,
            "selected_parent_ids": sorted({parent_of(cid) for cid in selected}),
            "shared_prefix": prefix, "skipped_for_budget": skipped, "dense_used": dense is not None,
            "policy_version": policy["version"], **trace}


def full_context_text(policy: dict | None = None) -> dict:
    policy = policy or load_policy()
    records, _ = v.source_records()
    enc = tiktoken.get_encoding(policy["context_encoding"])
    text = "\n\n".join(f"[{r['chunk_id']}] {r['doc_id']} p.{r['page']} | {r.get('section') or ''}\n{r['text']}"
                       for r in records)
    return {"system": "full_context", "context": text, "context_tokens": len(enc.encode(text, disallowed_special=())),
            "selected_ids": [r["chunk_id"] for r in records], "dense_used": False}


# -------------------------------------------------------------- generation
def answer(system: str, question: str, run_dir: Path, call=v.api_call, use_dense: bool = True) -> dict:
    """Paid generation call. Same model, instructions and limits as v1/v2."""
    if not isinstance(question, str) or not question.strip() or len(question.encode()) > 8000:
        raise ValueError("Invalid question")
    config = v.read(v.CONFIG)
    run = Path(run_dir)
    run.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    try:
        if system == "full_context":
            retrieval = full_context_text()
        else:
            rows = row_corpus()
            dense = dense_ranking(question, rows, call=call) if use_dense else None
            needs_names = system in {"graph_v3", "vector_v3_lex"}
            retrieval = build_context(system, question, rows, dense, c.load_graph() if needs_names else None)
        v.write(run / "retrieval.json", retrieval)
        instructions = INSTRUCTIONS.read_text(encoding="utf-8")
        payload = {"model": config["generation_model"], "store": False,
                   "max_completion_tokens": config["max_completion_tokens"],
                   "messages": [{"role": "system", "content": instructions},
                                {"role": "user", "content": json.dumps(
                                    {"question": question, "untrusted_reference_documents": retrieval["context"]},
                                    ensure_ascii=False)}]}
        raw, api = call("chat/completions", payload, run / "api")
        choice = raw["choices"][0]
        message = choice["message"]
        if choice.get("finish_reason") != "stop" or not message.get("content") or message.get("refusal"):
            raise ValueError("Incomplete generation; raw response retained")
        result = {"status": "complete", "system": system, "question": question, "answer": message["content"],
                  "requested_model": config["generation_model"], "returned_model": raw.get("model"),
                  "usage": raw.get("usage", {}), "generation_api": api, "seconds": time.perf_counter() - started,
                  "selected_ids": retrieval["selected_ids"], "context_tokens": retrieval["context_tokens"],
                  "instruction_sha256": v.digest(instructions.encode()), "grading_performed": False}
        v.write(run / "answer.json", result)
        return result
    except Exception as exc:
        v.write(run / "failure.json", {"status": "failed", "error_type": type(exc).__name__, "grading_performed": False})
        raise
