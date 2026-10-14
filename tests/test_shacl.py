"""SHACL 예제 실행 테스트.

통과 예제(pass_*)는 적합이어야 하고, 실패 예제(fail_*)는 의도한 규칙(S1~S5, L1~L4)만 위반해야 한다.
실행: .\\.venv\\Scripts\\python.exe -m unittest tests.test_shacl -v   (저장소 루트에서)
"""
import re
import unittest
from pathlib import Path

from pyshacl import validate
from rdflib import Graph

ROOT = Path(__file__).resolve().parents[1]
ONT = ROOT / "ontology_v1" / "ontology.ttl"
SHAPES = ROOT / "ontology_v1" / "shapes.ttl"
GUARDS = ROOT / "guards" / "leakage_shapes.ttl"
EXAMPLES = ROOT / "ontology_v1" / "examples"
GUARD_EXAMPLES = ROOT / "guards" / "examples"

# 실패 예제가 위반해야 하는 규칙 코드(메시지 앞부분). 이것만 위반해야 한다.
EXPECTED = {
    "fail_01_sensor_without_station.ttl": {"S1"},
    "fail_02_sensor_two_stations.ttl": {"S1"},
    "fail_03_effect_not_station.ttl": {"S3"},
    "fail_04_no_evidence.ttl": {"S4"},
    "fail_05_score_out_of_range.ttl": {"S5"},
}
GUARD_EXPECTED = {
    "fail_event_instance.ttl": {"L1"},
    "fail_forbidden_predicate.ttl": {"L3"},
    "fail_gt_identifier.ttl": {"L4"},
}


def run(data_path=None, data_text=None, shapes=SHAPES):
    dg = Graph()
    if data_path is not None:
        dg.parse(str(data_path), format="turtle")
    else:
        dg.parse(data=data_text, format="turtle")
    sg = Graph().parse(str(shapes), format="turtle")
    og = Graph().parse(str(ONT), format="turtle")
    conforms, report_graph, report_text = validate(dg, shacl_graph=sg, ont_graph=og, inference="none")
    return conforms, report_text


def codes(report_text):
    """보고서 문장에서 규칙 코드(S1, L3 등)를 모은다."""
    return set(re.findall(r"\b([SL][0-9])[:：]", report_text))


HEADER = """@prefix im: <https://example.org/imaks/v1#> .
@prefix inst: <https://example.org/imaks/id/> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""


class ShaclExamples(unittest.TestCase):
    def test_pass_examples_conform(self):
        files = sorted(EXAMPLES.glob("pass_*.ttl"))
        self.assertEqual(len(files), 5)
        for f in files:
            with self.subTest(f.name):
                ok, text = run(f)
                self.assertTrue(ok, text)

    def test_fail_examples_violate_only_intended_rule(self):
        files = sorted(EXAMPLES.glob("fail_*.ttl"))
        self.assertEqual(len(files), 5)
        for f in files:
            with self.subTest(f.name):
                ok, text = run(f)
                self.assertFalse(ok, f"{f.name}는 위반이어야 합니다")
                self.assertEqual(codes(text), EXPECTED[f.name], text)

    def test_leakage_guards(self):
        ok, text = run(GUARD_EXAMPLES / "pass_clean_input.ttl", shapes=GUARDS)
        self.assertTrue(ok, text)
        for name, expected in GUARD_EXPECTED.items():
            with self.subTest(name):
                ok, text = run(GUARD_EXAMPLES / name, shapes=GUARDS)
                self.assertFalse(ok, name)
                self.assertEqual(codes(text), expected, text)


class ShaclExtraNegatives(unittest.TestCase):
    """10개 예제 밖의 보조 반례. 근거 번호표 일치, 출처 필드, 하위 유형 배타성."""

    ST = """
