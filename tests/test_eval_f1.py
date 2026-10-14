"""F1_content 평가기 테스트. 가짜 정답 CSV와 가짜 임베더만 쓴다 (실제 정답 파일 사용 금지).
스모크 테스트 1개만 실제 모델을 쓰며, 모델이 없으면 건너뛴다."""
import csv
import json
import math
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from imaks_kg.eval import cli, gold as gold_mod  # noqa: E402
from imaks_kg.eval.lock import LOCK_NAME, LockMismatch  # noqa: E402
from imaks_kg.eval.match import assign  # noqa: E402
from imaks_kg.eval.predictions import PredictionError, load_predictions  # noqa: E402
from imaks_kg.eval.text import similarity_text  # noqa: E402

GOLD_HEADER = ["ruleId", "class", "station", "sensor", "sensorType", "condition", "action",
               "critHi", "warnHi", "critLo", "warnLo", "unit", "source"]
DOCS = ["DS-ELEC-3300", "SOP-001", "SOP-002", "SOP-003", "SOP-004"]


def unit(deg):
    r = math.radians(deg)
    return np.array([math.cos(r), math.sin(r)])


class FakeEmbedder:
    """텍스트 -> 미리 정한 단위 벡터. 코사인을 정확히 통제한다."""
    model_name = "fake-model"
    revision = "fake-rev"

    def __init__(self, vectors):
        self.vectors = {k: np.asarray(v, dtype=float) for k, v in vectors.items()}

    def encode(self, texts):
        return np.vstack([self.vectors[t] for t in texts]) if texts else np.zeros((0, 2))

    def loaded_revision(self):
        return None


class Base(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = Path(self._tmp.name)
        self.manifest = self.tmp / "doc_manifest.csv"
        self.manifest.write_text("doc_id,file\n" + "".join(f"{d},x\n" for d in DOCS), encoding="utf-8")
        self.definition = self.tmp / "definition.md"
        self.definition.write_text("fake definition", encoding="utf-8")

    def tearDown(self):
        self._tmp.cleanup()

    def write_gold(self, rows, name="gold.csv"):
        p = self.tmp / name
        with p.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f)
            w.writerow(GOLD_HEADER)
            for rid, cls, cond, doc in rows:
                rec = {"ruleId": rid, "class": cls, "condition": cond, "action": "", "source": doc}
                w.writerow([rec.get(h, "") for h in GOLD_HEADER])
        return p

    def write_preds(self, rows, name="pred.jsonl"):
        p = self.tmp / name
        with p.open("w", encoding="utf-8") as f:
            for doc, cls, cond, *extra in rows:
                rec = {"document_id": doc, "class": cls, "condition": cond, "action": ""}
                if extra:
                    rec.update(extra[0])
                f.write(json.dumps(rec) + "\n")
        return p

    def run_eval(self, preds, gold, vectors, out="out", threshold=0.6, **kw):
        return cli.run_evaluation(preds, self.tmp / out, gold, threshold, embedder=FakeEmbedder(vectors),
                                  manifest=self.manifest, definition=self.definition, **kw)


