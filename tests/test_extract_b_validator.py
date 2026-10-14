"""검증기 시험: 실제 전처리 청크로 위치·해시를 확인한다. 정답 파일은 읽지 않는다."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_b_helpers as h  # noqa: E402

from imaks_kg.extract.request_builder import load_prompt_files  # noqa: E402
from imaks_kg.extract.validator import (apply_duplicate_flags, rule_is_valid_for_kg, schema_errors,  # noqa: E402
                                        validate_response)

STORE, ALLOW = h.real_store(), h.real_allow()
_, SCHEMA = load_prompt_files()
sha = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()  # noqa: E731


def val(doc, resp, **kw):
    text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)
    sent = h.sent_ids(STORE, doc)
    merged = [t.chunk_id for u in h.make_units(STORE.chunks_by_doc[doc]) for t in u.titles]
    return validate_response(text, doc_id=doc, store=STORE, allowlist=ALLOW, sent_chunk_ids=sent,
                             merged_title_ids=merged, schema=SCHEMA, model_info={"model": "m"}, **kw)


class Blocking(unittest.TestCase):
    def test_not_json_is_blocking(self):
        r = val("SOP-001", "not json {")
        self.assertFalse(r.accepted)
        self.assertTrue(r.blocking_errors[0].startswith("json_parse_error"))
        self.assertEqual(r.rules, [])

    def test_schema_violations_are_blocking(self):
        good = h.sop001_response(STORE)
        cases = {}
        a = json.loads(json.dumps(good)); a["rules"][0]["class"] = "SafetyRule"; cases["class"] = a
        b = json.loads(json.dumps(good)); del b["rules"][0]["action"]; cases["missing"] = b
        c = json.loads(json.dumps(good)); c["rules"][0]["extra"] = 1; cases["extra"] = c
        d = json.loads(json.dumps(good)); d["rules"][0]["evidence"] = []; cases["noevidence"] = d
        e = json.loads(json.dumps(good)); e["rules"][0]["evidence"][0]["table_row"] = 0; cases["row0"] = e
        for name, resp in cases.items():
            r = val("SOP-001", resp)
            self.assertFalse(r.accepted, name)
            self.assertTrue(r.blocking_errors[0].startswith("schema_error"), name)

    def test_good_response_passes_schema(self):
        self.assertEqual(schema_errors(h.sop001_response(STORE), SCHEMA), [])
        self.assertTrue(val("SOP-001", h.sop001_response(STORE)).accepted)

    def test_response_schema_has_no_forbidden_key_names(self):
        keys = set()

        def walk(o):
            if isinstance(o, dict):
                for k, v in o.items():
                    keys.add(k)
                    walk(v)
            elif isinstance(o, list):
                for v in o:
                    walk(v)
        walk(SCHEMA)
        self.assertFalse(keys & {"status", "quality", "alarms", "day", "shift", "batch_id", "nominal", "sever" + "ity"})
        self.assertIn("ruleSeverity", keys)


class Flags(unittest.TestCase):
    def test_each_flag_case(self):
        r = val("SOP-001", h.sop001_response(STORE))
        by = {x["rule_index"]: x for x in r.rules}
        self.assertEqual(by[0]["flags"], [])
        self.assertEqual(by[1]["flags"], [])
        self.assertEqual(by[2]["flags"], ["evidence_not_found"])
        self.assertEqual(by[3]["flags"], ["id_not_in_allowlist"])
        self.assertIsNone(by[2]["evidence"][0]["provenance"])  # 못 찾으면 위치를 계산하지 않는다
        self.assertEqual([rule_is_valid_for_kg(x) for x in r.rules], [True, True, False, False])

    def test_table_position_out_of_range(self):
        r = val("SOP-003", h.sop003_response(STORE))
        self.assertEqual(r.rules[0]["flags"], [])
        self.assertEqual(r.rules[1]["flags"], ["table_position_out_of_range"])
        for row, col in ((0 + 10, 1), (2, 7), (None, 2)):
            resp = h.sop003_response(STORE)
            resp["rules"][1]["evidence"][0].update({"table_row": row, "table_col": col})
            self.assertIn("table_position_out_of_range", val("SOP-003", resp).rules[1]["flags"], (row, col))

    def test_table_coordinates_on_prose_chunk_flagged(self):
        resp = h.sop001_response(STORE)
        resp["rules"][0]["evidence"][0].update({"table_row": 1, "table_col": 1})
        self.assertIn("table_position_out_of_range", val("SOP-001", resp).rules[0]["flags"])

    def test_duplicate_identifier_flags_all_members(self):
        r = val("SOP-001", h.sop001_response(STORE))
        r2 = val("SOP-001", h.sop001_response(STORE))
        rules = r.rules + r2.rules
        self.assertEqual(apply_duplicate_flags(rules), 8)  # 같은 응답 두 벌이라 모든 identifier가 둘씩
        self.assertTrue(all("duplicate_identifier" in x["flags"] for x in rules))
        self.assertEqual(apply_duplicate_flags(rules), 8)  # 다시 불러도 결과가 같다(플래그·세부 중복 없음)
        self.assertEqual(rules[0]["flags"].count("duplicate_identifier"), 1)
        solo = val("SOP-001", h.sop001_response(STORE)).rules
        self.assertEqual(apply_duplicate_flags(solo), 0)

    def test_coverage_gap_cases(self):
        resp = h.sop001_response(STORE)
        resp["coverage"] = resp["coverage"][1:]                       # 청크 하나 빠짐
        resp["coverage"][0]["rules"] = [0, 9]                          # 없는 규칙 번호
        for e in resp["coverage"]:                                     # 규칙 1을 가리키던 항목을 제외로 바꿈
            if e["rules"] == [1]:
                e.update({"coverage_status": "excluded", "rules": [], "reason": "duplicate"})
        r = val("SOP-001", resp)
        details = " ".join(f["detail"] for f in r.doc_flags)
        self.assertTrue(all(f["flag"] == "coverage_gap" for f in r.doc_flags))
        self.assertIn("coverage에 이 청크가 없습니다", details)
        self.assertIn("벗어납니다", details)
        self.assertTrue(any("coverage_gap" in x["flags"] for x in r.rules))   # 어느 항목도 가리키지 않는 규칙
        self.assertTrue(all(rule_is_valid_for_kg(x) for x in r.rules if x["flags"] == ["coverage_gap"]))

    def test_empty_content_flag(self):
        resp = h.sop001_response(STORE)
        resp["rules"][0].update({"condition": " ", "action": ""})
        self.assertIn("empty_content", val("SOP-001", resp).rules[0]["flags"])

    def test_evidence_from_other_document_not_found(self):
        resp = h.sop001_response(STORE)
        resp["rules"][0]["evidence"][0]["chunk_id"] = "SOP-003:p1:text1"
        self.assertIn("evidence_not_found", val("SOP-001", resp).rules[0]["flags"])


class PositionsAndHashes(unittest.TestCase):
    def test_prose_position_matches_page_text(self):
        r = val("SOP-001", h.sop001_response(STORE))
        for x in r.rules[:2]:
            ev = x["evidence"][0]
            p = ev["provenance"]
            self.assertTrue(p["resolved"])
            page = STORE.pages[("SOP-001", p["page"])]
            self.assertEqual(" ".join(page[p["charStart"]:p["charEnd"]].split()), " ".join(ev["source_quote"].split()))
            self.assertEqual(p["textSha256"], sha(ev["source_quote"]))
            # 2026-10-14: 저장되는 인용은 쪽 텍스트에서 잘라 낸 실제 구간이고, 모델 인용은 model_quote에 남는다
            self.assertEqual(p["sourceQuote"], page[p["charStart"]:p["charEnd"]])
            self.assertEqual(ev["source_quote"], p["sourceQuote"])
            self.assertEqual(p["textSha256"], sha(page[p["charStart"]:p["charEnd"]]))
            self.assertIn("model_quote", ev)
            self.assertEqual(p["documentSha256"], STORE.doc_sha256("SOP-001"))
            self.assertEqual(p["charEnd"] - p["charStart"], len(ev["source_quote"]))

    def test_position_across_a_line_break_in_page_text(self):
        # 쪽 텍스트에서는 줄바꿈인데 청크에서는 공백인 규칙 청크(실제 데이터에서 찾는다)
        pick = None
        for c in STORE.chunks_by_doc["SOP-001"]:
            if c.kind == "rule":
                if "\n" in STORE.pages[("SOP-001", c.page)][c.char_start:c.char_end]:
                    pick = c
                    break
        self.assertIsNotNone(pick)
        q = pick.text[:40]
        resp = {"rules": [h.rule("OperationalRule", q, evidence=[h.ev(pick.chunk_id, q)])],
                "coverage": h.coverage(STORE, "SOP-001", {pick.chunk_id: [0]})}
        p = val("SOP-001", resp).rules[0]["evidence"][0]["provenance"]
        self.assertEqual(p["charStart"], pick.char_start)
        # 인용 전체가 줄바꿈을 넘는 경우
        q2 = pick.text[: pick.text.index(" ", 60) + 12]
        resp["rules"][0]["evidence"][0]["source_quote"] = q2
        p2 = val("SOP-001", resp).rules[0]["evidence"][0]["provenance"]
        page = STORE.pages[("SOP-001", pick.page)]
        self.assertEqual(" ".join(page[p2["charStart"]:p2["charEnd"]].split()), " ".join(q2.split()))

    def test_table_position_bbox_and_hash(self):
        r = val("SOP-003", h.sop003_response(STORE))
        e0, e1 = r.rules[0]["evidence"]
        p0, p1 = e0["provenance"], e1["provenance"]
        self.assertEqual((p0["tableId"], p0["rowIndex"], p0["colIndex"]), ("SOP-003:p1:table1", 3, 4))
        self.assertEqual((p1["rowIndex"], p1["colIndex"]), (3, 5))
        self.assertEqual(p0["textSha256"], sha(e0["source_quote"]))
        self.assertEqual(e0["source_quote"], h.table_cell(STORE, "SOP-003:p1:table1", 3, 4))
        tb = json.loads([l for l in (STORE.documents_dir / "tables.jsonl").read_text(encoding="utf-8").splitlines()
                         if '"SOP-003:p1:table1"' in l][0])
        cell = [c for c in tb["cells"] if (c["row"], c["col"]) == (2, 3)][0]   # 원본은 0부터
        self.assertEqual(p0["bbox"], ",".join(f"{v:g}" for v in cell["bbox"]))

    def test_row_level_quote_gets_start_column_and_ambiguous_is_unresolved(self):
        tid, cid = "SOP-003:p1:table1", "SOP-003:p1:table1:chunk"
        row = " | ".join(STORE.tables[tid].rows[2][3:5])
        resp = {"rules": [h.rule("MaintenanceRule", "c", evidence=[h.ev(cid, row, row=3)])],
                "coverage": h.coverage(STORE, "SOP-003", {cid: [0]})}
        p = val("SOP-003", resp).rules[0]["evidence"][0]["provenance"]
        self.assertEqual((p["rowIndex"], p["colIndex"]), (3, 4))
        # 같은 글자가 여러 셀에 있고 좌표가 없으면 추측하지 않는다("HIGH"는 여러 행에 있음)
        resp["rules"][0]["evidence"] = [h.ev(cid, "HIGH")]
        r = val("SOP-003", resp).rules[0]
        self.assertIn("position_unresolved", r["flags"])
        self.assertFalse(r["evidence"][0]["provenance"]["resolved"])
        # 좌표 없이 한 셀에만 있는 글자는 정해진다
        resp["rules"][0]["evidence"] = [h.ev(cid, "Activate dehumidifier")]
        p = val("SOP-003", resp).rules[0]["evidence"][0]["provenance"]
        self.assertEqual((p["rowIndex"], p["colIndex"]), (9, 5))

    def test_quote_in_wrong_cell_is_unresolved(self):
        resp = h.sop003_response(STORE)
        resp["rules"][0]["evidence"][0].update({"table_row": 4, "table_col": 4})
        r = val("SOP-003", resp).rules[0]
        self.assertIn("position_unresolved", r["flags"])

    def test_ambiguous_prose_quote_is_unresolved(self):
        c = STORE.chunk_by_id["SOP-001:p1:text1"]
        word = "ST0"
        self.assertGreater(c.text.count(word), 1)
        resp = {"rules": [h.rule("OperationalRule", "x", evidence=[h.ev(c.chunk_id, word)])],
                "coverage": h.coverage(STORE, "SOP-001", {c.chunk_id: [0]})}
        self.assertIn("position_unresolved", val("SOP-001", resp).rules[0]["flags"])

    def test_identifier_assignment(self):
        r = val("SOP-001", h.sop001_response(STORE))
        self.assertEqual(r.rules[0]["identifier"], "RULE-ST02-01")
        self.assertEqual(r.rules[0]["identifier_source"], "printed")
        self.assertEqual(r.rules[2]["identifier"], "SOP-001:p1:RULE-ST02-01:1")
        self.assertEqual(r.rules[3]["identifier"], "SOP-001:p1:RULE-ST02-01:2")

    def test_revalidation_is_deterministic(self):
        text = json.dumps(h.sop001_response(STORE), ensure_ascii=False)
        a, b = val("SOP-001", text), val("SOP-001", text)
        self.assertEqual(json.dumps(a.rules, sort_keys=True), json.dumps(b.rules, sort_keys=True))


if __name__ == "__main__":
    unittest.main()
