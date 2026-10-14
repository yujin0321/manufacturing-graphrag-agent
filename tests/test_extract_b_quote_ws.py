"""검증기 수정 2건 시험(2026-10-14): (1) 인용 일치를 공백 정규화로, (2) 중복 인쇄 ID 접미사.
실제 전처리 청크(줄바꿈이 든 데이터시트 문단)와 가짜 응답만 쓴다. 정답 파일은 읽지 않고 API도 부르지 않는다."""
import csv
import hashlib
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path

from rdflib import Graph

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_b_helpers as h  # noqa: E402

from imaks_kg.extract import to_rdf  # noqa: E402
from imaks_kg.extract.docdata import DocumentStore  # noqa: E402
from imaks_kg.extract.providers.mock import ScriptedByDocMock  # noqa: E402
from imaks_kg.extract.request_builder import load_prompt_files  # noqa: E402
from imaks_kg.extract.run import revalidate, run_extraction  # noqa: E402
from imaks_kg.extract.validator import (apply_duplicate_flags, apply_identifier_suffixes, collapse_ws,  # noqa: E402
                                        resolve_evidence, rule_is_valid_for_kg, validate_response)
from imaks_kg.kg.convert_seed import IM  # noqa: E402

STORE, ALLOW = h.real_store(), h.real_allow()
_, SCHEMA = load_prompt_files()
sha = lambda s: hashlib.sha256(s.encode("utf-8")).hexdigest()  # noqa: E731
DS_CHUNK = "DS-ELEC-3300:p1:text2"
DS_TEXT = STORE.chunk_by_id[DS_CHUNK].text
Q_PLAIN = "The sensor is rated for continuous operation up to 14 A."
Q_NL_ORIG = DS_TEXT[DS_TEXT.index("Operation between"):DS_TEXT.index("(< 60 seconds).") + len("(< 60 seconds).")]
Q_NL_MODEL = Q_NL_ORIG.replace("\n", " ")
Q_LONG_ORIG = DS_TEXT[DS_TEXT.index("ElectroMeasure"):]
Q_LONG_MODEL = Q_LONG_ORIG.replace("\n", " ")


def val(doc, resp, **kw):
    text = resp if isinstance(resp, str) else json.dumps(resp, ensure_ascii=False)
    sent = h.sent_ids(STORE, doc)
    return validate_response(text, doc_id=doc, store=STORE, allowlist=ALLOW, sent_chunk_ids=sent,
                             merged_title_ids=[], schema=SCHEMA, model_info={"model": "m"}, **kw)


def ds_response(quotes, pids=None):
    pids = pids or [None] * len(quotes)
    rules = [h.rule("OperationalRule", f"c{i}", evidence=[h.ev(DS_CHUNK, q)], pid=p)
             for i, (q, p) in enumerate(zip(quotes, pids))]
    return {"rules": rules, "coverage": h.coverage(STORE, "DS-ELEC-3300", {DS_CHUNK: list(range(len(rules)))})}


def prov_of(rule, i=0):
    return rule["evidence"][i]["provenance"]


