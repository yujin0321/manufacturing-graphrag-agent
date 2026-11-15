"""센서 분석 결과 설명 Agent. 유료 API 없이 가짜 모델 응답으로 시험한다.

실행: PYTHONPATH=src python -m unittest tests.test_analysis_agent
"""
import contextlib
import csv
import io
import json
import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

from imaks_kg.analysis_agent import agent, analysis, ingest, planner, providers, service, tools
from imaks_kg.detection import rules as v1
from imaks_kg.detection.engine import config, run as engine_run
from imaks_kg.rag import vector as v

MODEL = v.read(v.CONFIG)["generation_model"]


def reference_rows(sensors=None, start=None, end=None):
    with (v.REPO_ROOT / v1.INPUT).open(encoding="utf-8-sig", newline="") as f:
        return [r for r in csv.DictReader(f)
                if (sensors is None or r["sensor_id"] in sensors)
                and (start is None or start <= r["timestamp"] < end)]


def to_csv(rows, fields):
    buf = io.StringIO(newline="")
    w = csv.DictWriter(buf, fieldnames=fields, lineterminator="\n", extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode("utf-8")


class FakeModel:
    """stage(api 캐시 폴더 이름)별 응답을 돌려주는 가짜 chat/completions."""

    def __init__(self, replies, model=MODEL):
        self.replies, self.model, self.calls = replies, model, []

    def __call__(self, resource, payload, cache):
        stage = Path(cache).name
        self.calls.append((stage, payload))
        reply = self.replies[stage]
        content = reply(payload) if callable(reply) else reply
        return ({"model": self.model, "usage": {"total_tokens": 10},
                 "choices": [{"finish_reason": "stop", "message": {"content": content}}]}, {"cache_hit": False})


class AnalysisAgentTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.svc = service.AnalysisService(Path(cls.tmp.name))
        cls.overview = cls.svc.create_reference_session()
        cls.sid = cls.overview["session_id"]
        cls.ws = cls.svc.workspace(cls.sid)
        cls.top = cls.overview["incidents"][0]["id"]

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    # ------------------------------------------------------------ ingest / analysis
    def test_upload_matches_engine_on_reference_input(self):
        cfg = config.load(analysis.DEFAULT_CONFIG)
        groups, _, _ = v1.read_inputs()
        expected, _ = engine_run.pipeline(groups, analysis.ir_bundle(), cfg)
        self.assertEqual(self.ws.store.incidents, expected["incidents"])
        self.assertEqual(self.ws.store.correlations, expected["correlations"])
        self.assertFalse(self.ws.summary["gold_loaded"])

    def test_overlay_provenance_points_to_upload(self):
        ttl = (self.svc.path(self.sid) / "overlay/overlay.ttl").read_text(encoding="utf-8")
        self.assertIn(self.ws.ingest["file_sha256"], ttl)
        report = v.read(self.svc.path(self.sid) / "overlay/overlay_report.json")
        self.assertEqual(report["shacl_blocking"], [])
        self.assertEqual(report["loader_errors"], [])

    def test_label_columns_are_dropped_and_do_not_change_results(self):
        rows = reference_rows({"ST02_SEALING_TMP", "ST02_SEALING_CUR"}, "2026-01-06T06", "2026-01-06T12")
        plain = to_csv(rows, v1.FIELDS)
        labeled = to_csv([dict(r, anomaly_label="SPIKE", severity="CRITICAL", alarm_flag="ALARM", quality="BAD",
                               nominal="0", warn_hi="1", day="9") for r in rows],
                         v1.FIELDS + ["anomaly_label", "severity", "alarm_flag", "quality", "nominal", "warn_hi", "day"])
        g1, r1 = ingest.parse(plain)
        g2, r2 = ingest.parse(labeled)
        self.assertEqual(g1, g2)
        self.assertEqual(set(r2["dropped_label_like_columns"]),
                         {"anomaly_label", "severity", "alarm_flag", "quality", "nominal", "warn_hi", "day"})
        self.assertFalse(r2["labels_read"])
        self.assertEqual(set(next(iter(g2.values()))[0]), set(v1.FIELDS))

    def test_minimal_columns_and_subset_of_sensors(self):
        rows = reference_rows({"ST02_SEALING_TMP"}, "2026-01-06T06", "2026-01-06T10")
        data = to_csv([{"timestamp": r["timestamp"].replace("T", " "), "sensor_id": r["sensor_id"],
                        "value": r["value"]} for r in rows], ["timestamp", "sensor_id", "value"])
        groups, report = ingest.parse(data, "small.csv")
        self.assertEqual(report["sensors"], ["ST02_SEALING_TMP"])
        self.assertEqual(len(report["sensors_missing"]), 21)
        with tempfile.TemporaryDirectory() as d:
            summary = analysis.run_engine(groups, Path(d) / "engine", {"file_name": "small.csv",
                                                                       "file_sha256": report["file_sha256"]})
        self.assertGreaterEqual(summary["incidents"], 1)  # 08:30 SPIKE
        self.assertTrue(summary["rules_skipped_missing_sensor"])

    def test_ingest_rejects_bad_input(self):
        rows = reference_rows({"ST02_SEALING_TMP"}, "2026-01-06T06", "2026-01-06T07")
        cases = {
            "필수 컬럼": to_csv(rows, ["timestamp", "sensor_id"]),
            "분석 가능한": to_csv([dict(r, sensor_id="UNKNOWN_X_TMP") for r in rows], v1.FIELDS),
            "중복": to_csv(rows + rows[:1], v1.FIELDS),
            "30초": to_csv(rows[::2], v1.FIELDS),
            "기준": to_csv([dict(r, unit="K") for r in rows], v1.FIELDS),
        }
        for expected, data in cases.items():
            with self.subTest(expected):
                with self.assertRaises(ingest.IngestError) as ctx:
                    ingest.parse(data)
                self.assertIn(expected, str(ctx.exception) + json.dumps(ctx.exception.details, ensure_ascii=False))

    def test_session_id_is_validated(self):
        for bad in ("../x", "sess_x", self.sid + "/.."):
            with self.assertRaises(service.SessionError):
                self.svc.path(bad)

    # ------------------------------------------------------------ planner
    def test_deterministic_routing(self):
        known = set(self.ws.store.by_id)
        meta = self.ws.meta
        cases = [
            ("이번 데이터 요약해줘", "summary", {}),
            ("가장 심각한 사건 설명해줘", "summary", {"pick": "top"}),
            ("실링 전류 이상 알려줘", "list", {"filters": {"sensor_id": "ST02_SEALING_CUR"}}),
            ("포장 공정에서 나온 사건", "list", {"filters": {"station_id": "ST04_PACKAGING"}}),
            ("창고 온도 드리프트 조치는?", "list", {"filters": {"sensor_id": "WRH01_WAREHOUSE_TMP",
                                                          "anomaly_type": "DRIFT"}}),
            ("공정 간 상관 후보 설명", "correlation", {}),
            ("SOP-002의 DRIFT 정의가 뭐야?", "document", {}),
            ("지금 서버실 온도 실시간으로 조회해줘", "unavailable", {}),
            (f"{self.top} 설명해줘", "incident", {"incident_id": self.top}),
            ("inc3-0000000000000000aaaa 설명", "clarify", {}),
        ]
        for question, intent, extra in cases:
            with self.subTest(question):
                plan = planner.deterministic(question, meta, known)
                self.assertEqual(plan["intent"], intent)
                for k, val in extra.items():
                    self.assertEqual(plan[k], val)
        self.assertEqual(planner.deterministic("이 사건 센서 값은?", meta, known, last_id=self.top)["incident_id"],
                         self.top)
        self.assertEqual(planner.deterministic("조치 방법은?", meta, known, focus_id=self.top)["incident_id"], self.top)
        self.assertIsNone(planner.deterministic("음 그러니까 어떻게 봐야 해?", meta, known))

    def test_model_plan_is_checked(self):
        known = set(self.ws.store.by_id)
        ok = planner.parse_model_plan(json.dumps({"intent": "incident", "calls": [
            {"tool": "get_incident_evidence", "arguments": {"incident_id": self.top}},
            {"tool": "get_incident_evidence", "arguments": {"incident_id": "inc3-0000000000000000ffff"}}]}), known)
        self.assertEqual(len(ok["calls"]), 1)
        for bad in ('{"intent":"hack","calls":[]}', '{"intent":"summary","calls":[{"tool":"rm","arguments":{}}]}',
                    "not json"):
            with self.assertRaises(ValueError):
                planner.parse_model_plan(bad, known)

    # ------------------------------------------------------------ tools
    def test_tools_and_selection_rule(self):
        with tempfile.TemporaryDirectory() as d:
            ts = tools.ToolSession(self.ws, Path(d))
            denied = ts.execute("get_incident_evidence", {"incident_id": self.top})
            self.assertEqual(denied["error_code"], "incident_selection_required")
            summary = ts.execute("summarize_results", {})
            self.assertEqual(summary["data"]["totals"]["incidents"], len(self.ws.store.incidents))
            evidence = ts.execute("get_incident_evidence", {"incident_id": self.top})
            self.assertEqual(evidence["status"], "ok")
            self.assertTrue(evidence["data"]["matched_rules"])
            window = ts.execute("get_sensor_window", {"incident_id": self.top})
            self.assertTrue(window["data"]["points"])
            self.assertIsNotNone(window["data"]["during_incident"])
            bad = ts.execute("list_incidents", {"station_id": "NOPE_STATION"})
            self.assertEqual(bad["error_code"], "unknown_filter_id")

    # ------------------------------------------------------------ agent
    def _evidence_answer(self, payload):
        """첫 사건 ID와 근거 청크 하나를 인용하는 정상 답변."""
        content = json.loads(payload["messages"][1]["content"])
        text = json.dumps(content["evidence"], ensure_ascii=False)
        iid = tools.INCIDENT_ID.findall(text)[0]
        chunk = next(c for e in content["evidence"] if e["data"]
                     for r in e["data"].get("matched_rules", []) for c in r["source_chunks"])
        return f"**요약** 사건 후보가 있습니다 [{iid}]. 문서 조치가 있습니다 [{chunk}]."

    def test_generation_and_verification(self):
        fake = FakeModel({"draft_1": self._evidence_answer, "verify_1": '{"approved": true, "issues": []}'})
        r = self.svc.ask(self.sid, "가장 심각한 사건을 설명해줘", call=fake)
        self.assertEqual(r["status"], "verified")
        self.assertEqual([c[0] for c in fake.calls], ["draft_1", "verify_1"])
        self.assertEqual(r["focus_incident_id"], self.top)
        self.assertTrue(any(s["cited"] for s in r["sources"]))
        self.assertTrue(r["sensor_windows"] and r["sensor_windows"][0]["points"])
        self.assertTrue(any(card["cited"] for card in r["incidents"]))
        # 후속 질문은 직전 사건을 이어받는다(모델 호출 없이 오프라인 확인)
        follow = self.svc.ask(self.sid, "이 사건 센서 값은 어땠어?", offline=True, call=None)
        self.assertEqual(follow["focus_incident_id"], self.top)

    def test_invented_citation_triggers_redraft(self):
        fake = FakeModel({"draft_1": "**요약** 원인은 [inc3-0000000000000000beef] 입니다 2026-02-01T00:00:00.",
                          "verify_1": '{"approved": true, "issues": []}',
                          "draft_2": lambda p: (self.assertIn("fix_these_issues", p["messages"][1]["content"]),
                                                self._evidence_answer(p))[1],
                          "verify_2": '{"approved": true, "issues": []}'})
        r = self.svc.ask(self.sid, f"{self.top} 설명해줘", call=fake)
        self.assertEqual(r["status"], "verified")
        self.assertEqual(r["verification"]["attempts"], 2)

    def test_unapproved_after_two_drafts_is_flagged(self):
        no = '{"approved": false, "issues": ["조치 실행 완료로 단정함"]}'
        fake = FakeModel({"draft_1": self._evidence_answer, "verify_1": no,
                          "draft_2": self._evidence_answer, "verify_2": no})
        r = self.svc.ask(self.sid, f"{self.top} 설명해줘", call=fake)
        self.assertEqual(r["status"], "unverified")
        self.assertFalse(r["verification"]["passed"])
        self.assertIn("조치 실행 완료로 단정함", r["verification"]["issues"])

    def test_gemini_provider_through_service(self):
        fake = FakeModel({"draft_1": self._evidence_answer, "verify_1": '{"approved": true, "issues": []}'},
                         model="gemini-test")
        r = self.svc.ask(self.sid, f"{self.top} 설명해줘", provider="gemini", model="gemini-test", call=fake)
        self.assertEqual((r["status"], r["provider"], r["model"]), ("verified", "gemini", "gemini-test"))
        self.assertEqual(fake.calls[0][1]["model"], "gemini-test")

    def test_incomplete_model_response_is_error_without_retry(self):
        fake = FakeModel({"draft_1": "x"}, model="other-model")
        r = self.svc.ask(self.sid, f"{self.top} 설명해줘", call=fake)
        self.assertEqual(r["status"], "error")
        self.assertEqual(len(fake.calls), 1)

    def test_model_planner_fallback(self):
        plan = json.dumps({"intent": "incident", "reason": "x",
                           "calls": [{"tool": "get_incident_evidence", "arguments": {"incident_id": self.top}}]})
        fake = FakeModel({"plan": plan, "draft_1": self._evidence_answer,
                          "verify_1": '{"approved": true, "issues": []}'})
        r = self.svc.ask(self.sid, "음 그러니까 어떻게 봐야 해?", call=fake)
        self.assertEqual(r["routing"]["mode"], "model")
        self.assertEqual(r["status"], "verified")

    def test_offline_and_unavailable_make_no_model_calls(self):
        def forbidden(*a):
            raise AssertionError("model called")
        for q in ("요약해줘", "지금 실시간 온도 조회해줘", "SOP-002의 DRIFT 정의가 뭐야?"):
            with self.subTest(q):
                r = self.svc.ask(self.sid, q, offline=True, call=forbidden)
                self.assertEqual(r["usage"]["model_calls"], 0)
                self.assertTrue(r["answer"])

    def test_overview_for_first_screen(self):
        o = self.svc.get_session(self.sid)
        self.assertEqual(o["status"], "ready")
        self.assertEqual(o["incidents"][0]["severity"], "CRITICAL")
        self.assertTrue(o["suggested_questions"])
        self.assertIn(self.sid, [s["session_id"] for s in self.svc.list_sessions()])


class GeminiProviderTest(unittest.TestCase):
    """Gemini 호출 함수. 실제 네트워크 대신 가짜 opener를 쓴다."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.cache = Path(self.tmp.name) / "api"
        self.env = os.environ.get("GEMINI_API_KEY")
        os.environ["GEMINI_API_KEY"] = "test-key"
        self.payload = {"model": "gemini-3.8-flash", "store": False, "max_completion_tokens": 100,
                        "messages": [{"role": "user", "content": "x"}], "response_format": {"type": "json_object"}}

    def tearDown(self):
        self.tmp.cleanup()
        if self.env is None:
            os.environ.pop("GEMINI_API_KEY", None)
        else:
            os.environ["GEMINI_API_KEY"] = self.env

    def test_request_shape_normalization_and_cache(self):
        seen = []

        def opener(req, timeout):
            seen.append(req)
            body = {"model": "models/gemini-3.8-flash",
                    "choices": [{"finish_reason": "stop", "message": {"content": "ok"}}]}
            return contextlib.nullcontext(io.BytesIO(json.dumps(body).encode()))

        raw, transport = providers.gemini_call("chat/completions", self.payload, self.cache, opener=opener)
        req = seen[0]
        sent = json.loads(req.data)
        self.assertEqual(req.full_url, providers.GEMINI_BASE + "chat/completions")
        self.assertEqual(req.get_header("Authorization"), "Bearer test-key")
        self.assertNotIn("store", sent)
        self.assertNotIn("max_completion_tokens", sent)
        self.assertEqual(sent["max_tokens"], 100)
        self.assertEqual(sent["response_format"], {"type": "json_object"})
        self.assertEqual(raw["model"], "gemini-3.8-flash")
        self.assertFalse(transport["cache_hit"])
        self.assertNotIn("test-key", "".join(p.read_text() for p in self.cache.iterdir()))
        raw2, transport2 = providers.gemini_call("chat/completions", self.payload, self.cache, opener=None)
        self.assertTrue(transport2["cache_hit"])
        self.assertEqual(len(seen), 1)

    def test_other_model_is_not_relabelled(self):
        out = providers._normalize({"model": "gemini-9-pro", "choices": []}, "gemini-3.8-flash")
        self.assertEqual(out["model"], "gemini-9-pro")

    def test_rate_limit_and_missing_key(self):
        def opener(req, timeout):
            raise HTTPError(req.full_url, 429, "Too Many Requests", {}, None)

        with self.assertRaises(RuntimeError) as ctx:
            providers.gemini_call("chat/completions", self.payload, self.cache, opener=opener)
        self.assertIn("429", str(ctx.exception))
        os.environ.pop("GEMINI_API_KEY")
        with self.assertRaises(RuntimeError):
            providers.gemini_call("chat/completions", dict(self.payload, model="gemini-x"), self.cache)

    def test_provider_defaults(self):
        call, model = providers.get("gemini")
        self.assertIs(call, providers.gemini_call)
        self.assertEqual(model, os.environ.get("GEMINI_MODEL", providers.GEMINI_DEFAULT_MODEL))
        self.assertEqual(providers.get("openai")[1], MODEL)
        with self.assertRaises(ValueError):
            providers.get("other")


if __name__ == "__main__":
    unittest.main()