class TestMatching(unittest.TestCase):
    def test_maximizes_valid_count_before_similarity(self):
        # 탐욕 선택((0,0)=0.9 -> (1,1)=0.1)이면 유효 1개, 최적은 (0,1)+(1,0)으로 유효 2개
        sim = np.array([[0.9, 0.65], [0.7, 0.1]])
        res = assign(sim, 0.6)
        self.assertEqual(sorted((i, j) for i, j, _ in res), [(0, 1), (1, 0)])

    def test_valid_pair_similarity_sum_counterexample(self):
        # 무효 쌍(P3-G3 0.59)의 유사도가 합에 들어가면 {P1-G1, P2-G2}+P3-G3가 뽑힌다. 새 정의는 {P1-G2, P3-G1}.
        sim = np.array([[0.70, 0.75, 0.05], [0.05, 0.62, 0.10], [0.63, 0.05, 0.59]])
        res = assign(sim, 0.6)
        self.assertEqual(sorted((i, j) for i, j, _ in res), [(0, 1), (2, 0)])
        self.assertAlmostEqual(sum(s for _, _, s in res), 1.38)

    def test_valid_count_first_counterexample(self):
        sim = np.array([[0.99, 0.61], [0.61, 0.59]])
        self.assertEqual(sorted((i, j) for i, j, _ in assign(sim, 0.6)), [(0, 1), (1, 0)])

    def test_matches_brute_force(self):
        import itertools
        import random

        def brute(sim, t):
            n, m = sim.shape
            cells = [(i, j) for i in range(n) for j in range(m) if sim[i, j] >= t]
            best = (-1, -1.0, ())
            for r in range(len(cells) + 1):
                for comb in itertools.combinations(cells, r):
                    if len({i for i, _ in comb}) < r or len({j for _, j in comb}) < r:
                        continue
                    key = (r, sum(sim[i, j] for i, j in comb))
                    if key > best[:2]:
                        best = (key[0], key[1], comb)
            return sorted(best[2])

        rng = random.Random(12345)
        for _ in range(60):
            n, m = rng.randint(3, 4), rng.randint(3, 4)
            sim = np.array([[rng.uniform(0.3, 0.95) for _ in range(m)] for _ in range(n)])
            got = sorted((i, j) for i, j, _ in assign(sim, 0.6))
            self.assertEqual(got, brute(sim, 0.6))

    def test_deterministic_ties(self):
        sim = np.full((3, 3), 0.7)
        self.assertEqual(assign(sim, 0.6), assign(sim.copy(), 0.6))

    def test_rectangular(self):
        sim = np.array([[0.9, 0.2, 0.7]])
        self.assertEqual([(i, j) for i, j, _ in assign(sim, 0.6)], [(0, 0)])
        self.assertEqual(assign(np.zeros((0, 3)), 0.6), [])
        self.assertEqual(assign(np.zeros((2, 0)), 0.6), [])

    def test_threshold_boundary(self):
        self.assertEqual(len(assign(np.array([[0.6]]), 0.6)), 1)
        self.assertEqual(len(assign(np.array([[0.5999]]), 0.6)), 0)


