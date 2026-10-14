"""C: 입력 선택, 해시 사슬, 프롬프트 3단 구조, 요청 형식, 실제 실행 거부 (가짜 응답만, 실제 호출 없음).

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_inputs_prompt -v
"""
import io
import json
import os
import shutil
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_support as S  # noqa: E402
from imaks_kg import settings  # noqa: E402
from imaks_kg.common.provenance import sha256_text
from imaks_kg.extract import inputs, llm, prompt, run
from imaks_kg.extract.common import ExtractError
from imaks_kg.kg.preprocess_lock import BPaths


class InputsPrompt(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls.ctx = S.ctx()

    # ---------------------------------------------------------------- 입력 선택
    def test_selection_rules(self):
        sel = self.ctx["selected"]
        docs = {c["doc_id"] for c in sel}
        self.assertEqual(docs, {"SOP-001", "SOP-002", "SOP-003", "SOP-004"})
        self.assertFalse([c for c in sel if c["doc_id"] == "SOP-002" and c["kind"] == "table"])
        self.assertFalse([c for c in sel if c["doc_id"].startswith("DS-")])
        allc = self.ctx["docs"]["chunks"]
        for d in ("SOP-001", "SOP-003", "SOP-004"):
            self.assertEqual(sorted(c["chunk_id"] for c in sel if c["doc_id"] == d),
                             sorted(c["chunk_id"] for c in allc if c["doc_id"] == d))
        excl = dict(self.ctx["excluded"])
        self.assertEqual(len(sel) + len(excl), len(allc))
        for c in allc:
            if c["doc_id"].startswith("DS-") or (c["doc_id"] == "SOP-002" and c["kind"] == "table"):
                self.assertIn(c["chunk_id"], excl)
                self.assertTrue(excl[c["chunk_id"]])

    def test_requests_one_per_selected_chunk(self):
        self.assertEqual([c["chunk_id"] for c, _ in self.ctx["requests"]], [c["chunk_id"] for c in self.ctx["selected"]])

    # ---------------------------------------------------------------- 해시 사슬
    def _copy_docs(self, tmp):
        d = Path(tmp) / "documents"
        shutil.copytree(settings.DOCUMENTS_OUT, d)
        return BPaths(doc_dir=d)

    def test_chain_mismatch_stops(self):
        with S.tmpdir() as tmp:
            paths = self._copy_docs(tmp)
            p = paths.doc_dir / "chunks.jsonl"
            lines = p.read_text(encoding="utf-8").splitlines()
            rec = json.loads(lines[3])
            rec["text"] = rec["text"].replace("112", "113")
            lines[3] = json.dumps(rec, ensure_ascii=False)
            p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
            with self.assertRaises(ExtractError) as cm:
                inputs.verify_chain(paths)
            self.assertIn("해시 사슬", str(cm.exception))
            with self.assertRaises(ExtractError):
                run.prepare(paths)

    def test_chunk_level_hash_checked(self):
        docs = json.loads(json.dumps({"chunks": self.ctx["docs"]["chunks"]}))
        docs.update({k: self.ctx["docs"][k] for k in ("pages", "tables", "manifest")})
        lock = json.loads(settings.PREPROCESS_LOCK.read_text(encoding="utf-8"))
        self.assertEqual(inputs.chunk_errors(docs, lock["input_pdfs"]), [])
        docs["chunks"][0]["text"] += " "
        self.assertTrue(inputs.chunk_errors(docs, lock["input_pdfs"]))

    # ---------------------------------------------------------------- 프롬프트
    def test_prompt_three_parts(self):
        tpl = (settings.EXTRACT_PROMPTS_DIR / "v1" / "system.md").read_text(encoding="utf-8")
        prompt.check_structure(tpl)
        heads = [ln for ln in tpl.splitlines() if ln.startswith("# ")]
        self.assertEqual(heads, ["# Role", "# Task", "# Example"])
        sysm = self.ctx["prompt"]["system"]
        self.assertLess(sysm.index("# Role"), sysm.index("# Task"))
        self.assertLess(sysm.index("# Task"), sysm.index("# Example"))
        self.assertIn("## Example 1", sysm)
        self.assertNotIn("{{", sysm)
        with self.assertRaises(ExtractError):
            prompt.check_structure(tpl.replace("# Example", "## Example section"))

    def test_prompt_has_seed_id_lists_and_hash(self):
        sysm = self.ctx["prompt"]["system"]
        for sid in self.ctx["seed"]["sensors"] + self.ctx["seed"]["stations"]:
            self.assertIn(f"- {sid}\n", sysm)
        self.assertEqual(len(self.ctx["seed"]["sensors"]), 22)
        self.assertEqual(len(self.ctx["seed"]["stations"]), 9)
        self.assertEqual(self.ctx["prompt"]["prompt_sha256"], sha256_text(sysm))
        self.assertEqual(self.ctx["prompt"]["version"], "v1")

    def test_examples_draft_from_sop_text(self):
        ex = json.loads((settings.EXTRACT_PROMPTS_DIR / "v1" / "examples.json").read_text(encoding="utf-8"))
        # 사람이 확정하면 CONFIRMED가 된다(그 전에는 초안)
        self.assertIn(ex[prompt.EXAMPLES_STATUS_KEY], (prompt.STATUS_DRAFT, prompt.STATUS_CONFIRMED))
        self.assertTrue(2 <= len(ex["examples"]) <= 3)
        chunks = self.ctx["chunks_by_id"]
        for e in ex["examples"]:
            self.assertTrue(e["source_chunk_id"].split(":")[0].startswith("SOP-"))
            for line in e["input_text"].split("\n"):
                self.assertIn(line, chunks[e["source_chunk_id"]]["text"])

    def test_schema_shape(self):
        sch = self.ctx["schema"]
        self.assertEqual(sch["required"], ["rules"])
        self.assertFalse(sch["additionalProperties"])
        item = sch["properties"]["rules"]["items"]
        self.assertFalse(item["additionalProperties"])
        self.assertEqual(set(item["required"]), set(item["properties"]))
        self.assertEqual(item["properties"]["class"]["enum"],
                         ["OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule"])
        self.assertEqual(item["properties"]["sensors"]["items"]["enum"], self.ctx["seed"]["sensors"])
        self.assertEqual(item["properties"]["targetStations"]["items"]["enum"], self.ctx["seed"]["stations"])

    def test_request_format(self):
        _, req = self.ctx["requests"][0]
        self.assertEqual(set(req), {"model", "max_tokens", "betas", "fallbacks", "system", "messages", "output_config"})
        self.assertEqual(req["model"], "claude-opus-5-5")
        self.assertEqual(req["max_tokens"], 16000)
        self.assertEqual(req["betas"], ["server-side-fallback-2026-07-01"])
        self.assertEqual(req["fallbacks"], "default")
        self.assertEqual(req["output_config"]["effort"], "high")
        self.assertEqual(req["output_config"]["format"]["type"], "json_schema")
        for k in ("temperature", "top_p", "top_k", "thinking"):
            self.assertNotIn(k, req)

    # ---------------------------------------------------------------- 실제 실행 거부
    def test_execute_refused_while_draft(self):
        # 예시 파일 상태와 무관하게 초안 상태를 주입하고, 실제 클라이언트 생성은 목으로 막는다(네트워크 없음)
        run_id = "t-refuse-draft"
        draft = dict(self.ctx, prompt=dict(self.ctx["prompt"], examples_status=prompt.STATUS_DRAFT))
        real = mock.Mock(side_effect=AssertionError("실제 클라이언트 생성 금지"))
        factory = mock.Mock(side_effect=AssertionError("거부 전에 클라이언트 생성 금지"))
        out = io.StringIO()
        with (S.tmpdir() as tmp, mock.patch.object(run, "prepare", return_value=draft),
              mock.patch.dict(os.environ, {llm.API_KEY_ENV: "x-test-not-a-key"}),
              mock.patch("anthropic.Anthropic", real), mock.patch.object(run.llm, "AnthropicClient", factory),
              redirect_stdout(out)):
            code = run.main(["--execute", "--run-id", run_id, "--out-root", str(Path(tmp) / "runs"),
                             "--approvals-dir", str(Path(tmp) / "ap")])
            self.assertFalse((Path(tmp) / "runs" / run_id).exists())
        self.assertEqual(code, 2)
        self.assertIn("examples.json", out.getvalue())
        self.assertEqual(real.call_count + factory.call_count, 0)

    def test_execute_refused_without_key(self):
        confirmed = dict(self.ctx["prompt"], examples_status=prompt.STATUS_CONFIRMED)
        env = {k: v for k, v in os.environ.items() if k != llm.API_KEY_ENV}
        real = mock.Mock(side_effect=AssertionError("실제 클라이언트 생성 금지"))
        with mock.patch.dict(os.environ, env, clear=True), mock.patch("anthropic.Anthropic", real):
            self.assertIn(llm.API_KEY_ENV, run.refuse_execute_reason(confirmed))
            with self.assertRaises(ExtractError):
                llm.AnthropicClient()
        self.assertEqual(real.call_count, 0)
        with mock.patch.dict(os.environ, {llm.API_KEY_ENV: "x-test-not-a-key"}):
            self.assertEqual(run.refuse_execute_reason(confirmed), "")

    def test_dry_run_prints_plan_without_calls(self):
        out = io.StringIO()
        env = {k: v for k, v in os.environ.items() if k != llm.API_KEY_ENV}
        real = mock.Mock(side_effect=AssertionError("실제 클라이언트 생성 금지"))
        with (S.tmpdir() as tmp, mock.patch.dict(os.environ, env, clear=True), redirect_stdout(out),
              mock.patch("anthropic.Anthropic", real)):
            self.assertEqual(run.main(["--dry-run", "--approvals-dir", str(Path(tmp) / "ap")]), 0)
            self.assertEqual(len(list((Path(tmp) / "ap").glob("*.json"))), 1)
        self.assertEqual(real.call_count, 0)
        text = out.getvalue()
        self.assertIn(f"입력 청크(호출 수): {len(self.ctx['requests'])}", text)
        self.assertIn("입력 토큰 추정", text)
        self.assertIn("DS-ELEC-3300:p1:table1:chunk", text)
        self.assertIn("estimate_id=", text)


if __name__ == "__main__":
    unittest.main()
