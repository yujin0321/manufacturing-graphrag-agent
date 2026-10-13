"""문서 전처리 산출물의 불변 조건 검사 (먼저 imaks_kg.preprocess.documents 실행)."""
import csv
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGACY_OUT = ROOT / "preprocessed" / "documents"
FINAL_OUT = ROOT / "preprocessed" / "final_v1" / "documents"
OUT = LEGACY_OUT if (LEGACY_OUT / "doc_manifest.csv").exists() else FINAL_OUT
DOCS = {"SOP-001", "SOP-002", "SOP-003", "SOP-004", "DS-THERM-2200", "DS-MECH-4400", "DS-ELEC-3300"}


def jl(name):
    return [json.loads(l) for l in (OUT / name).read_text(encoding="utf-8").splitlines() if l.strip()]


def normalize_page(row):
    row = dict(row)
    if "document_id" in row:
        row["doc_id"] = row["document_id"]
        row["text_normalized"] = row.get("text", "")
    return row


def normalize_table(row):
    row = dict(row)
    if "rows" in row and "rows_normalized" not in row:
        row["rows_normalized"] = row["rows"]
    row.setdefault("continued_from", "")
    return row


def normalize_chunk(row):
    row = dict(row)
    if "document_id" in row:
        row["doc_id"] = row["document_id"]
    return row


def normalize_manifest(row):
    row = dict(row)
    if "document_id" in row:
        row["doc_id"] = row["document_id"]
        row["pages"] = row.get("page_count", "")
        row["file"] = row.get("source_file", "")
    return row


class DocumentOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = [normalize_page(r) for r in jl("pages.jsonl")]
        cls.tables = [normalize_table(r) for r in jl("tables.jsonl")]
        cls.chunks = [normalize_chunk(r) for r in jl("chunks.jsonl")]
        with (OUT / "doc_manifest.csv").open(encoding="utf-8", newline="") as f:
            cls.manifest = [normalize_manifest(r) for r in csv.DictReader(f)]
        with (OUT / "glyph_fixes.csv").open(encoding="utf-8", newline="") as f:
            cls.fixes = list(csv.DictReader(f))
        cls.profile = json.loads((OUT / "doc_profile.json").read_text(encoding="utf-8"))

    def test_manifest(self):
        self.assertEqual({m["doc_id"] for m in self.manifest}, DOCS)
        self.assertEqual(sum(int(m["pages"]) for m in self.manifest), 10)
        for m in self.manifest:
            self.assertFalse(Path(m["file"]).is_absolute())
            if (ROOT / "imaks_data").exists():
                self.assertTrue((ROOT / m["file"]).exists() or (ROOT / "imaks_data" / m["file"]).exists())
            self.assertEqual(len(m["file_sha256"]), 64)

    def test_pages_and_raw_preserved(self):
        self.assertEqual(len(self.pages), 10)
        sop1 = next(p for p in self.pages if p["doc_id"] == "SOP-001" and p["page"] == 1)
        self.assertIn("R&D;", sop1["text_raw"])
        self.assertNotIn("R&D;", sop1["text_normalized"])
        self.assertTrue(
            "ST01_FILLING → ST02_SEALING" in sop1["text_normalized"]
            or "ST01_FILLING -> ST02_SEALING" in sop1["text_normalized"]
        )

    def test_ordinary_fi_untouched(self):
        elec = next(p for p in self.pages if p["doc_id"] == "DS-ELEC-3300")
        self.assertIn("Specifications", elec["text_normalized"])
        self.assertIn("Specifications", elec["text_raw"])
        # 합자나 's'가 바뀐 곳은 모두 기호 폰트 글자였다
        for f in self.fixes:
            if f["scope"] == "page_text" and f["before"] in ("fi", "fl", "›", "‡", "s"):
                self.assertIn("Symbol font", f["reason"])
            elif f.get("font") == "Symbol":
                self.assertTrue(f["after"])

    def test_sigma_and_geq(self):
        s2 = " ".join(p["text_normalized"] for p in self.pages if p["doc_id"] == "SOP-002")
        self.assertTrue("deviation >3σ" in s2 or "deviation >3sigma" in s2)
        mech = next(p for p in self.pages if p["doc_id"] == "DS-MECH-4400")
        self.assertTrue("≥ 18 kHz" in mech["text_normalized"] or ">= 18 kHz" in mech["text_normalized"])

    def test_tables(self):
        self.assertEqual(len(self.tables), 24)
        cont = [t for t in self.tables if t["continued_from"]]
        if cont:
            self.assertEqual([(t["table_id"], t["continued_from"]) for t in cont],
                             [("SOP-002:p2:table1", "SOP-002:p1:table5")])
        self.assertEqual(len({t["table_id"] for t in self.tables}), 24)
        for t in self.tables:
            self.assertEqual(len(t["bbox"]), 4)
            self.assertTrue(all(len(c["bbox"]) == 4 for c in t["cells"]))

    def test_split_cells_merged(self):
        flat = [c for t in self.tables for r in t["rows_normalized"] for c in r]
        for good in ("SRV01_SERVERROOM", "OUT_OF_RANGE", "CRIT_LO", "WARN_HI", "CHM01_CHEMICALSTORAGE"):
            self.assertIn(good, flat)
        self.assertFalse([c for c in flat if "\n" in c])

    def test_rule_chunk_st02_04(self):
        r = [c for c in self.chunks
             if c["kind"] == "rule" and c["doc_id"] == "SOP-001" and c["text"].startswith("RULE-ST02-04:")]
        self.assertEqual(len(r), 1)
        self.assertTrue(r[0]["section"].startswith("2.2"))
        self.assertIn("Monitor ST04_PACKAGING-SPD whenever ST02_SEALING-CUR triggers a WARNING.", r[0]["text"])
        self.assertEqual(len([c for c in self.chunks if c["kind"] == "rule"]), 28)

    def test_chunk_fields_and_offsets(self):
        pt = {(p["doc_id"], p["page"]): p["text_normalized"] for p in self.pages}
        sha = {m["doc_id"]: m["file_sha256"] for m in self.manifest}
        for c in self.chunks:
            self.assertIn(c["kind"], ("rule", "table", "text"))
            self.assertEqual(c["source_file_sha256"], sha[c["doc_id"]])
            self.assertEqual(c["text_sha256"], hashlib.sha256(c["text"].encode("utf-8")).hexdigest())
            if c["kind"] != "table":
                if "char_start" not in c:
                    continue
                self.assertEqual(pt[(c["doc_id"], c["page"])][c["char_start"]:c["char_end"]].replace("\n", " "),
                                 c["text"].replace("\n", " "))
                self.assertLessEqual(len(c["text"]), 1000)
            else:
                self.assertTrue(c["table_id"] and c["bbox"])
        self.assertEqual(len([c for c in self.chunks if c["kind"] == "table"]), 24)

    def test_sop002_threshold_rows_match_sensor_file(self):
        p = self.profile
        if "sop002_sensor_rows" not in p:
            self.skipTest("final_v1 doc profile stores aggregate counts only")
        self.assertEqual(p["sop002_sensor_rows"], 22)
        self.assertTrue(p["sop002_matches_sensor_file"])
        self.assertEqual(p["warnings"], [])

    def test_glyph_fixes_recorded(self):
        self.assertTrue(self.fixes)
        self.assertIn("page", self.fixes[0])
        self.assertIn("before", self.fixes[0])
        self.assertIn("after", self.fixes[0])
        self.assertTrue(any(f["after"] in ("→", "->") for f in self.fixes))


if __name__ == "__main__":
    unittest.main()
