"""C: 검토·입력 무결성 반례(사용자 보완 요청). 가짜 응답과 임시 사본만 쓴다(실제 호출 없음, 저장소 파일 불변).

작업 공간(임시): inputs/{documents/, kg_build/seed.ttl, kg_build/rules_deterministic.ttl, preprocess_lock.json} + run/
- 검토 전 기준(pre): 1차 채움(ST01-02 hold, 나머지 accept) → 2차 생성(1행) → 2차 accept 채움. apply 전.
- 검토 후 기준(post): pre + apply.

실행: PYTHONPATH=src .venv/Scripts/python.exe -m unittest tests.test_extract_guard -v
"""
import json
import shutil
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import extract_fakes  # noqa: E402
import extract_support as S  # noqa: E402
from imaks_kg import settings  # noqa: E402
from imaks_kg.common.provenance import sha256_file, sha256_text  # noqa: E402
from imaks_kg.extract import llm, review, run, to_rdf  # noqa: E402
from imaks_kg.extract.common import ExtractError, read_jsonl  # noqa: E402
from imaks_kg.kg.preprocess_lock import BPaths  # noqa: E402

ST0102 = "SOP-001:p1:RULE-ST01-02:r1"
OUT_NAMES = (settings.RULES_LLM_TTL.name, settings.RULES_LLM_PREREVIEW_TTL.name, settings.SEED_RULES_LLM_TTL.name)


def paths_for(ws):
    ws = Path(ws)
    return BPaths(doc_dir=ws / "inputs" / "documents", out_dir=ws / "inputs" / "kg_build",
                  seed_ttl=ws / "inputs" / "kg_build" / "seed.ttl", lock_file=ws / "inputs" / "preprocess_lock.json")


def make_inputs(ws):
    inp = Path(ws) / "inputs"
    shutil.copytree(settings.DOCUMENTS_OUT, inp / "documents")
    (inp / "kg_build").mkdir(parents=True)
    shutil.copy2(settings.SEED_TTL, inp / "kg_build" / "seed.ttl")
    shutil.copy2(settings.RULES_TTL, inp / "kg_build" / "rules_deterministic.ttl")
    shutil.copy2(settings.PREPROCESS_LOCK, inp / "preprocess_lock.json")


def edit_text(path, old, new):
    p = Path(path)
    t = p.read_text(encoding="utf-8")
    assert old in t, (p, old)
    p.write_text(t.replace(old, new, 1), encoding="utf-8", newline="\n")