class QuoteWhitespace(unittest.TestCase):
    def test_test_data_really_has_newlines(self):
        self.assertIn("\n", Q_NL_ORIG)
        self.assertNotIn("\n", Q_NL_MODEL)
        self.assertNotIn(Q_NL_MODEL, DS_TEXT)   # 예전 방식(정확한 부분 문자열)이면 못 찾는 인용

    def test_newline_replaced_by_space_matches_with_exact_position_and_hash(self):
        r = val("DS-ELEC-3300", ds_response([Q_NL_MODEL])).rules[0]
        self.assertNotIn("evidence_not_found", r["flags"])
        self.assertIn("quote_whitespace_adjusted", r["flags"])
        self.assertTrue(rule_is_valid_for_kg(r))
        p, e = prov_of(r), r["evidence"][0]
        page = STORE.pages[("DS-ELEC-3300", p["page"])]
        self.assertTrue(p["resolved"])
        self.assertEqual(page[p["charStart"]:p["charEnd"]], Q_NL_ORIG)       # 위치가 원문 구간을 정확히 가리킴
        self.assertEqual(p["sourceQuote"], Q_NL_ORIG)
        self.assertIn("\n", p["sourceQuote"])
        self.assertEqual(p["textSha256"], sha(page[p["charStart"]:p["charEnd"]]))   # 해시 = 원문 구간 해시
        self.assertNotEqual(p["textSha256"], sha(Q_NL_MODEL))
        self.assertEqual(e["model_quote"], Q_NL_MODEL)                       # 모델이 준 인용은 감사용으로 보존
        self.assertEqual(e["source_quote"], Q_NL_ORIG)

    def test_exact_quote_is_not_flagged_and_model_quote_equals_source(self):
        r = val("DS-ELEC-3300", ds_response([Q_PLAIN])).rules[0]
        self.assertEqual(r["flags"], [])
        e = r["evidence"][0]
        self.assertEqual((e["model_quote"], e["source_quote"], prov_of(r)["sourceQuote"]), (Q_PLAIN,) * 3)

    def test_quote_spanning_several_line_breaks(self):
        r = val("DS-ELEC-3300", ds_response([Q_LONG_MODEL])).rules[0]
        p = prov_of(r)
        page = STORE.pages[("DS-ELEC-3300", p["page"])]
        self.assertEqual(page[p["charStart"]:p["charEnd"]], Q_LONG_ORIG)
        self.assertGreaterEqual(Q_LONG_ORIG.count("\n"), 1)
        self.assertIn("quote_whitespace_adjusted", r["flags"])

    def test_other_whitespace_kinds_and_runs(self):
        for variant in (Q_PLAIN.replace(" ", "\t"), Q_PLAIN.replace(" ", " "), Q_PLAIN.replace(" ", "  "),
                        "  " + Q_PLAIN + " \n"):
            r = val("DS-ELEC-3300", ds_response([variant])).rules[0]
            self.assertNotIn("evidence_not_found", r["flags"], repr(variant))
            self.assertIn("quote_whitespace_adjusted", r["flags"], repr(variant))
            p = prov_of(r)
            self.assertEqual(STORE.pages[("DS-ELEC-3300", 1)][p["charStart"]:p["charEnd"]], Q_PLAIN)
            self.assertEqual(p["sourceQuote"], Q_PLAIN)

    def test_one_word_or_digit_difference_still_not_found(self):
        cases = {"word": Q_NL_MODEL.replace("permissible", "permitted"),
                 "digit": Q_NL_MODEL.replace("60 seconds", "61 seconds"),
                 "number2": Q_NL_MODEL.replace("14 A and 20 A", "14 A and 21 A"),
                 "case": Q_NL_MODEL.replace("Operation", "operation"),
                 "punct": Q_NL_MODEL.replace("(< 60", "(<60"),   # 공백 유무는 정규화 대상이 아니다(연속 공백만 하나로)
                 "dot": Q_NL_MODEL.rstrip(".") + ","}
        for name, q in cases.items():
            r = val("DS-ELEC-3300", ds_response([q])).rules[0]
            self.assertIn("evidence_not_found", r["flags"], name)
            self.assertIsNone(prov_of(r), name)
            self.assertFalse(rule_is_valid_for_kg(r), name)
            self.assertNotIn("quote_whitespace_adjusted", r["flags"], name)

    def test_collapse_ws_mapping(self):
        n, idx = collapse_ws("  a \n\tb  c ")
        self.assertEqual(n, "a b c")
        self.assertEqual([("  a \n\tb  c ")[i] for i in idx], ["a", " ", "b", " ", "c"])

    def test_page_vs_chunk_difference_is_also_a_whitespace_adjustment(self):
        # RULE-ST02-04: 청크에는 공백, 쪽 텍스트에는 줄바꿈. sourceQuote는 쪽 텍스트 구간이어야 해시를 쪽 텍스트와 대조할 수 있다.
        cid = "SOP-001:p1:RULE-ST02-04"
        c = STORE.chunk_by_id[cid]
        q = h.rest_after_colon(STORE, cid)
        resp = {"rules": [h.rule("OperationalRule", "x", evidence=[h.ev(cid, q)])],
                "coverage": h.coverage(STORE, "SOP-001", {cid: [0]})}
        r = val("SOP-001", resp).rules[0]
        p = prov_of(r)
        page = STORE.pages[("SOP-001", 1)]
        self.assertEqual(p["sourceQuote"], page[p["charStart"]:p["charEnd"]])
        self.assertIn("\n", p["sourceQuote"])
        self.assertEqual(p["textSha256"], sha(p["sourceQuote"]))
        self.assertEqual(" ".join(p["sourceQuote"].split()), " ".join(q.split()))
        self.assertEqual(p["charStart"], c.char_start + c.text.index(q))

    def test_ambiguous_normalized_quote_stays_unresolved(self):
        r = val("DS-ELEC-3300", ds_response(["14 A"])).rules[0]    # 청크에 여러 번 나온다 -> 위치를 추측하지 않는다
        self.assertIn("position_unresolved", r["flags"])
        self.assertFalse(prov_of(r)["resolved"])
        self.assertNotIn("charStart", prov_of(r))


