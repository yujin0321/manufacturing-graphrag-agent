"""Build Document and Provenance records from preprocessed document outputs."""
import argparse
import json
from pathlib import Path

from imaks_kg.common.io_utils import read_csv_rows, write_jsonl
from imaks_kg.kg_build.preprocessed_abox import PreprocessedLayout
from imaks_kg.settings import REPO_ROOT


def load_jsonl(path):
    with Path(path).open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def build_documents(layout: PreprocessedLayout):
    _, rows = read_csv_rows(layout.doc_manifest)
    docs = []
    for r in rows:
        doc_id = r.get("doc_id") or r.get("document_id")
        docs.append({
            "id": doc_id,
            "labels": ["Document"],
            "properties": {
                "identifier": doc_id,
                "title": doc_id,
                "sourcePath": r.get("source_file") or r.get("sourcePath") or "",
                "sourceSha256": r.get("file_sha256") or r.get("sourceSha256") or "",
                "pageCount": r.get("page_count") or r.get("pageCount") or "",
            },
        })
    return docs


def provenance_from_chunk(chunk):
    chunk_id = chunk["chunk_id"]
    text = chunk.get("text", "")
    prov = {
        "id": f"prov:{chunk_id}",
        "labels": ["Provenance"],
        "properties": {
            "sourceKind": "document",
            "page": str(chunk.get("page", "")),
            "charStart": str(chunk.get("char_start", 0)),
            "charEnd": str(chunk.get("char_end", len(text))),
            "sourceQuote": text,
            "textSha256": chunk.get("text_sha256", ""),
            "fileSha256": chunk.get("source_file_sha256", ""),
        },
    }
    if chunk.get("table_id"):
        prov["properties"].update({"tableId": chunk["table_id"], "rowIndex": "1", "colIndex": "1"})
    return prov


def build_provenance(layout: PreprocessedLayout):
    return [provenance_from_chunk(c) for c in load_jsonl(layout.chunks_jsonl)]


def build(preprocessed_root=None, out_dir=None):
    layout = PreprocessedLayout.detect(preprocessed_root)
    out = Path(out_dir or (REPO_ROOT / "kg_build" / "latest"))
    docs = build_documents(layout)
    prov = build_provenance(layout)
    write_jsonl(out / "documents.jsonl", docs)
    write_jsonl(out / "provenance.jsonl", prov)
    return {"documents": docs, "provenance": prov, "out_dir": out}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--preprocessed", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    result = build(args.preprocessed, args.out)
    print(f"built {len(result['documents'])} documents and {len(result['provenance'])} provenance records")
    print(f"output: {result['out_dir']}")


if __name__ == "__main__":
    main()
