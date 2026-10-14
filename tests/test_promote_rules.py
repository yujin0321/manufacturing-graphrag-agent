"""Rule·Document 승격(B) 검사. 변환은 메모리에서 다시 돌려 확인한다.

실행: .\\.venv\\Scripts\\python.exe -m unittest tests.test_promote_rules -v   (저장소 루트에서, kg_build/seed.ttl 필요)
"""
import ast
import copy
import csv
import hashlib
import json
import re
import shutil
import sys
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

from pyshacl import validate
from rdflib import RDF, Graph, Literal, XSD

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from imaks_kg import settings  # noqa: E402
from imaks_kg.kg import preprocess_lock, promote_rules  # noqa: E402
from imaks_kg.kg.preprocess_lock import BPaths  # noqa: E402
from imaks_kg.kg.naming import IM, entity_iri  # noqa: E402

ONT = ROOT / "ontology_v1" / "ontology.ttl"
SHAPES = ROOT / "ontology_v1" / "shapes.ttl"
DOCS = ROOT / "preprocessed" / "documents"
SEED = ROOT / "imaks_data" / "kg_seed"
COL_TO_PROP = {"Nominal": "nominalValue", "WARN_LO": "warnLo", "WARN_HI": "warnHi", "CRIT_LO": "critLo", "CRIT_HI": "critHi"}


def shacl(dg):
    conforms, _, text = validate(dg, shacl_graph=Graph().parse(str(SHAPES)), ont_graph=Graph().parse(str(ONT)),
                                 inference="none")
    return conforms, text


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def one(g, s, p):
    vals = list(g.objects(s, p))
    assert len(vals) == 1, (s, p, vals)
    return vals[0]