class TableCellWhitespace(unittest.TestCase):
    def setUp(self):
        self.t = tempfile.TemporaryDirectory()
        rows = [["Item", "Limit", "Action"],
                ["Bearing\ntemperature", "above 80 C\nfor 5 min", "Inspect\nand lubricate"],
                ["Vibration", "above 9 mm/s", "Stop"]]
        d, _ = h.write_fake_docs(self.t.name, {"T-1": [("table", {"rows": rows}, None)]})
        self.store = DocumentStore(d)
        self.chunk = self.store.chunks_by_doc["T-1"][0]

    def tearDown(self):
        self.t.cleanup()

    def res(self, quote, row=None, col=None):
        return resolve_evidence({"source_quote": quote, "table_row": row, "table_col": col}, self.chunk, self.store, "a" * 64)

    def test_cell_text_with_newline_matches_space_quote(self):
        fl, p = self.res("above 80 C for 5 min", 2, 2)
        self.assertEqual([f for f, _ in fl], ["quote_whitespace_adjusted"])
        self.assertTrue(p["resolved"])
        self.assertEqual(p["sourceQuote"], "above 80 C\nfor 5 min")        # 셀 원문 구간(줄바꿈 포함)
        self.assertEqual(p["textSha256"], sha("above 80 C\nfor 5 min"))
        self.assertEqual((p["rowIndex"], p["colIndex"]), (2, 2))

    def test_partial_cell_quote_without_coordinates(self):
        fl, p = self.res("lubricate")
        self.assertEqual(fl, [])
        self.assertEqual((p["rowIndex"], p["colIndex"], p["sourceQuote"]), (2, 3, "lubricate"))
        fl, p = self.res("Inspect and lubricate")
        self.assertEqual(p["sourceQuote"], "Inspect\nand lubricate")
        self.assertEqual((p["rowIndex"], p["colIndex"]), (2, 3))

    def test_row_level_quote_across_cells_and_newlines(self):
        fl, p = self.res("Bearing temperature | above 80 C for 5 min", 2)
        self.assertTrue(p["resolved"])
        self.assertEqual((p["rowIndex"], p["colIndex"]), (2, 1))
        self.assertEqual(p["sourceQuote"], "Bearing\ntemperature | above 80 C\nfor 5 min")
        self.assertEqual(p["textSha256"], sha(p["sourceQuote"]))
        self.assertIn("quote_whitespace_adjusted", [f for f, _ in fl])

    def test_trailing_separator_is_whitespace_adjustment_only(self):
        fl, p = self.res("Vibration | above 9 mm/s | ")
        self.assertEqual(p["sourceQuote"], "Vibration | above 9 mm/s |")   # 앞뒤 공백만 제거
        self.assertIn("quote_whitespace_adjusted", [f for f, _ in fl])

    def test_changed_word_or_number_in_cell_not_found(self):
        for q in ("above 81 C for 5 min", "Above 80 C for 5 min", "above 80 C for 5 minutes"):
            fl, p = self.res(q, 2, 2)
            self.assertIn("evidence_not_found", [f for f, _ in fl], q)
            self.assertIsNone(p)

    def test_quote_in_wrong_cell_with_normalization_is_unresolved_not_guessed(self):
        fl, p = self.res("above 80 C for 5 min", 3, 2)
        self.assertIn("position_unresolved", [f for f, _ in fl])
        self.assertFalse(p["resolved"])


