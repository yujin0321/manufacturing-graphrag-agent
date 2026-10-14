"""문서 전처리 산출물의 불변 조건 검사 (먼저 imaks_kg.preprocess.documents 실행)."""
import csv
import hashlib
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "preprocessed" / "documents"
DOCS = {"SOP-001", "SOP-002", "SOP-003", "SOP-004", "DS-THERM-2200", "DS-MECH-4400", "DS-ELEC-3300"}


def jl(name):
    return [json.loads(l) for l in (OUT / name).read_text(encoding="utf-8").splitlines() if l.strip()]


class DocumentOutputs(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.pages = jl("pages.jsonl")
        cls.tables = jl("tables.jsonl")
        cls.chunks = jl("chunks.jsonl")
        with (OUT / "doc_manifest.csv").open(encoding="utf-8", newline="") as f:
            cls.manifest = list(csv.DictReader(f))
        with (OUT / "glyph_fixes.csv").open(encoding="utf-8", newline="") as f:
            cls.fixes = list(csv.DictReader(f))

    def test_manifest(self):
        self.assertEqual({m["doc_id"] for m in self.manifest}, DOCS)
        self.assertEqual(sum(int(m["pages"]) for m in self.manifest), 10)
        for m in self.manifest:
            self.assertFalse(Path(m["file"]).is_absolute())
            self.assertTrue((ROOT / m["file"]).exists())
            self.assertEqual(len(m["file_sha256"]), 64)

    def test_pages_and_raw_preserved(self):
        self.assertEqual(len(self.pages), 10)
        sop1 = next(p for p in self.pages if p["doc_id"] == "SOP-001" and p["page"] == 1)
        self.assertIn("R&D;", sop1["text_raw"])
        self.assertNotIn("R&D;", sop1["text_normalized"])
        self.assertIn("ST01_FILLING → ST02_SEALING", sop1["text_normalized"])

    def test_ordinary_fi_untouched(self):
        elec = next(p for p in self.pages if p["doc_id"] == "DS-ELEC-3300")
        self.assertIn("Specifications", elec["text_normalized"])
        self.assertIn("Specifications", elec["text_raw"])
        # 합자나 's'가 바뀐 곳은 모두 기호 폰트 글자였다
        for f in self.fixes:
            if f["scope"] == "page_text" and f["before"] in ("fi", "fl", "›", "‡", "s"):
                self.assertIn("Symbol font", f["reason"])

    def test_sigma_and_geq(self):
        s2 = " ".join(p["text_normalized"] for p in self.pages if p["doc_id"] == "SOP-002")
        self.assertIn("deviation >3σ", s2)
        mech = next(p for p in self.pages if p["doc_id"] == "DS-MECH-4400")
        self.assertIn("≥ 18 kHz", mech["text_normalized"])

    def test_tables(self):
        self.assertEqual(len(self.tables), 24)
        cont = [t for t in self.tables if t["continued_from"]]
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
                self.assertEqual(pt[(c["doc_id"], c["page"])][c["char_start"]:c["char_end"]].replace("\n", " "),
                                 c["text"].replace("\n", " "))
                self.assertLessEqual(len(c["text"]), 1000)
            else:
                self.assertTrue(c["table_id"] and c["bbox"])
        self.assertEqual(len([c for c in self.chunks if c["kind"] == "table"]), 24)

    def test_sop002_threshold_rows_match_sensor_file(self):
        p = json.loads((OUT / "doc_profile.json").read_text(encoding="utf-8"))
        self.assertEqual(p["sop002_sensor_rows"], 22)
        self.assertTrue(p["sop002_matches_sensor_file"])
        self.assertEqual(p["warnings"], [])

    def test_glyph_fixes_recorded(self):
        self.assertTrue(self.fixes)
        self.assertEqual(list(self.fixes[0].keys()),
                         ["doc_id", "page", "scope", "location", "before", "after", "reason", "context"])
        self.assertTrue(any(f["after"] == "→" for f in self.fixes))


if __name__ == "__main__":
    unittest.main()
