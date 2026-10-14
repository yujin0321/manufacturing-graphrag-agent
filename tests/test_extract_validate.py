"""C: 응답 자동 검사(스키마, 인용 원문 일치, ID 목록)와 Provenance 좌표·해시, LLM 응답 처리(가짜 응답만).

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_validate -v
"""
import copy
import hashlib
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_fakes  # noqa: E402
import extract_support as S  # noqa: E402
from imaks_kg.extract import llm, validate  # noqa: E402


def item(**kw):
    base = {"class": "OperationalRule", "conditionText": "c", "responseText": "r", "ruleSeverity": None,
            "sensors": [], "targetStations": [], "sourceQuote": "", "ruleIdInText": None, "actionSteps": []}
    base.update(kw)
    return base


class Validate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.ctx = S.ctx()
        cls.docs = cls.ctx["docs"]
        cls.chunks = cls.ctx["chunks_by_id"]
        cls.sensors = set(cls.ctx["seed"]["sensors"])
        cls.stations = set(cls.ctx["seed"]["stations"])

    def check(self, cid, it):
        return validate.validate_item(it, self.chunks[cid], self.docs, self.sensors, self.stations)

    def page_text(self, cid):
        c = self.chunks[cid]
        return self.docs["pages"][(c["doc_id"], c["page"])]["text_normalized"]

    # ---------------------------------------------------------------- 거부
    def test_schema_violation_rejected(self):
        cid = "SOP-001:p1:RULE-ST01-01"
        q = self.chunks[cid]["text"]
        bad = [
            {k: v for k, v in item(sourceQuote=q).items() if k != "actionSteps"},
            item(sourceQuote=q) | {"extra": 1},
            item(sourceQuote=q, **{"class": "SafetyRule"}),
            item(sourceQuote=q, sensors="ST01_FILLING_FLW"),
            item(sourceQuote=q, ruleSeverity=3),
        ]
        for it in bad:
            cand, err = self.check(cid, it)
            self.assertIsNone(cand)
            self.assertEqual(err[0], "schema")

    def test_top_level_schema_rejected(self):
        cid = "SOP-001:p1:RULE-ST01-01"
        for parsed in ({"rules": [], "note": "x"}, [], {"rule": []}, "text"):
            res = llm.CallResult(key=cid, ok=True, parsed=parsed)
            cands, rej = validate.validate_response(res, self.chunks[cid], self.docs, self.sensors, self.stations)
            self.assertEqual(cands, [])
            self.assertEqual([r["reason_code"] for r in rej], ["schema"])

    def test_quote_not_in_source_rejected(self):
        cid = "SOP-001:p1:RULE-ST02-02"
        for q in ("RULE-ST02-02: TMP > 210 °C (CRITICAL) - emergency stop ST02, ST03, ST04.", "TMP above 210°C", " "):
            cand, err = self.check(cid, item(sourceQuote=q))
            self.assertIsNone(cand)
            self.assertIn(err[0], ("quote_not_in_chunk", "quote_empty"))

    def test_out_of_list_ids_rejected(self):
        cid = "SOP-001:p1:RULE-ST01-01"
        q = self.chunks[cid]["text"]
        cand, err = self.check(cid, item(sourceQuote=q, sensors=["ST01_FILLING_FLW", "ST01_FILLING_XYZ"]))
        self.assertEqual(err[0], "sensor_not_in_list")
        cand, err = self.check(cid, item(sourceQuote=q, targetStations=["ST05_UNKNOWN"]))
        self.assertEqual(err[0], "station_not_in_list")
        cand, err = self.check(cid, item(sourceQuote=q, sensors=["ST01_FILLING_FLW"], targetStations=["ST01_FILLING"]))
        self.assertIsNotNone(cand)

    def test_invented_rule_id_and_level_rejected(self):
        cid = "SOP-001:p1:RULE-ST01-01"
        q = self.chunks[cid]["text"]
        self.assertEqual(self.check(cid, item(sourceQuote=q, ruleIdInText="RULE-ST01-09"))[1][0], "rule_id_not_in_chunk")
        self.assertEqual(self.check(cid, item(sourceQuote=q, ruleSeverity="CRITICAL"))[1][0],
                         "rule_severity_not_in_chunk")

    # ---------------------------------------------------------------- 좌표·해시
    def test_rule_chunk_coords_match_page_text(self):
        # RULE-ST02-04는 쪽 텍스트에서 줄바꿈이 있는 규칙(청크는 줄바꿈→공백)
        cid = "SOP-001:p1:RULE-ST02-04"
        q = "due to shared electrical coupling. Monitor ST04_PACKAGING-SPD"
        cand, err = self.check(cid, item(sourceQuote=q))
        self.assertIsNone(err)
        p = cand["provenance"]
        pt = self.page_text(cid)
        self.assertEqual(p["charStart"], self.chunks[cid]["char_start"] + self.chunks[cid]["text"].index(q))
        self.assertEqual(p["charEnd"] - p["charStart"], len(q))
        self.assertIn("\n", pt[p["charStart"]:p["charEnd"]])
        self.assertEqual(pt[p["charStart"]:p["charEnd"]].replace("\n", " "), q)
        self.assertEqual(p["textSha256"], hashlib.sha256(q.encode("utf-8")).hexdigest())
        self.assertEqual(p["page"], 1)
        self.assertEqual(p["doc_id"], "SOP-001")

    def test_text_chunk_coords_exact(self):
        cid = "SOP-002:p1:text1"
        q = "Threshold hierarchy: CRIT_LO < WARN_LO < NOMINAL < WARN_HI < CRIT_HI."
        cand, err = self.check(cid, item(sourceQuote=q, **{"class": "ThresholdRule"}))
        self.assertIsNone(err)
        p = cand["provenance"]
        self.assertEqual(self.page_text(cid)[p["charStart"]:p["charEnd"]], q)

    def test_page2_coords(self):
        cid = "SOP-004:p2:RULE-ACCESS-04"
        q = "immediate escalation to the Safety Officer regardless of role."
        cand, err = self.check(cid, item(sourceQuote=q, **{"class": "AccessRule"}))
        self.assertIsNone(err)
        p = cand["provenance"]
        self.assertEqual(p["page"], 2)
        self.assertEqual(self.page_text(cid)[p["charStart"]:p["charEnd"]].replace("\n", " "), q)

    def test_table_chunk_coords(self):
        cid = "SOP-003:p1:table1:chunk"
        q = "Trigger: PRS <3.3 bar for >15 min; Action: Inspect filter and pump"
        cand, err = self.check(cid, item(sourceQuote=q, **{"class": "MaintenanceRule"}))
        self.assertIsNone(err)
        p = cand["provenance"]
        self.assertNotIn("charStart", p)
        t = self.docs["tables"][p["tableId"]]
        row = t["rows_normalized"][p["rowIndex"] - 1]
        self.assertEqual(row[0], "MAINT-04")
        self.assertEqual(p["colIndex"], [4, 5])
        self.assertEqual([row[c - 1] for c in p["colIndex"]], ["PRS <3.3 bar for >15 min", "Inspect filter and pump"])
        self.assertEqual(p["textSha256"], hashlib.sha256(q.encode("utf-8")).hexdigest())
        cells = [c for c in t["cells"] if c["row"] == p["rowIndex"] - 1 and c["col"] + 1 in p["colIndex"]]
        x0 = min(c["bbox"][0] for c in cells)
        self.assertEqual(float(p["bbox"].split(",")[0]), x0)

    def test_table_quote_across_rows_rejected(self):
        cid = "SOP-003:p1:table1:chunk"
        text = self.chunks[cid]["text"]
        i = text.index("Priority: HIGH\nRule ID: MAINT-02")
        q = text[i:i + 30]
        cand, err = self.check(cid, item(sourceQuote=q))
        self.assertEqual(err[0], "quote_spans_table_rows")
        cand, err = self.check(cid, item(sourceQuote="[SOP-003:p1:table1] 1. Predictive"))
        self.assertEqual(err[0], "quote_spans_table_rows")

    def test_candidate_ids_by_position(self):
        cid = "SOP-001:p1:RULE-ST03-02"
        sp = extract_fakes.specs(self.chunks)[cid]
        res = llm.CallResult(key=cid, ok=True, parsed={"rules": list(reversed(copy.deepcopy(sp)))})
        cands, rej = validate.validate_response(res, self.chunks[cid], self.docs, self.sensors, self.stations)
        self.assertEqual(rej, [])
        self.assertEqual([c["candidate_id"] for c in cands], [f"{cid}:r1", f"{cid}:r2"])
        self.assertLess(cands[0]["provenance"]["charStart"], cands[1]["provenance"]["charStart"])
        self.assertEqual(cands[0]["ruleSeverity"], None)
        self.assertEqual(cands[1]["ruleSeverity"], "CRITICAL")

    # ---------------------------------------------------------------- 응답 처리(가짜)
    def test_llm_response_handling(self):
        chunks = self.chunks
        msgs = extract_fakes.build(["SOP-001:p2:RULE-SRV01-01", "SOP-001:p2:RULE-SRV01-02",
                                    "SOP-001:p2:RULE-CAF01-02", "SOP-001:p1:RULE-ST01-01"])
        with S.tmpdir() as tmp:
            client = llm.FakeClient(extract_fakes.write(Path(tmp) / "fake", msgs))
            req = self.ctx["requests"][0][1]
            fb = llm.call(client, req, "SOP-001:p2:RULE-SRV01-01")
            self.assertTrue(fb.ok)
            self.assertTrue(fb.fallback_used)
            self.assertEqual(fb.served_model, extract_fakes.FAKE_FALLBACK_MODEL)
            self.assertEqual(fb.parsed["rules"][0]["sourceQuote"], chunks["SOP-001:p2:RULE-SRV01-01"]["text"])
            self.assertTrue(fb.request_id.startswith("req_fake_"))
            ref = llm.call(client, req, "SOP-001:p2:RULE-SRV01-02")
            self.assertFalse(ref.ok)
            self.assertEqual(ref.failure, "stop_reason=refusal")
            self.assertIsNone(ref.parsed)
            mt = llm.call(client, req, "SOP-001:p2:RULE-CAF01-02")
            self.assertFalse(mt.ok)
            self.assertIsNone(mt.parsed)
            ok = llm.call(client, req, "SOP-001:p1:RULE-ST01-01")
            self.assertTrue(ok.ok)
            self.assertFalse(ok.fallback_used)
            self.assertEqual(ok.served_model, "claude-opus-5-5")

    def test_sdk_exceptions_classified_single_call(self):
        msgs = {"A": {"__raise__": "rate_limit"}, "B": {"__raise__": "status"}, "C": {"__raise__": "connection"}}
        with S.tmpdir() as tmp:
            client = llm.FakeClient(extract_fakes.write(Path(tmp) / "fake", msgs))
            req = self.ctx["requests"][0][1]
            a, b, c = (llm.call(client, req, k) for k in "ABC")
            self.assertEqual((a.error_class, b.error_class, c.error_class),
                             (llm.TRANSIENT_RATE, llm.AMBIGUOUS, llm.AMBIGUOUS))
            self.assertTrue(a.abort and b.abort and c.abort)
            self.assertTrue(a.failure.startswith("TRANSIENT_RATE: RateLimitError"))


if __name__ == "__main__":
    unittest.main()
