"""C: --execute 비용 승인 게이트와 실제 클라이언트 생성 금지(가짜 응답만, 네트워크 없음).

모든 --execute 경로 테스트는 anthropic.Anthropic을 '부르면 실패하는' 목으로 바꾸고, llm.AnthropicClient는
FakeClient를 돌려주는 목으로 바꾼다. 예시가 나중에 CONFIRMED가 되어도 실제 호출이 나갈 수 없다.

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_approval -v
"""
import copy
import io
import json
import os
import sys
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_fakes  # noqa: E402
import extract_support as S  # noqa: E402
from imaks_kg.extract import approval, llm, prompt, run  # noqa: E402
from imaks_kg.extract.common import ExtractError  # noqa: E402

DUMMY_KEY = "x-test-not-a-key"


def confirmed(ctx):
    c = dict(ctx)
    c["prompt"] = dict(ctx["prompt"], examples_status=prompt.STATUS_CONFIRMED)
    return c


class Gate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls._tmp = S.tmpdir()
        cls.fake_dir = extract_fakes.write(Path(cls._tmp.name) / "fake")
        cls.ctx = confirmed(S.ctx())

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def setUp(self):
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        self.root = Path(tmp.name)
        S.use_ledger(self, self.root / "ledger.jsonl")  # 테스트마다 임시 장부
        self.approvals = self.root / "approvals"
        self.out_root = self.root / "runs"

    def main(self, args, ctx=None):
        """run.main을 목으로 감싸 실행: 실제 anthropic.Anthropic 생성은 실패, AnthropicClient는 FakeClient."""
        ctx = ctx or self.ctx
        out = io.StringIO()
        real = mock.Mock(side_effect=AssertionError("테스트에서 실제 anthropic.Anthropic 생성 금지"))
        factory = mock.Mock(side_effect=lambda: llm.FakeClient(self.fake_dir))
        with mock.patch.object(run, "prepare", return_value=ctx), \
                mock.patch.dict(os.environ, {llm.API_KEY_ENV: DUMMY_KEY}), \
                mock.patch("anthropic.Anthropic", real), \
                mock.patch.object(run.llm, "AnthropicClient", factory), redirect_stdout(out):
            code = run.main(args + ["--approvals-dir", str(self.approvals), "--out-root", str(self.out_root)])
        self.assertEqual(real.call_count, 0)
        return code, out.getvalue(), factory

    def estimate(self, ctx=None):
        code, text, _ = self.main(["--dry-run"], ctx)
        self.assertEqual(code, 0, text)
        files = sorted(self.approvals.glob("*.json"))
        self.assertEqual(len(files), 1)
        return json.loads(files[0].read_text(encoding="utf-8"))

    def test_dry_run_record_contents(self):
        rec = self.estimate()
        self.assertEqual(rec["calls"], len(self.ctx["requests"]))
        self.assertEqual(rec["max_tokens_per_call"], 16000)
        self.assertEqual(rec["input_tokens"]["method"], "chars_estimate")
        self.assertEqual(rec["output_cap_tokens"], 16000 * rec["calls"])
        self.assertEqual(rec["price"], {"usd_per_mtok_input": 4.0, "usd_per_mtok_output": 20.0, "basis_date": "2026-10-06"})
        self.assertAlmostEqual(rec["cost_usd"]["output_max"], rec["output_cap_tokens"] * 20 / 1e6, places=3)
        fp = rec["fingerprint"]
        self.assertEqual(fp["input_fingerprint"], self.ctx["fingerprint"])
        self.assertEqual(fp["prompt_sha256"], self.ctx["prompt"]["prompt_sha256"])
        self.assertEqual(fp["examples_sha256"], self.ctx["prompt"]["examples_sha256"])
        self.assertEqual(len(fp["chunks"]), rec["calls"])
        self.assertTrue(rec["created_at"])
        self.assertEqual(rec["estimate_id"], rec["content_sha256"][:16])

    def assert_refused(self, args, needle, ctx=None):
        code, text, factory = self.main(args, ctx)
        self.assertEqual(code, 2, text)
        self.assertIn(needle, text)
        self.assertEqual(factory.call_count, 0, "거부인데 클라이언트를 만듦")
        self.assertFalse(self.out_root.exists() and any(self.out_root.iterdir()))
        return text

    def test_no_approval_refused(self):
        self.estimate()
        self.assert_refused(["--execute", "--run-id", "t-a"], "--approve")

    def test_wrong_id_refused(self):
        self.estimate()
        self.assert_refused(["--execute", "--approve", "0" * 16, "--run-id", "t-b"], "추정 기록이 없음")
        self.assert_refused(["--execute", "--approve", "../x", "--run-id", "t-b"], "형식")

    def test_input_changed_refused(self):
        rec = self.estimate()
        ctx2 = dict(self.ctx, fingerprint=copy.deepcopy(self.ctx["fingerprint"]))
        ctx2["fingerprint"]["seed_ttl"]["sha256"] = "f" * 64
        text = self.assert_refused(["--execute", "--approve", rec["estimate_id"], "--run-id", "t-c"], "seed_ttl", ctx2)
        self.assertIn("f" * 64, text)
        ctx3 = dict(self.ctx, prompt=dict(self.ctx["prompt"], prompt_sha256="e" * 64))
        self.assert_refused(["--execute", "--approve", rec["estimate_id"], "--run-id", "t-c"], "prompt_sha256", ctx3)

    def test_examples_changed_refused(self):
        rec = self.estimate()
        ctx2 = dict(self.ctx, prompt=dict(self.ctx["prompt"], examples_sha256="d" * 64))
        self.assert_refused(["--execute", "--approve", rec["estimate_id"], "--run-id", "t-d"], "examples_sha256", ctx2)

    def test_tampered_record_refused(self):
        rec = self.estimate()
        p = self.approvals / f"{rec['estimate_id']}.json"
        rec["calls"] = 999
        p.write_text(json.dumps(rec), encoding="utf-8")
        self.assert_refused(["--execute", "--approve", rec["estimate_id"], "--run-id", "t-e"], "기록을 고침")

    def test_approved_fake_passes_and_reuse_refused(self):
        rec = self.estimate()
        code, text, factory = self.main(["--execute", "--approve", rec["estimate_id"], "--run-id", "t-ok"])
        self.assertEqual(code, 0, text)
        self.assertEqual(factory.call_count, 1)
        meta = json.loads((self.out_root / "t-ok" / "meta.json").read_text(encoding="utf-8"))
        self.assertEqual(meta["mode"], "execute")
        self.assertEqual(meta["approval_id"], rec["estimate_id"])
        self.assertEqual(meta["max_calls"], rec["calls"])
        self.assertEqual(meta["counts"]["calls"], rec["calls"])
        used = json.loads((self.approvals / f"{rec['estimate_id']}.json").read_text(encoding="utf-8"))
        self.assertEqual(used["used_by_run_id"], "t-ok")
        # 재사용 거부(다른 run_id)
        code, text, factory = self.main(["--execute", "--approve", rec["estimate_id"], "--run-id", "t-again"])
        self.assertEqual(code, 2)
        self.assertIn("쓸 수 없는 승인 상태 used", text)
        self.assertEqual(factory.call_count, 0)
        self.assertFalse((self.out_root / "t-again").exists())

    def test_call_cap_enforced(self):
        client = llm.FakeClient(self.fake_dir)
        with self.assertRaises(ExtractError):
            run.run_calls(self.ctx, client, self.root / "cap", "t-cap", "execute", max_calls=len(self.ctx["requests"]) - 1)
        self.assertEqual(client.calls, [])
        self.assertFalse((self.root / "cap").exists())
        budget = approval.CallBudget(client, 1, 2)  # 승인 청크 1개, API 시도 상한 2회
        req = self.ctx["requests"][0]
        other = self.ctx["requests"][1]
        budget.create(req[1], req[0]["chunk_id"])
        self.assertTrue(budget.has_retry_room())
        budget.create(req[1], req[0]["chunk_id"])
        self.assertFalse(budget.has_retry_room())
        with self.assertRaises(ExtractError):  # 시도 상한
            budget.create(req[1], req[0]["chunk_id"])
        with self.assertRaises(ExtractError):  # 승인 청크 수 초과
            budget.create(other[1], other[0]["chunk_id"])
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(budget.history, {req[0]["chunk_id"]: 2})

    def test_draft_still_refused_first(self):
        rec = self.estimate()
        draft = dict(self.ctx, prompt=dict(self.ctx["prompt"], examples_status=prompt.STATUS_DRAFT))
        self.assert_refused(["--execute", "--approve", rec["estimate_id"], "--run-id", "t-f"], "examples.json", draft)


