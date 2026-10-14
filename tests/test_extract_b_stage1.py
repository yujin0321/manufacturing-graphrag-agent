"""1단계 보강 시험: 재시도 횟수 의미(max_retries), 대기 1·2·4·8초, run_mode(scoring은 모델 1개만). mock만 쓴다."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_a_helpers import Sleeper, make_config, mocks, read_log, zero_rng  # noqa: E402

from imaks_kg.extract.client import extract_call  # noqa: E402
from imaks_kg.extract.config import (EXAMPLE_CONFIG_PATH, ConfigError, RetryPolicy, config_from_dict,  # noqa: E402
                                     load_config)
from imaks_kg.extract.providers.base import LLMRequest  # noqa: E402


def req():
    return LLMRequest(prompt="p", system="s", doc_id="D", prompt_sha256="a", example_sha256="b")


def data(mode=None, g=("g1",), o=()):
    d = {"run": {"provider_order": ["gemini"] + (["openai"] if o else [])},
         "providers": {"gemini": {"models": [{"id": i} for i in g]}}}
    if o:
        d["providers"]["openai"] = {"models": [{"id": i} for i in o]}
    if mode:
        d["run"]["run_mode"] = mode
    return d


class RetryMeaning(unittest.TestCase):
    def test_default_is_four_retries_five_attempts(self):
        p = RetryPolicy()
        self.assertEqual((p.max_retries, p.total_attempts), (4, 5))

    def test_five_calls_and_delays_1_2_4_8(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = config_from_dict({"run": {"provider_order": ["gemini"]}, "paths": {"log_dir": t, "cache_dir": t + "/c"},
                                    "providers": {"gemini": {"models": [{"id": "g1"}]}}})
            provs = mocks(g=("503",))
            sl = Sleeper()
            res = extract_call(cfg, req(), providers=provs, sleep=sl, rng=zero_rng)
            self.assertEqual(res.status, "failed")
            self.assertEqual(len(provs["gemini"].calls), 5)
            self.assertEqual(sl.delays, [1.0, 2.0, 4.0, 8.0])

    def test_delay_capped_at_60(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = config_from_dict({"run": {"provider_order": ["gemini"]}, "retry": {"max_retries": 9},
                                    "paths": {"log_dir": t, "cache_dir": t + "/c"},
                                    "providers": {"gemini": {"models": [{"id": "g1"}]}}})
            sl = Sleeper()
            extract_call(cfg, req(), providers=mocks(g=("429",)), sleep=sl, rng=zero_rng)
            self.assertEqual(sl.delays, [1, 2, 4, 8, 16, 32, 60, 60, 60])

    def test_old_name_is_rejected_with_guidance(self):
        d = data()
        d["retry"] = {"max_attempts": 4}
        with self.assertRaises(ConfigError) as cm:
            config_from_dict(d)
        self.assertIn("max_retries", str(cm.exception))

    def test_example_toml_uses_new_name(self):
        text = EXAMPLE_CONFIG_PATH.read_text(encoding="utf-8")
        self.assertIn("max_retries = 4", text)
        self.assertNotIn("max_attempts", text)
        cfg = load_config(EXAMPLE_CONFIG_PATH, require_models=False)
        self.assertEqual(cfg.run_mode, "production")


class RunMode(unittest.TestCase):
    def test_default_production_allows_fallback_chain(self):
        cfg = config_from_dict(data(g=("g1", "g2"), o=("o1",)))
        self.assertEqual(cfg.run_mode, "production")
        self.assertEqual(len(cfg.chain()), 3)

    def test_scoring_with_one_model_ok(self):
        self.assertEqual(config_from_dict(data("scoring")).run_mode, "scoring")

    def test_scoring_with_two_models_rejected_in_korean(self):
        for d in (data("scoring", g=("g1", "g2")), data("scoring", g=("g1",), o=("o1",))):
            with self.assertRaises(ConfigError) as cm:
                config_from_dict(d)
            self.assertIn("정확히 하나", str(cm.exception))

    def test_bad_mode_rejected(self):
        with self.assertRaises(ConfigError):
            config_from_dict(data("fast"))

    def test_extract_call_rechecks_mode(self):
        with tempfile.TemporaryDirectory() as t:
            ok = config_from_dict(data("scoring"))
            bad = config_from_dict(data("production", g=("g1", "g2")))
            object.__setattr__(bad, "run_mode", "scoring")  # 설정 객체를 나중에 바꿔도 호출 직전에 막는다
            with self.assertRaises(ConfigError):
                extract_call(bad, req(), providers=mocks(), sleep=Sleeper(), rng=zero_rng)
            self.assertIsNotNone(ok)

    def test_run_mode_recorded_in_call_log(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = config_from_dict({"run": {"provider_order": ["gemini"], "run_mode": "scoring"},
                                    "paths": {"log_dir": t, "cache_dir": t + "/c"},
                                    "providers": {"gemini": {"models": [{"id": "g1"}]}}})
            extract_call(cfg, req(), providers=mocks(), sleep=Sleeper(), rng=zero_rng)
            rows = read_log(cfg)
            self.assertTrue(rows)
            self.assertTrue(all(r.get("run_mode") == "scoring" for r in rows))
            self.assertTrue(all(r["request_meta"]["run_mode"] == "scoring" for r in rows if r.get("request_meta")))


if __name__ == "__main__":
    unittest.main()