class TestEvaluator(Base):
    def test_counterexample_tp_fp_fn(self):
        rows = [[0.70, 0.75, 0.05], [0.05, 0.62, 0.10], [0.63, 0.05, 0.59]]
        gold = self.write_gold([(f"G{j}", "ThresholdRule", f"g{j}", "SOP-001") for j in (1, 2, 3)])
        preds = self.write_preds([("SOP-001", "ThresholdRule", f"p{i}") for i in (1, 2, 3)])
        # 3차원 단위 벡터로 코사인 행렬을 그대로 만들기는 어려우므로 임베더 대신 행렬을 주입한다
        from imaks_kg.eval import metrics as mt
        orig = mt.cosine_matrix
        mt.cosine_matrix = lambda a, b: np.array(rows)
        try:
            v = {f"p{i}": np.ones(2) for i in (1, 2, 3)}
            v.update({f"g{j}": np.ones(2) for j in (1, 2, 3)})
            a = self.run_eval(preds, gold, v)["main_report"]
        finally:
            mt.cosine_matrix = orig
        self.assertEqual((a["tp"], a["fp"], a["fn"]), (2, 1, 1))

    def test_hand_calculated_case(self):
        # SOP-001: 예측 3, 정답 2, 유효 매칭 2 -> P 2/3, R 1, F1 0.8, 상한 2*2/5 = 0.8
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001"), ("G2", "ThresholdRule", "g2", "SOP-001")])
        preds = self.write_preds([("SOP-001", "ThresholdRule", "p1"), ("SOP-001", "ThresholdRule", "p2"),
                                  ("SOP-001", "ThresholdRule", "p3")])
        v = {"g1": unit(0), "g2": unit(90), "p1": unit(0), "p2": unit(90), "p3": unit(45 + 90 + 45)}
        m = self.run_eval(preds, gold, v)
        a = m["main_report"]
        self.assertEqual((a["tp"], a["fp"], a["fn"]), (2, 1, 0))
        self.assertAlmostEqual(a["precision"], 2 / 3)
        self.assertAlmostEqual(a["recall"], 1.0)
        self.assertAlmostEqual(a["f1"], 0.8)
        self.assertAlmostEqual(a["f1_upper_bound"], 0.8)
        self.assertAlmostEqual(a["pred_gold_ratio"], 1.5)

    def test_matches_only_within_same_document(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001"), ("G2", "ThresholdRule", "g2", "SOP-002")])
        preds = self.write_preds([("SOP-001", "ThresholdRule", "p1")])
        # p1은 SOP-002의 g2와 똑같지만 SOP-001의 g1과는 직교
        v = {"g1": unit(90), "g2": unit(0), "p1": unit(0)}
        m = self.run_eval(preds, gold, v)
        self.assertEqual(m["main_report"]["tp"], 0)

    def test_one_to_one(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001")])
        preds = self.write_preds([("SOP-001", "ThresholdRule", "p1"), ("SOP-001", "ThresholdRule", "p2")])
        v = {"g1": unit(0), "p1": unit(0), "p2": unit(0)}
        a = self.run_eval(preds, gold, v)["main_report"]
        self.assertEqual((a["tp"], a["fp"], a["fn"]), (1, 1, 0))

    def test_threshold_exactly_point_six_is_valid(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001")])
        preds = self.write_preds([("SOP-001", "ThresholdRule", "p1")])
        v = {"g1": np.array([0.6, 0.8]), "p1": np.array([1.0, 0.0])}
        self.assertEqual(self.run_eval(preds, gold, v)["main_report"]["tp"], 1)

    def test_class_not_a_matching_constraint_but_in_confusion(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001"), ("G2", "AccessRule", "g2", "SOP-001")])
        preds = self.write_preds([("SOP-001", "OperationalRule", "p1"), ("SOP-001", "AccessRule", "p2")])
        v = {"g1": unit(0), "g2": unit(90), "p1": unit(0), "p2": unit(90)}
        m = self.run_eval(preds, gold, v)
        a = m["main_report"]
        self.assertEqual(a["tp"], 2)
        self.assertAlmostEqual(a["f1"], 1.0)
        self.assertEqual(a["class_aware"]["tp"], 1)
        self.assertAlmostEqual(a["class_aware"]["f1"], 0.5)
        conf = m["class_confusion_matched_pairs"]["rows_gold_class_cols_pred_class"]
        self.assertEqual(conf["ThresholdRule"], {"OperationalRule": 1})
        self.assertEqual(conf["AccessRule"], {"AccessRule": 1})

    def test_main_vs_processed_denominators(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001"), ("G2", "ThresholdRule", "g2", "SOP-001"),
                                ("G3", "ThresholdRule", "g3", "SOP-002"), ("G4", "ThresholdRule", "g4", "SOP-002"),
                                ("G5", "ThresholdRule", "g5", "SOP-002")])
        preds = self.write_preds([("SOP-001", "ThresholdRule", "p1"), ("SOP-001", "ThresholdRule", "p2")])
        v = {"g1": unit(0), "g2": unit(90), "g3": unit(180), "g4": unit(270), "g5": unit(135),
             "p1": unit(0), "p2": unit(90)}
        m = self.run_eval(preds, gold, v)
        self.assertEqual((m["main_report"]["n_gold"], m["main_report"]["fn"]), (5, 3))
        self.assertAlmostEqual(m["main_report"]["recall"], 2 / 5)
        self.assertEqual((m["processed_scope_report"]["n_gold"], m["processed_scope_report"]["fn"]), (2, 0))
        self.assertAlmostEqual(m["processed_scope_report"]["recall"], 1.0)
        self.assertEqual(m["processed_scope_report"]["documents"], ["SOP-001"])

    def test_datasheet_predictions_are_out_of_scope(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001")])
        preds = self.write_preds([("SOP-001", "ThresholdRule", "p1"), ("DS-ELEC-3300", "ThresholdRule", "d1"),
                                  ("DS-ELEC-3300", "ThresholdRule", "d2")])
        v = {"g1": unit(0), "p1": unit(0), "d1": unit(0), "d2": unit(10)}
        m = self.run_eval(preds, gold, v)
        self.assertEqual(m["out_of_scope_predictions"]["datasheet_prediction_count"], 2)
        self.assertEqual(m["main_report"]["fp"], 0)
        self.assertEqual(m["main_report"]["n_pred"], 1)

    def test_threshold_sensitivity_reported_main_stays_point_six(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001")])
        preds = self.write_preds([("SOP-001", "ThresholdRule", "p1")])
        v = {"g1": np.array([0.65, math.sqrt(1 - 0.65 ** 2)]), "p1": np.array([1.0, 0.0])}
        m = self.run_eval(preds, gold, v)
        s = m["threshold_sensitivity"]
        self.assertEqual((s["0.5"]["tp"], s["0.6"]["tp"], s["0.7"]["tp"]), (1, 1, 0))
        self.assertEqual(m["main_report"]["tp"], 1)

    def test_sensor_agreement_only_when_present(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001")])
        preds = self.write_preds([("SOP-001", "ThresholdRule", "p1")])
        m = self.run_eval(preds, gold, {"g1": unit(0), "p1": unit(0)})
        self.assertTrue(str(m["agreement_on_matched_pairs"]["sensor_set"]).startswith("skipped"))
        preds2 = self.write_preds([("SOP-001", "ThresholdRule", "p1", {"sensors": [], "ruleExtra": "x"})], "p2.jsonl")
        m2 = self.run_eval(preds2, gold, {"g1": unit(0), "p1": unit(0)}, out="out2")
        self.assertEqual(m2["agreement_on_matched_pairs"]["sensor_set"]["agree"], 1)

    def test_unknown_prediction_fields_are_ignored(self):
        p = self.tmp / "extra.jsonl"
        p.write_text(json.dumps({"document_id": "SOP-001", "class": "AccessRule", "condition": "c", "action": "",
                                 "unknownField": 1, "evidence": [{"a": 1}], "ruleExtra": "x"}) + "\n", encoding="utf-8")
        got = load_predictions(p, set(DOCS))
        self.assertEqual(len(got), 1)

    def test_determinism(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001"), ("G2", "AccessRule", "g2", "SOP-001")])
        preds = self.write_preds([("SOP-001", "AccessRule", "p1"), ("SOP-001", "AccessRule", "p2")])
        v = {"g1": unit(0), "g2": unit(30), "p1": unit(10), "p2": unit(20)}
        a = self.run_eval(preds, gold, v, out="a")
        b = self.run_eval(preds, gold, v, out="b")
        self.assertEqual(json.dumps(a, sort_keys=True), json.dumps(b, sort_keys=True))
        self.assertEqual((self.tmp / "a" / "assignments.csv").read_bytes(), (self.tmp / "b" / "assignments.csv").read_bytes())

    def test_outputs_contain_no_gold_sentences(self):
        marker = "ZZQ-GOLD-SENTENCE-XYZ"
        gold = self.write_gold([("G1", "ThresholdRule", marker, "SOP-001")])
        preds = self.write_preds([("SOP-001", "ThresholdRule", "p1")])
        self.run_eval(preds, gold, {marker: unit(0), "p1": unit(0)})
        for f in (self.tmp / "out").iterdir():
            self.assertNotIn(marker, f.read_text(encoding="utf-8"), f.name)
        self.assertTrue({"metrics.json", "document_scores.csv", "assignments.csv", LOCK_NAME}
                        <= {f.name for f in (self.tmp / "out").iterdir()})


class TestGoldAndPredictions(Base):
    def test_unknown_document_in_gold_aborts(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-099")])
        with self.assertRaises(gold_mod.GoldError):
            gold_mod.load_gold(gold, gold_mod.known_doc_ids(self.manifest))

    def test_missing_gold_column_aborts(self):
        p = self.tmp / "bad.csv"
        p.write_text("ruleId,class,condition\nG1,AccessRule,x\n", encoding="utf-8")
        with self.assertRaises(gold_mod.GoldError):
            gold_mod.load_gold(p, set(DOCS))

    def test_prediction_format_errors_have_line_numbers(self):
        p = self.tmp / "bad.jsonl"
        good = json.dumps({"document_id": "SOP-001", "class": "AccessRule", "condition": "c", "action": ""})
        p.write_text(good + "\n" + json.dumps({"document_id": "SOP-001", "class": "Nope", "condition": "c",
                                               "action": ""}) + "\n", encoding="utf-8")
        with self.assertRaises(PredictionError) as cm:
            load_predictions(p, set(DOCS))
        self.assertIn("2번째 줄", str(cm.exception))

    def test_similarity_text(self):
        self.assertEqual(similarity_text("  If A ", " do B  "), "If A   do B".replace("   ", "   ").strip())
        self.assertEqual(similarity_text("Abc", "Def"), "Abc Def")
        self.assertEqual(similarity_text("Abc", ""), "Abc")  # 소문자화하지 않음


class TestLock(Base):
    def test_lock_written_before_gold_is_read(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001")])
        preds = self.write_preds([("SOP-001", "ThresholdRule", "p1")])
        seen = {}

        def loader(path, known):
            seen["lock_exists"] = (self.tmp / "out" / LOCK_NAME).exists()
            return gold_mod.load_gold(path, known)

        cli.run_evaluation(preds, self.tmp / "out", gold, 0.6, embedder=FakeEmbedder({"g1": unit(0), "p1": unit(0)}),
                           gold_loader=loader, manifest=self.manifest, definition=self.definition)
        self.assertTrue(seen["lock_exists"])
        lock = json.loads((self.tmp / "out" / LOCK_NAME).read_text(encoding="utf-8"))
        for k in ("predictions_sha256", "definition_sha256", "embedding_model", "libraries", "threshold",
                  "written_at_utc"):
            self.assertIn(k, lock)

    def test_lock_mismatch_aborts_before_gold_read(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001")])
        v = {"g1": unit(0), "p1": unit(0), "p2": unit(90)}
        self.run_eval(self.write_preds([("SOP-001", "ThresholdRule", "p1")]), gold, v)
        called = []

        def loader(path, known):
            called.append(1)
            return []

        with self.assertRaises(LockMismatch):
            cli.run_evaluation(self.write_preds([("SOP-001", "ThresholdRule", "p2")], "other.jsonl"),
                               self.tmp / "out", gold, 0.6, embedder=FakeEmbedder(v), gold_loader=loader,
                               manifest=self.manifest, definition=self.definition)
        self.assertEqual(called, [])

    def test_meta_is_recorded(self):
        gold = self.write_gold([("G1", "ThresholdRule", "g1", "SOP-001")])
        meta = self.tmp / "meta.json"
        meta.write_text(json.dumps({"prompt_sha256": "abc", "requested_models": ["m1"]}), encoding="utf-8")
        self.run_eval(self.write_preds([("SOP-001", "ThresholdRule", "p1")]), gold,
                      {"g1": unit(0), "p1": unit(0)}, meta_path=meta)
        lock = json.loads((self.tmp / "out" / LOCK_NAME).read_text(encoding="utf-8"))
        self.assertEqual(lock["meta"]["prompt_sha256"], "abc")


class TestRealModelSmoke(unittest.TestCase):
    def test_real_model_encodes_normalized(self):
        from imaks_kg.eval.embed import SbertEmbedder
        e = SbertEmbedder()
        try:
            m = e.encode(["the valve is open", "the valve is open now", "unrelated sentence about lunch"])
        except Exception as ex:  # 모델 없음/다운로드 불가 -> 건너뜀
            self.skipTest(f"실제 모델을 불러올 수 없어 건너뜀: {type(ex).__name__}")
        self.assertEqual(m.shape[0], 3)
        self.assertTrue(np.allclose(np.linalg.norm(m, axis=1), 1.0, atol=1e-4))
        self.assertGreater(float(m[0] @ m[1]), float(m[0] @ m[2]))


if __name__ == "__main__":
    unittest.main()
