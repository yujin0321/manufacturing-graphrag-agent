"""Benchmark v3 runner: retrieve -> seal -> (separately) grade evidence recall.

  # 1) offline, free: retrieval only (BM25 only unless the row index exists)
  python scripts/run_benchmark_v3.py retrieve --out kg_build/benchmark_v3/retrieval_run1
  # 2) separate step: read the private key only after step 1 is sealed
  python scripts/run_benchmark_v3.py grade --run kg_build/benchmark_v3/retrieval_run1
  # 3) paid: answers for the three systems (needs OPENAI_API_KEY)
  python scripts/run_benchmark_v3.py build-index
  python scripts/run_benchmark_v3.py answer --out kg_build/benchmark_v3/answers_run1 --repeat 3

Step 1 never opens evaluation/. Step 2 never changes step 1 outputs.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from imaks_kg.rag import comparison as c  # noqa: E402
from imaks_kg.rag import retrieval_v3 as r3  # noqa: E402
from imaks_kg.rag import vector as v  # noqa: E402
from imaks_kg.rag.chunking import parent_of  # noqa: E402

BENCH = v.REPO_ROOT / "docs/benchmark_graph_v3_20261028"
KEY = v.REPO_ROOT / "evaluation/benchmark_graph_v3_20261028/answer_key_PRIVATE.json"
SYSTEMS = ["vector_v3", "vector_v3_lex", "graph_v3"]
CODE = ["scripts/run_benchmark_v3.py", "scripts/validate_benchmark_v3_free.py", "src/imaks_kg/rag/retrieval_v3.py", "src/imaks_kg/rag/linking.py", "src/imaks_kg/rag/lexical.py",
        "src/imaks_kg/rag/chunking.py", "docs/graphrag_v3/policy.json", "docs/graphrag_v3/lexicon.json"]


def questions() -> list[dict]:
    lock = v.read(BENCH / "lock.json")
    path = BENCH / "questions.jsonl"
    if v.digest(path.read_bytes()) != lock["hashes"]["docs/benchmark_graph_v3_20261028/questions.jsonl"]:
        raise ValueError("Frozen v3 questions changed")
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def code_hashes() -> dict:
    return {p: v.digest((v.REPO_ROOT / p).read_bytes()) for p in CODE}


def retrieve(out: Path, bm25_only: bool = False) -> None:
    out.mkdir(parents=True, exist_ok=False)
    rows, graph = r3.row_corpus(), c.load_graph()
    dense_available = not bm25_only and (r3.ROW_INDEX / "manifest.json").exists()
    for q in questions():
        dense = r3.dense_ranking(q["question"], rows) if dense_available else None
        for system in SYSTEMS:
            result = r3.build_context(system, q["question"], rows, dense, graph if system != "vector_v3" else None)
            v.write(out / system / f"{q['id']}.json", result)
    seal = {"dense_used": dense_available, "code": code_hashes(),
            "files": {str(p.relative_to(out)): v.digest(p.read_bytes()) for p in sorted(out.rglob("*.json"))}}
    v.write(out / "seal.json", seal)
    print(f"sealed {len(seal['files'])} retrievals; dense_used={dense_available}")


def grade(run: Path) -> None:
    seal = v.read(run / "seal.json")
    for name, digest in seal["files"].items():
        if v.digest((run / name).read_bytes()) != digest:
            raise ValueError(f"Retrieval output changed after sealing: {name}")
    lock = v.read(BENCH / "lock.json")
    expected_key = lock["hashes"]["evaluation/benchmark_graph_v3_20261028/answer_key_PRIVATE.json"]
    if v.digest(KEY.read_bytes()) != expected_key:
        raise ValueError("Frozen private answer key changed")
    key = {q["id"]: q for q in v.read(KEY)["questions"]}
    hypotheses = {q["id"]: q["graph_hypothesis"] for q in questions()}
    report = {"dense_used": seal["dense_used"], "systems": {}, "per_question": {}}
    for system in SYSTEMS:
        found_total = needed_total = complete = 0
        tokens = []
        for qid, item in key.items():
            result = v.read(run / system / f"{qid}.json")
            selected = set(result["selected_ids"])
            # A row is satisfied only by that exact row, or by the whole parent table chunk.
            found = [e for e in item["evidence"] if e in selected or parent_of(e) in selected and "#r" not in e]
            found_total += len(found)
            needed_total += len(item["evidence"])
            complete += len(found) == len(item["evidence"])
            tokens.append(result["context_tokens"])
            report["per_question"].setdefault(qid, {"hypothesis": hypotheses[qid]})[system] = {
                "found": len(found), "needed": len(item["evidence"]),
                "missing": sorted(set(item["evidence"]) - set(found))}
        report["systems"][system] = {"evidence_recall": found_total / needed_total,
                                     "found": found_total, "needed": needed_total,
                                     "complete_questions": complete, "questions": len(key),
                                     "mean_context_tokens": sum(tokens) / len(tokens)}
    out = run / "grade_summary.json"
    v.write(out, report)
    print(json.dumps(report["systems"], ensure_ascii=False, indent=2))
    for qid, row in report["per_question"].items():
        cells = "  ".join(f"{s}={row[s]['found']}/{row[s]['needed']}" for s in SYSTEMS)
        print(f"{qid} [{row['hypothesis']}] {cells}")


def answer(out: Path, repeat: int) -> None:
    """Paid. Same question order for every system; each run is independent."""
    for q in questions():
        for system in ["full_context", "vector_v3", "vector_v3_lex", "graph_v3"]:
            for k in range(1, repeat + 1):
                r3.answer(system, q["question"], out / system / q["id"] / f"run{k}")
    v.write(out / "run_lock.json", {"code": code_hashes(), "repeat": repeat})


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("action", choices=["retrieve", "grade", "build-index", "answer"])
    p.add_argument("--bm25-only", action="store_true", help="Disable dense retrieval and paid query embeddings")
    p.add_argument("--out", type=Path)
    p.add_argument("--run", type=Path)
    p.add_argument("--repeat", type=int, default=3)
    a = p.parse_args()
    if a.action == "retrieve":
        retrieve(a.out, bm25_only=a.bm25_only)
    elif a.action == "grade":
        grade(a.run)
    elif a.action == "build-index":
        print(json.dumps(r3.build_row_index(), ensure_ascii=False, indent=2)[:2000])
    else:
        answer(a.out, a.repeat)


if __name__ == "__main__":
    main()
