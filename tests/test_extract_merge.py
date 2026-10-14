"""C: B 규칙과의 병합(MAINT 병합 기준)과 RDF 결과에서 B 값 불변 (가짜 응답만).

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_merge -v
"""
import sys
import unittest
from pathlib import Path

from rdflib import RDF, Graph, URIRef

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_support as S  # noqa: E402
from imaks_kg.extract import merge, to_rdf, validate  # noqa: E402
from imaks_kg.extract.common import ExtractError  # noqa: E402
from imaks_kg.kg.naming import IM  # noqa: E402

PROTECTED = (RDF.type, IM.appliesToSensor, IM.conditionText, IM.responseText, IM.priority, IM.identifier,
             IM.actionTarget, IM.sourceDocument)
MAINT02_ROW = ("Rule ID: MAINT-02; Sensor: CUR; Station: ST02_SEALING; Trigger: CUR DRIFT >1.0 A for 30+ min; "
               "Action: Inspect sealing jaw; Priority: HIGH")


class Merge(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.ctx = S.ctx()
        cls.b = cls.ctx["b"]
        cls.chunks = cls.ctx["chunks_by_id"]

    def cand(self, cid, n=1, **kw):
        it = {"class": "MaintenanceRule", "conditionText": "", "responseText": "", "ruleSeverity": None,
              "sensors": [], "targetStations": [], "sourceQuote": "", "ruleIdInText": None, "actionSteps": []}
        it.update(kw)
        c, err = validate.validate_item(it, self.chunks[cid], self.ctx["docs"], set(self.ctx["seed"]["sensors"]),
                                        set(self.ctx["seed"]["stations"]))
        self.assertIsNone(err, err)
        c.update({"candidate_id": f"{cid}:r{n}", "item_index": n - 1, "served_model": "m", "fallback_used": False,
                  "request_id": ""})
        return c

    def maint02(self, **kw):
        base = dict(conditionText="CUR DRIFT >1.0 A for 30+ min", responseText="Inspect sealing jaw",
                    sensors=["ST02_SEALING_CUR"], targetStations=["ST02_SEALING"], sourceQuote=MAINT02_ROW,
                    ruleIdInText="MAINT-02")
        base.update(kw)
        return self.cand("SOP-003:p1:table1:chunk", 2, **base)

    def test_id_match_merges_without_new_rule(self):
        c = self.maint02(ruleIdInText="MAINT-02")
        recs, conflicts = merge.merge([c], self.b, self.chunks)
        self.assertTrue(recs[0]["merge"]["merged"])
        self.assertEqual(recs[0]["merge"]["basis"], "id")
        self.assertEqual(recs[0]["identifier"], "MAINT-02")
        self.assertEqual(conflicts, [])
        g = to_rdf.build_graph(recs, "t", self.b, self.ctx["seed"])
        self.assertEqual(len(list(g.subjects(IM.identifier, None))), 0)  # 새 Rule 없음
        b_iri = URIRef(self.b["rules"]["MAINT-02"]["iri"])
        self.assertEqual(set(g.subjects(IM.hasProvenance, None)), {b_iri})
        self.assertEqual({p for _, p, _ in g.triples((b_iri, None, None))}, {IM.hasProvenance})
        prov = next(g.objects(b_iri, IM.hasProvenance))
        self.assertEqual(str(next(g.objects(prov, IM.extractionMethod))), "llm")

    def test_normalized_id_match(self):
        c = self.maint02()
        c["ruleIdInText"] = "maint - 02"  # 정규화(대문자, 공백 제거)
        recs, _ = merge.merge([c], self.b, self.chunks)
        self.assertEqual(recs[0]["merge"]["b_identifier"], "MAINT-02")

    def test_table_row_match_merges(self):
        c = self.cand("SOP-003:p1:table1:chunk", 4, conditionText="PRS <3.3 bar for >15 min",
                      responseText="Inspect filter and pump", sensors=["ST01_FILLING_PRS"],
                      targetStations=["ST01_FILLING"],
                      sourceQuote="Trigger: PRS <3.3 bar for >15 min; Action: Inspect filter and pump")
        recs, conflicts = merge.merge([c], self.b, self.chunks)
        self.assertEqual(recs[0]["merge"], {"merged": True, "basis": "table_row", "b_identifier": "MAINT-04",
                                            "b_iri": self.b["rules"]["MAINT-04"]["iri"]})
        self.assertEqual(conflicts, [])

    def test_different_values_recorded(self):
        c = self.maint02(conditionText="CUR DRIFT >1.0 A for 30+ min at ST02_SEALING", sensors=["ST04_PACKAGING_SPD"],
                         targetStations=["ST04_PACKAGING"], **{"class": "OperationalRule"})
        recs, conflicts = merge.merge([c], self.b, self.chunks)
        self.assertTrue(recs[0]["merge"]["merged"])
        fields = {x["field"]: x for x in conflicts}
        self.assertEqual(set(fields), {"class", "sensors", "stations", "conditionText"})
        self.assertEqual(fields["class"]["llm_value"], "OperationalRule")
        self.assertEqual(fields["class"]["b_value"], "MaintenanceRule")
        self.assertEqual(fields["conditionText"]["b_value"], "CUR DRIFT >1.0 A for 30+ min")
        for x in conflicts:
            self.assertIn("SOP-003:p1:table1 row 3", x["llm_source"])
            self.assertIn("rule_MAINT_02", x["b_source"])
        # 1차 검토 CSV에도 들어간다
        from imaks_kg.extract.review import round1_rows
        rows = round1_rows(recs, conflicts)
        self.assertEqual(sorted(r["item_id"] for r in rows if r["row_type"] == "merge_conflict"),
                         sorted(x["conflict_id"] for x in conflicts))

    def test_different_ids_not_merged_rule_st02_02(self):
        # SOP-001 RULE-ST02-02(TMP > 210°C)와 SOP-002 ST02 TMP 임계값(critHi 210)은 센서·수치가 같아도 합치지 않는다
        cid = "SOP-001:p1:RULE-ST02-02"
        c = self.cand(cid, 1, conditionText="TMP > 210°C", responseText="emergency stop ST02, ST03, ST04.",
                      sensors=["ST02_SEALING_TMP"], targetStations=["ST02_SEALING", "ST03_LABELLING", "ST04_PACKAGING"],
                      sourceQuote=self.chunks[cid]["text"], ruleIdInText="RULE-ST02-02", ruleSeverity="CRITICAL",
                      **{"class": "ThresholdRule"})
        thr = self.b["rules"]["SOP-002:THR:ST02_SEALING_TMP"]
        self.assertEqual(thr["sensors"], ["ST02_SEALING_TMP"])
        recs, conflicts = merge.merge([c], self.b, self.chunks)
        self.assertFalse(recs[0]["merge"]["merged"])
        self.assertEqual(recs[0]["identifier"], "RULE-ST02-02")
        self.assertEqual(conflicts, [])
        g = to_rdf.build_graph(recs, "t", self.b, self.ctx["seed"])
        self.assertEqual([str(o) for o in g.objects(None, IM.identifier)], ["RULE-ST02-02"])
        self.assertNotIn(URIRef(thr["iri"]), set(g.subjects()))

    def test_id_present_but_not_b_blocks_row_merge(self):
        # ID가 B에 없으면 같은 표 행을 인용해도 합치지 않는다(ID가 다른 규칙)
        c = self.maint02()
        c["ruleIdInText"] = "RULE-X-01"
        recs, _ = merge.merge([c], self.b, self.chunks)
        self.assertFalse(recs[0]["merge"]["merged"])

    def test_identifier_collisions_and_uniqueness(self):
        cid = "SOP-001:p1:RULE-ST03-02"
        a = self.cand(cid, 1, sourceQuote="RULE-ST03-02: CNT below 110 pcs/min — check for label jam.",
                      ruleIdInText="RULE-ST03-02", **{"class": "OperationalRule"})
        b = self.cand(cid, 2, sourceQuote="Below 100 (CRITICAL): halt.", ruleIdInText="RULE-ST03-02",
                      **{"class": "OperationalRule"})
        other = self.cand("SOP-001:p2:RULE-ST04-03", 1, sourceQuote="verify RULE-ST02-04.", ruleIdInText="RULE-ST02-04",
                          **{"class": "OperationalRule"})
        own = self.cand("SOP-001:p1:RULE-ST02-04", 1, sourceQuote=self.chunks["SOP-001:p1:RULE-ST02-04"]["text"],
                        ruleIdInText="RULE-ST02-04", **{"class": "OperationalRule"})
        recs, _ = merge.merge([a, b, other, own], self.b, self.chunks)
        ids = {r["candidate_id"]: r["identifier"] for r in recs}
        self.assertEqual(ids[f"{cid}:r1"], f"{cid}:r1")
        self.assertEqual(ids[f"{cid}:r2"], f"{cid}:r2")
        self.assertEqual(ids["SOP-001:p1:RULE-ST02-04:r1"], "RULE-ST02-04")  # 자기 청크의 rule_id
        self.assertEqual(ids["SOP-001:p2:RULE-ST04-03:r1"], "SOP-001:p2:RULE-ST04-03:r1")
        self.assertEqual(len(set(ids.values())), len(ids))
        bad = [dict(r) for r in recs]
        bad[0]["identifier"] = bad[1]["identifier"]
        with self.assertRaises(ExtractError):
            merge.check_unique(bad, self.b)

    def test_e2e_b_values_unchanged_and_unique(self):
        with S.tmpdir() as tmp:
            run_dir = S.fake_run(tmp, "t-merge")
            S.fill_round1(run_dir)
            from imaks_kg.extract import review
            review.make_round2(run_dir)
            review.apply_review(run_dir)
            res = to_rdf.run(run_dir, Path(tmp) / "kg")
            combined = res["merged_graph"]
            bg = Graph().parse(str(self.ctx["rules_ttl"]))
            for rule in self.b["rules"].values():
                s = URIRef(rule["iri"])
                for p in PROTECTED:
                    self.assertEqual(set(bg.objects(s, p)), set(combined.objects(s, p)), (s, p))
                # B의 기존 출처는 그대로, 덧붙은 것은 llm 재확인뿐
                added = set(combined.objects(s, IM.hasProvenance)) - set(bg.objects(s, IM.hasProvenance))
                for pv in added:
                    self.assertEqual(str(next(combined.objects(pv, IM.extractionMethod))), "llm")
            self.assertLessEqual(len(bg), len(combined))
            for t in bg:
                self.assertIn(t, combined)
            idents = [str(o) for s, _, o in combined.triples((None, IM.identifier, None))
                      if any(combined.triples((s, RDF.type, IM[c])) for c in
                             ("OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule"))]
            self.assertEqual(len(idents), len(set(idents)))
            final = [r for r in res["final_graph"].subjects(IM.hasProvenance, None)]
            maint_reconfirmed = {str(s) for s in final if str(s).endswith(tuple(f"rule_MAINT_0{i}" for i in range(1, 9)))}
            self.assertEqual(len(maint_reconfirmed), 8)


if __name__ == "__main__":
    unittest.main()