class IdentifierSuffix(unittest.TestCase):
    @staticmethod
    def mk(doc, printed, n=0):
        return {"document_id": doc, "printed_rule_id": printed, "identifier": printed, "identifier_source": "printed",
                "flags": [], "flag_details": [], "rule_index": n}

    def test_second_and_third_get_suffix_first_unchanged(self):
        rs = [self.mk("D1", "Note 2"), self.mk("D1", "Note 2"), self.mk("D1", "Note 2"), self.mk("D1", "Note 3")]
        self.assertEqual(apply_identifier_suffixes(rs), 2)
        self.assertEqual([r["identifier"] for r in rs], ["Note 2", "Note 2-2", "Note 2-3", "Note 3"])
        self.assertEqual([r["printed_rule_id"] for r in rs], ["Note 2"] * 3 + ["Note 3"])   # 원문 그대로
        self.assertEqual([("split_from_printed_id" in r["flags"]) for r in rs], [False, True, True, False])
        self.assertEqual(apply_duplicate_flags(rs), 0)
        self.assertTrue(all(rule_is_valid_for_kg(r) for r in rs))            # 비차단
        self.assertEqual(apply_identifier_suffixes(rs), 0)                     # 다시 불러도 같다
        self.assertEqual([r["identifier"] for r in rs], ["Note 2", "Note 2-2", "Note 2-3", "Note 3"])
        self.assertEqual(rs[1]["flags"].count("split_from_printed_id"), 1)

    def test_collision_with_other_identifiers_raises_number(self):
        rs = [self.mk("D1", "R"), self.mk("D1", "R"), self.mk("D1", "R-2"), self.mk("D1", "R"),
              {**self.mk("D1", None), "identifier": "R-4", "identifier_source": "assigned"}]
        reserved = {"R-3"}                      # ③ seed 노드 identifier
        apply_identifier_suffixes(rs, reserved)
        ids = [r["identifier"] for r in rs]
        self.assertEqual(ids, ["R", "R-5", "R-2", "R-6", "R-4"])   # R-2(인쇄 ID), R-3(seed), R-4(자동 부여)를 피했다
        self.assertEqual(len(set(ids)), 5)
        self.assertEqual(apply_duplicate_flags(rs), 0)

    def test_other_document_is_separate(self):
        rs = [self.mk("D1", "Note 2"), self.mk("D2", "Note 2"), self.mk("D2", "Note 2")]
        apply_identifier_suffixes(rs)
        self.assertEqual([r["identifier"] for r in rs], ["Note 2", "Note 2", "Note 2-2"])   # D2의 첫 규칙은 접미사 없음
        self.assertEqual(apply_duplicate_flags(rs), 2)    # 문서 사이 같은 ID는 접미사 대상이 아니다(현재 동작 유지)
        self.assertNotIn("split_from_printed_id", rs[1]["flags"])

    def test_assigned_ids_untouched(self):
        a = {**self.mk("D1", None), "identifier": "D1:c:1", "identifier_source": "assigned"}
        b = {**self.mk("D1", None), "identifier": "D1:c:2", "identifier_source": "assigned"}
        apply_identifier_suffixes([a, b])
        self.assertEqual((a["identifier"], b["identifier"]), ("D1:c:1", "D1:c:2"))


def run_docs(tmp, responses, docs, run_id):
    ex, reg = h.make_registered_example(tmp)
    cfg = h.make_cfg(tmp, ex)
    prov = {"gemini": ScriptedByDocMock("gemini", responses)}
    rr = run_extraction(cfg, docs=docs, run_id=run_id, mock=True, providers=prov, registry_path=reg,
                        out_root=Path(tmp) / "out", validation_retries=0, sleep=lambda s: None)
    return cfg, rr


def jl(p):
    return [json.loads(x) for x in Path(p).read_text(encoding="utf-8").splitlines() if x.strip()]