inst:A a im:Station ; im:identifier "A" ; im:stationType "SEALING" ; im:zone "Z" ; im:hasSensor inst:SA .
inst:SA a im:Sensor ; im:identifier "SA" ; im:sensorType "CUR" ; im:unit "A" .
inst:B a im:Station ; im:identifier "B" ; im:stationType "PACKAGING" ; im:zone "Z" ; im:hasSensor inst:SB .
inst:SB a im:Sensor ; im:identifier "SB" ; im:sensorType "SPD" ; im:unit "m/s" .
"""
    H64 = "0" * 63 + "1"
    WIN = f"""
inst:w a im:Provenance ; im:sourceKind "timeseries" ; im:fileName "f.csv" ; im:sensorId "SB" ;
    im:intervalStart "2026-01-01T00:00:00"^^xsd:dateTime ; im:intervalEnd "2026-01-01T01:00:00"^^xsd:dateTime ;
    im:fileSha256 "{'0' * 63 + '1'}" ; im:windowId "W1" .
"""

    def check(self, body, expected_code):
        ok, text = run(data_text=HEADER + self.ST + self.WIN + body)
        self.assertFalse(ok, body)
        self.assertIn(expected_code, codes(text), text)

    def test_sop_evidence_without_rule_ids(self):
        self.check('inst:l a im:CausalLink ; im:hasCause inst:A ; im:hasEffect inst:B ; im:hasEvidence "SOPRule" ; im:likelihoodScore 0.7 .', "S6")

    def test_timeseries_evidence_without_window(self):
        self.check('inst:l a im:CausalLink ; im:hasCause inst:A ; im:hasEffect inst:B ; im:hasEvidence "TimeseriesCorrelation" ; im:likelihoodScore 0.7 .', "S6")

    def test_rule_id_not_existing(self):
        self.check('inst:l a im:CausalLink ; im:hasCause inst:A ; im:hasEffect inst:B ; im:hasEvidence "SOPRule" ; im:ruleIds "NOPE" ; im:likelihoodScore 0.7 .', "S6")

    def test_window_not_registered(self):
        self.check('inst:l a im:CausalLink ; im:hasCause inst:A ; im:hasEffect inst:B ; im:hasEvidence "TimeseriesCorrelation" ; im:windowId "UNREGISTERED" ; im:likelihoodScore 0.7 .', "S6")

    def test_self_loop(self):
        self.check('inst:l a im:CausalLink ; im:hasCause inst:A ; im:hasEffect inst:A ; im:hasEvidence "TimeseriesCorrelation" ; im:windowId "W1" ; im:likelihoodScore 0.7 .', "S3")

    def test_unknown_evidence_value(self):
        self.check('inst:l a im:CausalLink ; im:hasCause inst:A ; im:hasEffect inst:B ; im:hasEvidence "Unknown" ; im:windowId "W1" ; im:likelihoodScore 0.7 .', "S4")

    def test_negative_lag(self):
        self.check('inst:l a im:CausalLink ; im:hasCause inst:A ; im:hasEffect inst:B ; im:hasLag -5 ; im:hasEvidence "TimeseriesCorrelation" ; im:windowId "W1" ; im:likelihoodScore 0.7 .', "S5")

    def test_event_with_two_subtypes(self):
        self.check('inst:SA im:triggers inst:e . inst:e a im:Spike , im:Drift .', "S2")

    def test_event_without_sensor(self):
        self.check('inst:e a im:Spike .', "S2")

    def test_document_provenance_missing_fields(self):
        self.check('inst:p a im:Provenance ; im:sourceKind "document" ; im:page "1"^^xsd:positiveInteger .', "S7")

    def test_bad_hash_pattern(self):
        self.check('inst:p a im:Provenance ; im:sourceKind "seedCsv" ; im:fileName "nodes.csv" ; im:sourceRowId "N0013" ; im:textSha256 "XYZ" .', "S7")

    def test_rule_without_document(self):
        self.check('inst:r a im:OperationalRule ; im:identifier "R1" .', "S8")


if __name__ == "__main__":
    unittest.main()
