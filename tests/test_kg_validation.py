import json
import tempfile
import unittest
from pathlib import Path

from imaks_kg.eval.metrics import evaluate
from imaks_kg.kg_build import rule_extract
from imaks_kg.kg_build.llm_rule_extract import extract_json_array, normalize_records
from imaks_kg.kg_build.preprocessed_abox import PreprocessedLayout, build_station_sensor
from imaks_kg.kg_build.rdf_export import export_ttl
from imaks_kg.kg_build.rule_extract import (
    extract_threshold_rules,
    sop002_threshold_table_contexts,
    split_condition_action,
)


class KgValidationTests(unittest.TestCase):
    def test_split_condition_action(self):
        cond, action = split_condition_action("RULE-X: TMP > 210°C (CRITICAL) — emergency stop ST02.")
        self.assertEqual(cond, "TMP > 210°C (CRITICAL)")
        self.assertEqual(action, "emergency stop ST02")

    def test_station_sensor_from_preprocessed_only(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "sensors" / "input"
            p.mkdir(parents=True)
            (p / "ts_input.csv").write_text(
                "timestamp,zone,station_id,sensor_id,sensor_type,value,unit\n"
                "t,Production Area,ST01_FILLING,ST01_FILLING_TMP,TMP,1,°C\n",
                encoding="utf-8",
            )
            layout = PreprocessedLayout(root)
            stations, sensors, rels = build_station_sensor(layout)
            self.assertEqual(len(stations), 1)
            self.assertEqual(len(sensors), 1)
            self.assertEqual(rels[0]["type"], "hasSensor")

    def test_processed_style_sensor_path_is_supported(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            p = root / "sensors"
            p.mkdir(parents=True)
            (p / "timeseries_input_clean.csv").write_text(
                "timestamp,day,shift,batch_id,zone,station_id,sensor_id,sensor_type,value,unit\n"
                "t,1,M,B,Production Area,ST01_FILLING,ST01_FILLING_TMP,TMP,1,°C\n",
                encoding="utf-8",
            )
            layout = PreprocessedLayout(root)
            self.assertEqual(layout.sensor_input.name, "timeseries_input_clean.csv")
            stations, sensors, _ = build_station_sensor(layout)
            self.assertEqual(stations[0]["id"], "ST01_FILLING")
            self.assertEqual(sensors[0]["id"], "ST01_FILLING_TMP")

    def test_evaluate_content_match(self):
        pred = [{"ruleId": "R1", "class": "OperationalRule", "condition": "TMP > 210 C", "action": "stop"}]
        truth = [{"ruleId": "G1", "class": "OperationalRule", "condition": "TMP > 210 C", "action": "stop"}]
        summary, pairs = evaluate(pred, truth, threshold=0.6)
        self.assertEqual(len(pairs), 1)
        self.assertEqual(summary["matched_count"], 1)

    def test_llm_json_records_are_normalized(self):
        raw = """```json
        [{"ruleId":"RULE-X","class":"OperationalRule","condition":"TMP > 1","action":"stop",
          "sourceDocument":"SOP-001","provenanceId":"prov:SOP-001:p1:text1"}]
        ```"""
        rows = normalize_records(extract_json_array(raw))
        self.assertEqual(rows[0]["extractionMethod"], "llm")
        self.assertEqual(rows[0]["ruleId"], "RULE-X")

    def test_sop002_threshold_mapping_uses_document_headings_and_continuation(self):
        pages = [
            {"doc_id": "SOP-002", "page": 1, "text": "ST01_FILLING Thresholds\nSRV01_SERVERROOM Thresholds"},
            {"doc_id": "SOP-002", "page": 2, "text": "HUM %RH 25\nWRH01_WAREHOUSE Thresholds"},
        ]
        header = ["Sensor", "Unit", "CRIT_LO", "WARN_LO", "Nominal", "WARN_HI", "CRIT_HI", "CRITICAL Response"]
        tables = [
            {"doc_id": "SOP-002", "page": 1, "table_id": "SOP-002:p1:table1", "bbox": [0, 10, 0, 0],
             "rows": [header, ["TMP", "°C", "1", "2", "3", "4", "5", "stop"]]},
            {"doc_id": "SOP-002", "page": 1, "table_id": "SOP-002:p1:table2", "bbox": [0, 20, 0, 0],
             "rows": [header, ["TMP", "°C", "1", "2", "3", "4", "5", "stop"]]},
            {"doc_id": "SOP-002", "page": 2, "table_id": "SOP-002:p2:table1", "bbox": [0, 5, 0, 0],
             "rows": [["HUM", "%RH", "25", "30", "45", "60", "65", "alert"]]},
            {"doc_id": "SOP-002", "page": 2, "table_id": "SOP-002:p2:table2", "bbox": [0, 15, 0, 0],
             "rows": [header, ["HUM", "%RH", "25", "30", "45", "60", "65", "alert"]]},
        ]
        contexts = sop002_threshold_table_contexts(
            tables, pages, {"ST01_FILLING", "SRV01_SERVERROOM", "WRH01_WAREHOUSE"}
        )
        self.assertEqual(
            [(c["table_id"], c["station"], c["continuation"]) for c in contexts],
            [
                ("SOP-002:p1:table1", "ST01_FILLING", False),
                ("SOP-002:p1:table2", "SRV01_SERVERROOM", False),
                ("SOP-002:p2:table1", "SRV01_SERVERROOM", True),
                ("SOP-002:p2:table2", "WRH01_WAREHOUSE", False),
            ],
        )

        rules, audit = extract_threshold_rules(
            tables,
            pages,
            {"ST01_FILLING", "SRV01_SERVERROOM", "WRH01_WAREHOUSE"},
            {
                "ST01_FILLING_TMP", "SRV01_SERVERROOM_TMP",
                "SRV01_SERVERROOM_HUM", "WRH01_WAREHOUSE_HUM",
            },
            return_audit=True,
        )
        self.assertIn("RULE-THR-SRV01-HUM-CRIT", {r.ruleId for r in rules})
        self.assertTrue(next(a for a in audit if a["table_id"] == "SOP-002:p2:table1")["continuation"])

    def test_sop002_threshold_mapping_has_no_hardcoded_station_order(self):
        self.assertFalse(hasattr(rule_extract, "SOP002_TABLE_STATIONS"))

    def test_sop002_unknown_station_heading_fails(self):
        pages = [{"doc_id": "SOP-002", "page": 1, "text": "ZZ99_UNKNOWN Thresholds"}]
        header = ["Sensor", "Unit", "CRIT_LO", "WARN_LO", "Nominal", "WARN_HI", "CRIT_HI", "CRITICAL Response"]
        tables = [{"doc_id": "SOP-002", "page": 1, "table_id": "SOP-002:p1:table1", "rows": [header]}]
        with self.assertRaisesRegex(ValueError, "not in built Station set"):
            sop002_threshold_table_contexts(tables, pages, {"ST01_FILLING"})

    def test_rule_extract_build_does_not_require_reference_files(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "sensors" / "input").mkdir(parents=True)
            (root / "documents").mkdir()
            (root / "sensors" / "input" / "ts_input.csv").write_text(
                "timestamp,zone,station_id,sensor_id,sensor_type,value,unit\n"
                "t,Production Area,ST01_FILLING,ST01_FILLING_TMP,TMP,1,°C\n",
                encoding="utf-8",
            )
            (root / "documents" / "chunks.jsonl").write_text("", encoding="utf-8")
            (root / "documents" / "pages.jsonl").write_text(
                json.dumps({"doc_id": "SOP-002", "page": 1, "text": "ST01_FILLING Thresholds"}) + "\n",
                encoding="utf-8",
            )
            table = {
                "doc_id": "SOP-002",
                "page": 1,
                "table_id": "SOP-002:p1:table1",
                "rows": [[
                    "Sensor", "Unit", "CRIT_LO", "WARN_LO", "Nominal",
                    "WARN_HI", "CRIT_HI", "CRITICAL Response",
                ], ["TMP", "°C", "1", "2", "3", "4", "5", "stop"]],
            }
            (root / "documents" / "tables.jsonl").write_text(json.dumps(table) + "\n", encoding="utf-8")
            result = rule_extract.build(root, root / "kg")
            self.assertEqual(result["rules"][0]["station"], "ST01_FILLING")

    def test_rdf_export_links_rule_sources(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            build = root / "kg"
            build.mkdir()
            (build / "nodes.jsonl").write_text(
                '{"id":"ST01_FILLING","labels":["Station"],"properties":{"identifier":"ST01_FILLING","stationType":"FILLING","zone":"Production Area"}}\n'
                '{"id":"ST01_FILLING_TMP","labels":["Sensor"],"properties":{"identifier":"ST01_FILLING_TMP","sensorType":"TMP","unit":"°C"}}\n',
                encoding="utf-8",
            )
            (build / "relationships.jsonl").write_text(
                '{"source":"ST01_FILLING","target":"ST01_FILLING_TMP","type":"hasSensor","properties":{}}\n',
                encoding="utf-8",
            )
            (build / "documents.jsonl").write_text(
                '{"id":"SOP-001","labels":["Document"],"properties":{"identifier":"SOP-001","sourceSha256":"0000000000000000000000000000000000000000000000000000000000000001","pageCount":"1"}}\n',
                encoding="utf-8",
            )
            (build / "provenance.jsonl").write_text(
                '{"id":"prov:SOP-001:p1:text1","labels":["Provenance"],"properties":{"sourceKind":"document","page":"1","charStart":"0","charEnd":"3","textSha256":"0000000000000000000000000000000000000000000000000000000000000002","fileSha256":"0000000000000000000000000000000000000000000000000000000000000001"}}\n',
                encoding="utf-8",
            )
            (build / "rules_extracted.jsonl").write_text(
                '{"ruleId":"RULE-X","class":"OperationalRule","sensor":"ST01_FILLING_TMP","station":"ST01_FILLING","condition":"TMP > 1","action":"stop","sourceDocument":"SOP-001","provenanceId":"prov:SOP-001:p1:text1"}\n',
                encoding="utf-8",
            )
            ttl = export_ttl(build)
            text = ttl.read_text(encoding="utf-8")
            self.assertIn("im:sourceDocument inst:SOP-001", text)
            self.assertIn("im:hasProvenance inst:prov_SOP-001_p1_text1", text)


if __name__ == "__main__":
    unittest.main()