class Guard(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        why = S.needs_inputs()
        if why:
            raise unittest.SkipTest(why)
        cls._tmp = S.tmpdir()
        root = Path(cls._tmp.name)
        cls.pre = root / "pre"
        make_inputs(cls.pre)
        from imaks_kg.extract import ledger
        cls._ledger_before = ledger.LEDGER_OVERRIDE
        ledger.LEDGER_OVERRIDE = cls.pre / "ledger.jsonl"  # 작업 공간마다 장부(복사하면 장부도 함께 복사)
        paths = paths_for(cls.pre)
        ctx = run.prepare(paths, provider="anthropic")
        fake = extract_fakes.write(root / "fake")
        run.run_calls(ctx, llm.FakeClient(fake), cls.pre / "run", "t-guard", "fake")
        S.fill_round1(cls.pre / "run", overrides={ST0102: ("hold", "")})
        review.make_round2(cls.pre / "run", paths)
        S.fill_round2(cls.pre / "run", {ST0102: ("accept", "")})
        cls.post = root / "post"
        shutil.copytree(cls.pre, cls.post)
        ledger.LEDGER_OVERRIDE = cls.post / "ledger.jsonl"
        review.apply_review(cls.post / "run", paths_for(cls.post))
        cls.ref = root / "ref_out"
        to_rdf.run(cls.post / "run", cls.ref, paths_for(cls.post))
        cls.ref_hashes = {n: sha256_file(cls.ref / n) for n in OUT_NAMES}
        ledger.LEDGER_OVERRIDE = cls._ledger_before

    @classmethod
    def tearDownClass(cls):
        cls._tmp.cleanup()

    def ws(self, base):
        tmp = S.tmpdir()
        self.addCleanup(tmp.cleanup)
        d = Path(tmp.name) / "ws"
        shutil.copytree(base, d)
        S.use_ledger(self, d / "ledger.jsonl")
        return d, paths_for(d)

    def assert_rdf_stops(self, ws, paths, *needles, out=None):
        expect_empty = out is None
        out = out or (ws / "out")
        with self.assertRaises(ExtractError) as cm:
            to_rdf.run(ws / "run", out, paths)
        for n in needles:
            self.assertIn(n, str(cm.exception))
        if expect_empty:
            self.assertFalse(out.exists() and any(out.iterdir()), "멈췄는데 출력 파일이 생김")
        return str(cm.exception)

    def assert_apply_stops(self, ws, paths, *needles):
        with self.assertRaises(ExtractError) as cm:
            review.apply_review(ws / "run", paths)
        for n in needles:
            self.assertIn(n, str(cm.exception))
        self.assertFalse((ws / "run" / "final.jsonl").exists())

    # (h) 정상
    def test_h_normal_passes_same_hashes(self):
        ws, paths = self.ws(self.post)
        res = to_rdf.run(ws / "run", ws / "out", paths)
        self.assertEqual({n: sha256_file(ws / "out" / n) for n in OUT_NAMES}, self.ref_hashes)
        ok, text = S.shacl(res["merged_graph"])
        self.assertTrue(ok, text)
        ws2, paths2 = self.ws(self.pre)
        review.apply_review(ws2 / "run", paths2)
        to_rdf.run(ws2 / "run", ws2 / "out", paths2)
        self.assertEqual({n: sha256_file(ws2 / "out" / n) for n in OUT_NAMES}, self.ref_hashes)

    # (a) 검토 기록 없음
    def test_a_no_review_record(self):
        ws, paths = self.ws(self.post)
        (ws / "run" / "review_applied.json").unlink()
        self.assert_rdf_stops(ws, paths, "review_applied.json")
        ws, paths = self.ws(self.pre)  # apply 전
        self.assert_rdf_stops(ws, paths, "review_applied.json")

    # (b) final.jsonl 값 변경(해시 위조 포함)
    def test_b_final_edited(self):
        ws, paths = self.ws(self.post)
        f = ws / "run" / "final.jsonl"
        old = sha256_file(f)
        edit_text(f, '"responseText": "reduce speed by 10% and notify QC"', '"responseText": "stop the line"')
        msg = self.assert_rdf_stops(ws, paths, "final.jsonl", old, sha256_file(f))
        self.assertIn("기록", msg)
        # 해시까지 위조해도 값 대조로 멈춤
        rec_p = ws / "run" / "review_applied.json"
        rec = json.loads(rec_p.read_text(encoding="utf-8"))
        rec["final_jsonl_sha256"] = sha256_file(f)
        rec_p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        self.assert_rdf_stops(ws, paths, "responseText")

    def test_b_forged_counts(self):
        ws, paths = self.ws(self.post)
        rec_p = ws / "run" / "review_applied.json"
        rec = json.loads(rec_p.read_text(encoding="utf-8"))
        rec["counts"]["kept"] += 1
        rec_p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
        self.assert_rdf_stops(ws, paths, "개수·결정 집계")

    # (c) 1차 결정 변경
    def test_c_round1_changed(self):
        ws, paths = self.ws(self.post)
        S.fill_round1(ws / "run", overrides={ST0102: ("hold", ""), "SOP-002:p1:text1:r1": ("reject", "")})
        self.assert_rdf_stops(ws, paths, "review_round1.csv")
        ws, paths = self.ws(self.pre)  # apply 전에 바꾸면 apply가 멈춤
        S.fill_round1(ws / "run", overrides={ST0102: ("hold", ""), "SOP-002:p1:text1:r1": ("reject", "")})
        self.assert_apply_stops(ws, paths, "review_round1.csv", "1차 확정")

    # (d) 2차 변경
    def test_d_round2_changed(self):
        ws, paths = self.ws(self.post)
        S.fill_round2(ws / "run", {ST0102: ("reject", "")})
        self.assert_rdf_stops(ws, paths, "review_round2.csv")
        ws, paths = self.ws(self.post)
        (ws / "run" / "review_round2.csv").unlink()
        self.assert_rdf_stops(ws, paths, "2차 검토 유무")
        ws, paths = self.ws(self.pre)  # apply 전: 고정 열을 바꾸면 apply가 멈춤
        header, rows = S.read_rows(ws / "run" / "review_round2.csv")
        rows[0]["round1_comment"] = "바꿈"
        S.write_rows(ws / "run" / "review_round2.csv", header, rows)
        self.assert_apply_stops(ws, paths, "고정 열")

    def test_d_apply_requires_round2_step(self):
        ws, paths = self.ws(self.pre)
        man_p = ws / "run" / "review_manifest.json"
        man = json.loads(man_p.read_text(encoding="utf-8"))
        man.pop("round2")
        man_p.write_text(json.dumps(man), encoding="utf-8")
        self.assert_apply_stops(ws, paths, "round2")

    # (e) B 산출물 변경
    def test_e_b_output_changed(self):
        for base, check in ((self.pre, "apply"), (self.post, "rdf")):
            ws, paths = self.ws(base)
            edit_text(paths.out_dir / "rules_deterministic.ttl", 'im:responseText "Inspect sealing jaw"',
                      'im:responseText "Replace sealing jaw"')
            if check == "apply":
                self.assert_apply_stops(ws, paths, "rules_deterministic.ttl")
            else:
                self.assert_rdf_stops(ws, paths, "rules_deterministic.ttl")

    def test_e_merged_jsonl_changed_before_apply(self):
        ws, paths = self.ws(self.pre)
        edit_text(ws / "run" / "merged.jsonl", '"conditionText": "TMP exceeds 26°C"', '"conditionText": "TMP > 26°C"')
        self.assert_apply_stops(ws, paths, "merged.jsonl")

    # (f) seed 변경
    def test_f_seed_changed(self):
        for base in (self.pre, self.post):
            ws, paths = self.ws(base)
            edit_text(paths.seed_ttl, 'im:zone "Cafeteria"', 'im:zone "Canteen"')
            msg = (self.assert_apply_stops(ws, paths, "seed.ttl") if base == self.pre
                   else self.assert_rdf_stops(ws, paths, "seed.ttl"))
            del msg

    # (g) 청크·lock 변경
    def test_g_chunks_changed(self):
        ws, paths = self.ws(self.post)
        p = paths.doc_dir / "chunks.jsonl"
        lines = p.read_text(encoding="utf-8").splitlines()
        rec = json.loads(lines[4])
        rec["text_sha256"] = sha256_text(rec["text"] + "x")
        lines[4] = json.dumps(rec, ensure_ascii=False)
        p.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        self.assert_rdf_stops(ws, paths, "chunks.jsonl")
        ws, paths = self.ws(self.pre)
        p = paths.doc_dir / "chunks.jsonl"
        edit_text(p, "112 and 128", "112 and 129")
        self.assert_apply_stops(ws, paths, "해시 사슬")

    def test_g_lock_changed(self):
        for base in (self.pre, self.post):
            ws, paths = self.ws(base)
            lock = json.loads(paths.lock_file.read_text(encoding="utf-8"))
            lock["created_at"] = "2026-10-13T00:00:00+00:00"
            paths.lock_file.write_text(json.dumps(lock, indent=2), encoding="utf-8")
            if base == self.pre:
                self.assert_apply_stops(ws, paths, "preprocess_lock")
            else:
                self.assert_rdf_stops(ws, paths, "preprocess_lock")

    def test_g_round1_generation_checks_inputs(self):
        ws, paths = self.ws(self.pre)
        edit_text(paths.seed_ttl, 'im:zone "Cafeteria"', 'im:zone "Canteen"')
        with self.assertRaises(ExtractError) as cm:
            review.make_round2(ws / "run", paths)
        self.assertIn("seed.ttl", str(cm.exception))

    # (i) 멈출 때 기존 출력 불변
    def test_i_existing_outputs_untouched(self):
        ws, paths = self.ws(self.post)
        out = ws / "out"
        to_rdf.run(ws / "run", out, paths)
        before = {n: ((out / n).read_bytes(), (out / n).stat().st_mtime_ns) for n in OUT_NAMES}
        edit_text(ws / "run" / "final.jsonl", '"responseText": "reduce speed by 10% and notify QC"',
                  '"responseText": "stop the line"')
        self.assert_rdf_stops(ws, paths, "final.jsonl", out=out)
        edit_text(paths.seed_ttl, 'im:zone "Cafeteria"', 'im:zone "Canteen"')
        self.assert_rdf_stops(ws, paths, "seed.ttl", out=out)
        after = {n: ((out / n).read_bytes(), (out / n).stat().st_mtime_ns) for n in OUT_NAMES}
        self.assertEqual(before, after)

    # 검증자 반례: 일관된 위조(1차 결정 accept→reject, final에서 그 레코드 삭제, applied 해시·집계 재계산, manifest 그대로)
    def _consistent_forgery(self, ws):
        run_dir = ws / "run"
        target = "SOP-002:p1:text1:r1"
        header, rows = S.read_rows(run_dir / "review_round1.csv")
        for r in rows:
            if r["item_id"] == target:
                self.assertEqual(r["decision"], "accept")
                r["decision"] = "reject"
        S.write_rows(run_dir / "review_round1.csv", header, rows)
        f = run_dir / "final.jsonl"
        lines = [ln for ln in f.read_text(encoding="utf-8").splitlines() if f'"candidate_id": "{target}"' not in ln]
        f.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        final = read_jsonl(f)
        merged = read_jsonl(run_dir / "merged.jsonl")
        rec_p = run_dir / "review_applied.json"
        rec = json.loads(rec_p.read_text(encoding="utf-8"))
        rec["round1"]["sha256"] = sha256_file(run_dir / "review_round1.csv")
        rec["final_jsonl_sha256"] = sha256_file(f)
        rec.update(review.tally(final, merged))
        rec_p.write_text(json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")

    def test_j_consistent_forgery_stops(self):
        ws, paths = self.ws(self.post)
        out = ws / "out"
        to_rdf.run(ws / "run", out, paths)
        before = {n: ((out / n).read_bytes(), (out / n).stat().st_mtime_ns) for n in OUT_NAMES}
        self._consistent_forgery(ws)
        msg = self.assert_rdf_stops(ws, paths, "review_round1.csv", out=out)
        self.assertIn("manifest", msg)
        after = {n: ((out / n).read_bytes(), (out / n).stat().st_mtime_ns) for n in OUT_NAMES}
        self.assertEqual(before, after)

    def test_k_manifest_only_forgery_stops(self):
        cases = {
            "round1_template": lambda m: m["round1"].__setitem__("template_sha256", "0" * 64),
            "round1_merged": lambda m: m["round1"].__setitem__("merged_jsonl_sha256", "1" * 64),
            "round2_round1": lambda m: m["round2"].__setitem__("round1_sha256", "2" * 64),
            "round2_template": lambda m: m["round2"].__setitem__("template_sha256", "3" * 64),
            "run_id": lambda m: m.__setitem__("run_id", "other-run"),
            "fingerprint": lambda m: m.__setitem__("input_fingerprint_sha256", "4" * 64),
        }
        for name, change in cases.items():
            with self.subTest(name):
                ws, paths = self.ws(self.post)
                out = ws / "out"
                to_rdf.run(ws / "run", out, paths)
                before = {n: ((out / n).read_bytes(), (out / n).stat().st_mtime_ns) for n in OUT_NAMES}
                man_p = ws / "run" / "review_manifest.json"
                man = json.loads(man_p.read_text(encoding="utf-8"))
                change(man)
                man_p.write_text(json.dumps(man, ensure_ascii=False, indent=2), encoding="utf-8")
                self.assert_rdf_stops(ws, paths, out=out)
                after = {n: ((out / n).read_bytes(), (out / n).stat().st_mtime_ns) for n in OUT_NAMES}
                self.assertEqual(before, after)
                # apply 전 작업 공간에서도 같은 위조는 apply를 멈춘다
                ws2, paths2 = self.ws(self.pre)
                man_p2 = ws2 / "run" / "review_manifest.json"
                man2 = json.loads(man_p2.read_text(encoding="utf-8"))
                change(man2)
                man_p2.write_text(json.dumps(man2, ensure_ascii=False, indent=2), encoding="utf-8")
                self.assert_apply_stops(ws2, paths2)


    def test_meta_records_inputs(self):
        meta = json.loads((self.post / "run" / "meta.json").read_text(encoding="utf-8"))
        fp = meta["input_fingerprint"]
        paths = paths_for(self.post)
        self.assertEqual(fp["seed_ttl"]["sha256"], sha256_file(paths.seed_ttl))
        self.assertEqual(fp["rules_deterministic_ttl"]["sha256"], sha256_file(paths.out_dir / "rules_deterministic.ttl"))
        self.assertEqual(fp["preprocess_lock"]["sha256"], sha256_file(paths.lock_file))
        self.assertEqual(fp["chunks_jsonl"]["sha256"], sha256_file(paths.doc_dir / "chunks.jsonl"))
        self.assertTrue(meta["prompt_sha256"])
        self.assertTrue(all(c["text_sha256"] for c in meta["input_chunks"]))
        man = json.loads((self.post / "run" / "review_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(man), {"run_id", "input_fingerprint_sha256", "round1", "round2"})
        self.assertEqual(man["run_id"], meta["run_id"])


if __name__ == "__main__":
    unittest.main()