class EndToEnd(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._t = tempfile.TemporaryDirectory()
        cls.tmp = Path(cls._t.name)
        # DS-ELEC: 같은 인쇄 ID "Note 2" 3개, 줄바꿈 인용 2개, 숫자 하나 다른 인용 1개(+)
        bad = Q_NL_MODEL.replace("60 seconds", "61 seconds")
        resp = ds_response([Q_PLAIN, Q_NL_MODEL, bad, Q_LONG_MODEL], ["Note 2"] * 4)
        cls.cfg, cls.rr = run_docs(cls.tmp, {"DS-ELEC-3300": json.dumps(resp)}, ["DS-ELEC-3300"], "mock-ws1")
        cls.d = cls.rr.out_dir
        cls.s = json.loads((cls.d / "run_summary.json").read_text(encoding="utf-8"))
        cls.all = jl(cls.d / "rules_all.jsonl")
        cls.valid = jl(cls.d / "rules_valid.jsonl")

    @classmethod
    def tearDownClass(cls):
        cls._t.cleanup()

    def test_identifiers_suffixed_and_no_duplicate_flag(self):
        self.assertEqual([r["identifier"] for r in self.all], ["Note 2", "Note 2-2", "Note 2-3", "Note 2-4"])
        self.assertEqual({r["printed_rule_id"] for r in self.all}, {"Note 2"})
        self.assertEqual(self.s["by_flag"]["duplicate_identifier"], 0)
        self.assertEqual(self.s["by_flag"]["split_from_printed_id"], 3)

    def test_non_blocking_flags_do_not_exclude_from_kg(self):
        ids = {r["identifier"] for r in self.valid}
        self.assertEqual(ids, {"Note 2", "Note 2-2", "Note 2-4"})     # 제외는 evidence_not_found 1개(Note 2-3)뿐
        self.assertEqual(self.s["counts"]["rules_all"], 4)
        self.assertEqual(self.s["counts"]["rules_excluded_from_kg"], 1)
        with (self.d / "flags.csv").open(encoding="utf-8", newline="") as f:
            rows = list(csv.DictReader(f))
        for r in rows:
            if r["flag"] in ("quote_whitespace_adjusted", "split_from_printed_id"):
                self.assertEqual(r["excluded_from_kg"], "no")

    def test_summary_counts_and_match_rate(self):
        q = self.s["quote_stats"]
        self.assertEqual((q["evidence_total"], q["evidence_not_found"], q["evidence_matched"]), (4, 1, 3))
        self.assertEqual(self.s["quote_match_rate"], 0.75)
        self.assertEqual(self.s["quote_whitespace_adjusted"], 2)
        self.assertEqual(self.s["by_flag"]["quote_whitespace_adjusted"], 2)
        self.assertEqual(self.s["by_flag"]["evidence_not_found"], 1)

    def test_rules_all_keeps_model_quote_and_predictions_unaffected(self):
        r = self.all[1]["evidence"][0]
        self.assertEqual(r["model_quote"], Q_NL_MODEL)
        self.assertEqual(r["source_quote"], Q_NL_ORIG)
        preds = jl(self.d / "predictions.jsonl")
        self.assertEqual(len(preds), 4)
        self.assertEqual([p["identifier"] for p in preds], [x["identifier"] for x in self.all])
        self.assertTrue(all("model_quote" not in p and "evidence" not in p for p in preds))

    def test_revalidate_is_deterministic_and_byte_identical(self):
        rr2 = revalidate("mock-ws1", self.cfg, out_run_id="mock-ws1", out_root=self.tmp / "out")
        for n in ("predictions.jsonl", "rules_all.jsonl", "rules_valid.jsonl"):
            self.assertEqual((rr2.out_dir / n).read_bytes(), (self.d / n).read_bytes(), n)

    def test_to_rdf_escapes_newlines_and_conforms(self):
        rep = to_rdf.convert("mock-ws1", out_root=self.tmp / "out")
        self.assertTrue(rep["shacl"]["conforms"], rep["shacl"]["messages"])
        self.assertEqual(rep["shacl"]["inference"], "none")
        self.assertEqual(rep["rules_in_ttl"], 3)
        ttl = (self.d / "rules_only.ttl").read_text(encoding="utf-8")
        g = Graph().parse(data=ttl, format="turtle")
        quotes = {str(o) for o in g.objects(None, IM.sourceQuote)}
        self.assertIn(Q_NL_ORIG, quotes)                  # 줄바꿈이 든 원문 구간이 그대로 돌아온다(모델 인용이 아님)
        self.assertNotIn(Q_NL_MODEL, quotes)
        for p in g.subjects(IM.sourceQuote, None):
            q, hsh = str(g.value(p, IM.sourceQuote)), str(g.value(p, IM.textSha256))
            self.assertTrue(re.fullmatch(r"[0-9a-f]{64}", hsh))
            self.assertEqual(hsh, sha(q))
        full = Graph().parse(str(self.d / "kg_with_rules.ttl"))
        self.assertEqual(len({str(o) for o in full.objects(None, IM.identifier)} & {"Note 2", "Note 2-2", "Note 2-4"}), 3)


class SuffixAcrossParts(unittest.TestCase):
    def test_collect_rules_suffixes_across_responses_and_avoids_seed_ids(self):
        from imaks_kg.extract.artifacts import DocOutcome, collect_rules
        va = val("DS-ELEC-3300", ds_response([Q_PLAIN], ["MAINT-01"]))
        vb = val("DS-ELEC-3300", ds_response([Q_NL_MODEL, Q_LONG_MODEL], ["MAINT-01", "MAINT-01"]))
        oa, ob = DocOutcome("DS-ELEC-3300", 1, 2, validation=va), DocOutcome("DS-ELEC-3300", 2, 2, validation=vb)
        rules = collect_rules([oa, ob], reserved=("MAINT-01-2",))
        self.assertEqual([r["identifier"] for r in rules], ["MAINT-01", "MAINT-01-3", "MAINT-01-4"])


if __name__ == "__main__":
    unittest.main()