class PromoteRules(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if not promote_rules.SEED_TTL.exists():
            raise unittest.SkipTest("kg_build/seed.ttl 없음(먼저 seed_to_rdf 실행)")
        cls.inp = promote_rules.load_inputs()
        g, cls.info = promote_rules.build_graph(cls.inp)
        cls.text = promote_rules.serialize(g)
        cls.g = Graph().parse(data=cls.text, format="turtle")
        cls.seed = cls.inp["seed_graph"]
        with (DOCS / "tables.jsonl").open(encoding="utf-8") as f:
            cls.tables = {t["table_id"]: t for t in (json.loads(line) for line in f if line.strip())}
        cls.nodes = read_csv(SEED / "nodes.csv")
        cls.edges = read_csv(SEED / "edges.csv")

    def rules(self, cls_name):
        return sorted(self.g.subjects(RDF.type, IM[cls_name]))

    def cell_provs(self, rule):
        return [p for p in self.g.objects(rule, IM.hasProvenance) if (p, IM.sourceKind, Literal("document")) in self.g]

    def table_cell(self, prov):
        t = self.tables[str(one(self.g, prov, IM.tableId))]
        r, c = int(one(self.g, prov, IM.rowIndex)) - 1, int(one(self.g, prov, IM.colIndex)) - 1
        cells = [x for x in t["cells"] if x["row"] == r and x["col"] == c]
        self.assertEqual(len(cells), 1)
        return t, cells[0]

    # ---- 개수
    def test_counts(self):
        self.assertEqual(len(self.rules("Document")), 7)
        self.assertEqual(len(self.rules("MaintenanceRule")), 8)
        self.assertEqual(len(self.rules("ThresholdRule")), 22)
        for c in ("OperationalRule", "AccessRule", "Station", "Sensor", "AnomalyEvent", "CausalLink"):
            self.assertEqual(self.rules(c), [], c)
        ids = sorted(str(one(self.g, r, IM.identifier)) for r in self.rules("MaintenanceRule"))
        self.assertEqual(ids, [f"MAINT-0{i}" for i in range(1, 9)])

    # ---- Document
    def test_documents_match_manifest(self):
        manifest = read_csv(DOCS / "doc_manifest.csv")
        by_id = {str(one(self.g, d, IM.identifier)): d for d in self.rules("Document")}
        self.assertEqual(set(by_id), {r["doc_id"] for r in manifest})
        for r in manifest:
            d = by_id[r["doc_id"]]
            self.assertEqual(str(one(self.g, d, IM.sourceSha256)), r["file_sha256"])
            self.assertEqual(int(one(self.g, d, IM.pageCount)), int(r["pages"]))
            self.assertEqual(str(one(self.g, d, IM.sourcePath)), r["file"])
            self.assertEqual(hashlib.sha256((ROOT / r["file"]).read_bytes()).hexdigest(), r["file_sha256"])
            self.assertTrue(str(one(self.g, d, IM.title)))

    # ---- 공통 Rule
    def test_every_rule_has_document_and_table_provenance(self):
        for r in self.rules("MaintenanceRule") + self.rules("ThresholdRule"):
            with self.subTest(str(r)):
                doc = one(self.g, r, IM.sourceDocument)
                self.assertIn((doc, RDF.type, IM.Document), self.g)
                provs = self.cell_provs(r)
                self.assertTrue(provs)
                for p in provs:
                    for f in ("page", "tableId", "rowIndex", "colIndex", "bbox", "textSha256", "sourceQuote"):
                        one(self.g, p, IM[f])
                    t, cell = self.table_cell(p)
                    self.assertEqual(t["doc_id"], str(one(self.g, doc, IM.identifier)))
                    self.assertEqual(int(one(self.g, p, IM.page)), t["page"])
                    self.assertEqual(str(one(self.g, p, IM.sourceQuote)), cell["text_normalized"])
                    self.assertEqual(str(one(self.g, p, IM.textSha256)),
                                     hashlib.sha256(cell["text_normalized"].encode("utf-8")).hexdigest())
                    self.assertEqual([float(x) for x in str(one(self.g, p, IM.bbox)).split(",")], cell["bbox"])

    def test_applies_to_sensor_is_seed_sensor(self):
        seed_sensors = set(self.seed.subjects(RDF.type, IM.Sensor))
        self.assertEqual(len(seed_sensors), 22)
        targets = []
        for r in self.rules("MaintenanceRule") + self.rules("ThresholdRule"):
            s = one(self.g, r, IM.appliesToSensor)
            self.assertIn(s, seed_sensors, str(r))
            targets.append(s)
        thr_targets = [one(self.g, r, IM.appliesToSensor) for r in self.rules("ThresholdRule")]
        self.assertEqual(set(thr_targets), seed_sensors)  # 센서당 1개
        self.assertEqual(len(thr_targets), len(set(thr_targets)))

    # ---- MaintenanceRule
    def test_maintenance_matches_seed(self):
        by_id = {r["nodeId"]: r for r in self.nodes}
        resolves = {e["fromId"]: e["toId"] for e in self.edges if e["type"] == "resolves"}
        triggers = {(e["fromId"], e["toId"]) for e in self.edges if e["type"] == "triggers"}
        for r in self.rules("MaintenanceRule"):
            nid = str(one(self.g, r, IM.sourceNodeId))
            row = by_id[nid]
            self.assertEqual(row["label"], "Maintenance")
            self.assertEqual(str(one(self.g, r, IM.identifier)), row["ruleId"])
            self.assertEqual(str(one(self.g, r, IM.priority)), row["priority"])
            # 2026-10-12 사용자 결정: conditionText = SOP-003 Trigger 셀, responseText = SOP-003 Action 셀
            sop = self.tables["SOP-003:p1:table1"]
            hdr = sop["rows_normalized"][0]
            srow = [x for x in sop["rows_normalized"][1:] if x[0] == row["ruleId"]]
            self.assertEqual(len(srow), 1)
            srow = dict(zip(hdr, srow[0]))
            self.assertEqual(str(one(self.g, r, IM.conditionText)), srow["Trigger"])
            self.assertEqual(str(one(self.g, r, IM.responseText)), srow["Action"])
            self.assertEqual(srow["Priority"], row["priority"])
            self.assertNotIn(Literal(row["action"]), set(self.g.objects(r, None)) - {Literal(srow["Action"])})
            self.assertEqual(str(one(self.g, r, IM.extractionMethod)), "table")
            quotes = {}
            for p in self.cell_provs(r):
                t, cell = self.table_cell(p)
                quotes[hdr[cell["col"]]] = str(one(self.g, p, IM.sourceQuote))
            self.assertEqual(quotes.get("Trigger"), srow["Trigger"])
            self.assertEqual(quotes.get("Action"), srow["Action"])
            self.assertEqual(list(self.g.objects(r, IM.ruleSeverity)), [])
            sensor_nid = resolves[nid]
            self.assertIn((sensor_nid, nid), triggers)
            self.assertEqual(one(self.g, r, IM.appliesToSensor), entity_iri(by_id[sensor_nid]["name"]))
            self.assertEqual(str(one(self.g, one(self.g, r, IM.sourceDocument), IM.identifier)), "SOP-003")
            provs = self.cell_provs(r)
            self.assertEqual(len(provs), 6)
            ids = {self.table_cell(p)[1]["text_normalized"] for p in provs if int(one(self.g, p, IM.colIndex)) == 1}
            self.assertEqual(ids, {row["ruleId"]})
            seed_provs = [p for p in self.g.objects(r, IM.hasProvenance) if (p, IM.sourceKind, Literal("seedCsv")) in self.g]
            row_ids = {str(x) for p in seed_provs for x in self.g.objects(p, IM.sourceRowId)}
            self.assertIn(nid, row_ids)
            self.assertEqual(len([x for x in row_ids if x.startswith("row:")]), 2)

    # ---- ThresholdRule
    def test_threshold_values_match_tables(self):
        for r in self.rules("ThresholdRule"):
            with self.subTest(str(r)):
                self.assertEqual(str(one(self.g, r, IM.extractionMethod)), "table")
                self.assertEqual(str(one(self.g, one(self.g, r, IM.sourceDocument), IM.identifier)), "SOP-002")
                self.assertEqual(list(self.g.objects(r, IM.ruleSeverity)), [])
                provs = self.cell_provs(r)
                self.assertEqual(len(provs), 8)
                seen = set()
                for p in provs:
                    t, cell = self.table_cell(p)
                    head = self.tables[t["continued_from"]] if t["continued_from"] else t
                    col_name = head["rows_normalized"][0][cell["col"]]
                    text = cell["text_normalized"]
                    if col_name in COL_TO_PROP:
                        prop = COL_TO_PROP[col_name]
                        lit = one(self.g, r, IM[prop])
                        self.assertEqual(lit.datatype, XSD.decimal)
                        expect = Decimal(text.split("±")[0].strip())
                        self.assertEqual(Decimal(str(lit)), expect, prop)
                        seen.add(prop)
                    elif col_name == "CRITICAL Response":
                        self.assertEqual(str(one(self.g, r, IM.responseText)), text)
                        seen.add("responseText")
                    elif col_name == "Sensor":
                        sensor = one(self.g, r, IM.appliesToSensor)
                        station = re.match(r"^(\S+) Thresholds$", t["caption"]).group(1)
                        self.assertEqual(sensor, entity_iri(f"{station}_{text}"))
                        self.assertEqual(str(one(self.g, r, IM.identifier)), f"SOP-002:THR:{station}_{text}")
                self.assertEqual(seen, set(COL_TO_PROP.values()) | {"responseText"})

    def test_threshold_values_match_preprocessed_file(self):
        rows = {r["sensor_id"]: r for r in read_csv(ROOT / "preprocessed" / "sensors" / "rules" / "sensor_thresholds.csv")}
        for r in self.rules("ThresholdRule"):
            name = str(one(self.seed, one(self.g, r, IM.appliesToSensor), IM.identifier))
            for prop in COL_TO_PROP.values():
                self.assertEqual(Decimal(str(one(self.g, r, IM[prop]))), Decimal(rows[name][prop]), (name, prop))

    def test_no_threshold_properties_on_sensors(self):
        for prop in COL_TO_PROP.values():
            for s, _, _ in self.g.triples((None, IM[prop], None)):
                self.assertIn((s, RDF.type, IM.ThresholdRule), self.g)
            for s, _, _ in self.seed.triples((None, IM[prop], None)):
                self.fail(f"seed.ttl에 {prop}: {s}")

    # ---- SHACL
    def test_seed_plus_rules_conforms(self):
        merged = promote_rules.merged_graph(self.seed, self.g)
        conforms, text = shacl(merged)
        self.assertTrue(conforms, text)

    def test_s9_catches_threshold_on_seed_sensor(self):
        merged = promote_rules.merged_graph(self.seed, self.g)
        merged.add((entity_iri("ST02_SEALING_TMP"), IM.critHi, Literal("210.0", datatype=XSD.decimal)))
        conforms, text = shacl(merged)
        self.assertFalse(conforms)
        self.assertEqual(set(re.findall(r"\b(S[0-9])[:：]", text)), {"S9"}, text)

    # ---- 보고서
    def test_mapping_reports(self):
        md, s = promote_rules.maint_mapping_md(self.info["maint"])
        self.assertEqual(len(re.findall(r"^\| MAINT-0\d ", md, re.M)), 8)
        self.assertEqual(s["rows"], 8)
        md2, s2 = promote_rules.threshold_mapping_md(self.info["thr"], self.inp["thr_csv"])
        self.assertEqual(s2["sensors"], 22)
        self.assertEqual(len([ln for ln in md2.splitlines() if ln.startswith("| ") and "SOP-002:THR:" in ln]), 22)

    # ---- 멈춤 조건
    def test_stops_on_duplicate_or_missing_maint_row(self):
        inp = copy.deepcopy(self.inp)
        t = next(x for x in inp["tables"] if x["table_id"] == "SOP-003:p1:table1")
        for c in t["cells"]:
            if c["row"] == 2 and c["col"] == 0:
                c["text_normalized"] = "MAINT-01"
        t["rows_normalized"][2][0] = "MAINT-01"
        with self.assertRaises(promote_rules.PromoteError):
            promote_rules.build_graph(inp)

    def test_stops_on_triggers_resolves_mismatch(self):
        inp = copy.deepcopy(self.inp)
        e = next(x for x in inp["edges"] if x["type"] == "resolves")
        e["toId"] = next(r["nodeId"] for r in inp["nodes"] if r["label"] == "Sensor" and r["nodeId"] != e["toId"])
        with self.assertRaises(promote_rules.PromoteError):
            promote_rules.build_graph(inp)

    def test_stops_on_priority_mismatch(self):
        inp = copy.deepcopy(self.inp)
        row = next(r for r in inp["nodes"] if r.get("ruleId") == "MAINT-01")
        row["priority"] = "LOW"
        with self.assertRaises(promote_rules.PromoteError) as cm:
            promote_rules.build_graph(inp)
        self.assertIn("priority", str(cm.exception))

    def test_stops_on_unmapped_sensor(self):
        inp = copy.deepcopy(self.inp)
        t = next(x for x in inp["tables"] if x["table_id"] == "SOP-002:p1:table2")
        for c in t["cells"]:
            if c["row"] == 1 and c["col"] == 0:
                c["text_normalized"] = "VIB"
        t["rows_normalized"][1][0] = "VIB"
        with self.assertRaises(promote_rules.PromoteError):
            promote_rules.build_graph(inp)

    # ---- 결정성
    def test_deterministic(self):
        g2, _ = promote_rules.build_graph(copy.deepcopy(self.inp))
        self.assertEqual(promote_rules.serialize(g2).encode("utf-8"), self.text.encode("utf-8"))

    def test_written_file_matches_if_present(self):
        if not promote_rules.RULES_TTL.exists():
            self.skipTest("kg_build/rules_deterministic.ttl 없음(먼저 promote_rules 실행)")
        self.assertEqual(promote_rules.RULES_TTL.read_text(encoding="utf-8"), self.text)

    # ---- 소스 검사
    def test_source_has_no_model_calls_or_eval_files(self):
        allowed = {"difflib", "json", "re", "sys", "collections", "decimal", "rdflib", "imaks_kg", "pathlib",
                   "argparse", "dataclasses", "datetime"}
        for path in (Path(promote_rules.__file__), Path(preprocess_lock.__file__)):
            with self.subTest(path.name):
                src = path.read_text(encoding="utf-8")
                for name in ("ground_truth", "nodes_factory"):
                    self.assertNotIn(name, src)
                self.assertIsNone(re.search(r"(?<!imaks_)\bdata/", src))
                mods = set()
                for node in ast.walk(ast.parse(src)):
                    if isinstance(node, ast.Import):
                        mods |= {a.name.split(".")[0] for a in node.names}
                    elif isinstance(node, ast.ImportFrom):
                        mods.add((node.module or "").split(".")[0])
                self.assertTrue(mods <= allowed, mods - allowed)
                for word in ("openai", "anthropic", "requests", "urllib", "http", "socket", "langchain", "transformers"):
                    self.assertNotIn(word, src.lower(), word)


class HashChainGuard(unittest.TestCase):
    """해시 사슬·의미 검사 반례. 입력을 임시 폴더에 복사해 바꾸고, 멈추면 아무 파일도 쓰지 않는지 확인한다."""

    DOC_FILES = ("doc_manifest.csv", "pages.jsonl", "tables.jsonl", "chunks.jsonl", "glyph_fixes.csv", "doc_profile.json")

    @classmethod
    def setUpClass(cls):
        if not settings.SEED_TTL.exists() or not settings.PREPROCESS_LOCK.exists():
            raise unittest.SkipTest("kg_build/seed.ttl 또는 harness/preprocess_lock.json 없음")

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        tmp = Path(self._tmp.name)
        (tmp / "docs").mkdir()
        (tmp / "code").mkdir()
        for n in self.DOC_FILES:
            shutil.copyfile(DOCS / n, tmp / "docs" / n)
        for n in preprocess_lock.CODE_NAMES:
            shutil.copyfile(settings.PREPROCESS_CODE_DIR / n, tmp / "code" / n)
        shutil.copyfile(settings.SENSOR_THRESHOLDS_CSV, tmp / "thr.csv")
        shutil.copyfile(settings.PREPROCESS_LOCK, tmp / "lock.json")
        self.paths = BPaths(doc_dir=tmp / "docs", thresholds_csv=tmp / "thr.csv", lock_file=tmp / "lock.json",
                            code_dir=tmp / "code", out_dir=tmp / "out", reports_dir=tmp / "reports")

    def tearDown(self):
        self._tmp.cleanup()

    # ---- 도구
    def outputs(self):
        return list(promote_rules.output_paths(self.paths).values())

    def assert_stops(self, expect_text):
        with self.assertRaises(promote_rules.PromoteError) as cm:
            promote_rules.run(self.paths)
        self.assertIn(expect_text, str(cm.exception))
        return str(cm.exception)

    def assert_no_outputs(self):
        for p in self.outputs():
            self.assertFalse(p.exists(), p)

    def edit_tables_crit_hi(self, new="205.0"):
        """SOP-002 ST02_SEALING TMP 행의 CRIT_HI 210.0 → new (셀·행 원문·정규화본 모두)."""
        path = self.paths.doc_dir / "tables.jsonl"
        recs = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
        t = next(r for r in recs if r["table_id"] == "SOP-002:p1:table2")
        self.assertEqual(t["rows_normalized"][0][6], "CRIT_HI")
        self.assertEqual([t["rows_normalized"][1][0], t["rows_normalized"][1][6]], ["TMP", "210.0"])
        t["rows_raw"][1][6] = new
        t["rows_normalized"][1][6] = new
        for c in t["cells"]:
            if c["row"] == 1 and c["col"] == 6:
                c["text_raw"] = new
                c["text_normalized"] = new
        with path.open("w", encoding="utf-8", newline="") as f:
            for r in recs:
                f.write(json.dumps(r, ensure_ascii=False))
                f.write(chr(10))
        return hashlib.sha256(path.read_bytes()).hexdigest()

    def refresh_records(self, name, new_hash):
        """lock (b)와 doc_profile 기록을 새 해시로 맞춘다(해시가 '우연히' 갱신된 경우를 흉내)."""
        lock = json.loads(self.paths.lock_file.read_text(encoding="utf-8"))
        key = next(k for k in lock["document_outputs"] if k.endswith("/" + name))
        lock["document_outputs"][key] = new_hash
        self.paths.lock_file.write_text(json.dumps(lock), encoding="utf-8")
        prof_path = self.paths.doc_dir / "doc_profile.json"
        prof = json.loads(prof_path.read_text(encoding="utf-8"))
        pkey = next(k for k in prof["output_sha256"] if k.endswith("/" + name))
        prof["output_sha256"][pkey] = new_hash
        prof_path.write_text(json.dumps(prof), encoding="utf-8")

    def replace_in(self, path, old, new):
        data = path.read_bytes()
        self.assertIn(old.encode("utf-8"), data)
        path.write_bytes(data.replace(old.encode("utf-8"), new.encode("utf-8"), 1))

    # ---- (vii) 정상 입력
    def test_vii_clean_copy_passes_with_same_outputs(self):
        self.assertEqual(preprocess_lock.check_chain(self.paths), [])
        res = promote_rules.run(self.paths)
        repo = {"rules": settings.RULES_TTL, "merged": settings.SEED_PLUS_RULES_TTL,
                "maint_md": promote_rules.OUT_MAINT_MD, "thr_md": promote_rules.OUT_THR_MD}
        for k, p in res["outs"].items():
            self.assertTrue(p.exists(), k)
            if repo[k].exists():
                self.assertEqual(p.read_bytes(), repo[k].read_bytes(), k)

    # ---- (i) 표 수치 변경
    def test_i_table_value_change_stops_without_output(self):
        self.edit_tables_crit_hi()
        msg = self.assert_stops("preprocessed/documents/tables.jsonl")
        self.assertIn("해시 사슬", msg)
        self.assert_no_outputs()

    # ---- (ii) 해시 기록까지 맞춰도 의미 검사가 멈춘다
    def test_ii_semantic_check_after_lock_refresh(self):
        new = self.edit_tables_crit_hi()
        self.refresh_records("tables.jsonl", new)
        self.assertEqual(preprocess_lock.check_chain(self.paths), [])
        msg = self.assert_stops("의미 검사")
        self.assertIn("ST02_SEALING_TMP critHi", msg)
        self.assert_no_outputs()

    # ---- (iii) pages 한 글자
    def test_iii_pages_one_char_change(self):
        self.replace_in(self.paths.doc_dir / "pages.jsonl", "Standard Operating", "Standard Operatinh")
        self.assert_stops("pages.jsonl")
        self.assert_no_outputs()

    # ---- (iv) doc_manifest PDF 해시
    def test_iv_manifest_pdf_hash_change(self):
        old = "89bb8bebc3e0bc6ac9a157a9bc30b6de09fb526711cbc1c9631258444fe865b7"  # SOP-003 PDF
        self.replace_in(self.paths.doc_dir / "doc_manifest.csv", old, "0" * 64)
        msg = self.assert_stops("doc_manifest file_sha256 " + "0" * 64)
        self.assertIn("SOP_003_MaintenanceRules.pdf", msg)
        self.assert_no_outputs()

    # ---- (v) doc_profile 기록 불일치
    def test_v_doc_profile_mismatch(self):
        prof_path = self.paths.doc_dir / "doc_profile.json"
        prof = json.loads(prof_path.read_text(encoding="utf-8"))
        key = next(k for k in prof["output_sha256"] if k.endswith("/chunks.jsonl"))
        prof["output_sha256"][key] = "f" * 64
        prof_path.write_text(json.dumps(prof), encoding="utf-8")
        errs = preprocess_lock.check_chain(self.paths)
        self.assertEqual(len(errs), 1, errs)
        self.assert_stops("doc_profile.json output_sha256[chunks.jsonl]")
        self.assert_no_outputs()

    # ---- (vi) 전처리 코드 변경
    def test_vi_preprocess_code_change(self):
        path = self.paths.code_dir / "documents.py"
        path.write_bytes(path.read_bytes() + "# 변경".encode("utf-8"))
        self.assert_stops(preprocess_lock.CODE_CHANGED_MSG)
        self.assert_no_outputs()

    def test_threshold_file_change_stops(self):
        self.replace_in(self.paths.thresholds_csv, "185.0", "186.0")
        self.assert_stops("임계값 파일")
        self.assert_no_outputs()

    def test_missing_lock_stops(self):
        self.paths.lock_file.unlink()
        self.assert_stops("lock 없음")
        self.assert_no_outputs()

    # ---- (viii) 멈추면 기존 출력이 그대로
    def test_viii_existing_outputs_untouched_on_stop(self):
        promote_rules.run(self.paths)
        before = {p: (p.stat().st_mtime_ns, p.read_bytes()) for p in self.outputs()}
        self.edit_tables_crit_hi()
        self.assert_stops("tables.jsonl")
        for p, (mtime, data) in before.items():
            self.assertEqual(p.stat().st_mtime_ns, mtime, p)
            self.assertEqual(p.read_bytes(), data, p)


if __name__ == "__main__":
    unittest.main()