class NoRealClient(unittest.TestCase):
    """테스트 경로 전체에서 실제 anthropic.Anthropic이 만들어지지 않는지(호출 횟수 0)."""

    def test_pipeline_never_builds_real_client(self):
        why = S.needs_inputs()
        if why:
            self.skipTest(why)
        real = mock.Mock(side_effect=AssertionError("실제 클라이언트 생성 금지"))
        env = {k: v for k, v in os.environ.items() if k != llm.API_KEY_ENV}
        from imaks_kg.extract import llm_gemini
        gen = mock.Mock(side_effect=AssertionError("실제 genai.Client 생성 금지"))
        env.pop(llm_gemini.KEY_ENV, None)
        env.pop(llm_gemini.CONFLICT_ENV, None)
        with (S.tmpdir() as tmp, mock.patch("anthropic.Anthropic", real), mock.patch.dict(os.environ, env, clear=True),
              mock.patch.object(llm_gemini.genai, "Client", gen),
              mock.patch.object(llm_gemini, "DOTENV_FILE", Path(tmp) / "no.env")):
            run_dir = S.fake_run(tmp, "t-noreal")
            S.fill_round1(run_dir)
            from imaks_kg.extract import review, to_rdf
            review.make_round2(run_dir)
            review.apply_review(run_dir)
            to_rdf.run(run_dir, Path(tmp) / "kg")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(run.main(["--dry-run", "--approvals-dir", str(Path(tmp) / "ap")]), 0)
                self.assertEqual(run.main(["--execute", "--approvals-dir", str(Path(tmp) / "ap"),
                                           "--out-root", str(Path(tmp) / "runs2")]), 2)
            with self.assertRaises(ExtractError):
                llm.AnthropicClient()  # 키 없음 → SDK 클라이언트를 만들기 전에 거부
        self.assertEqual(real.call_count, 0)
        self.assertEqual(gen.call_count, 0)


if __name__ == "__main__":
    unittest.main()
