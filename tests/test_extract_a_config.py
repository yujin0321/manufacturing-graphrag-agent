"""설정 로더 테스트(mock만)."""
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from extract_a_helpers import ROOT, make_config  # noqa: E402

from imaks_kg.extract.config import (EXAMPLE_CONFIG_PATH, ConfigError, config_from_dict,  # noqa: E402
                                     load_config, model_fingerprint)


def base(models_g=None, models_o=None):
    models_g = models_g or ({"id": "g1"},)
    models_o = models_o or ({"id": "o1"},)
    models_g = [dict(m) for m in models_g]
    models_o = [dict(m) for m in models_o]
    return {"providers": {"gemini": {"models": list(models_g)}, "openai": {"models": list(models_o)}}}


class ConfigTests(unittest.TestCase):
    def test_example_loads_only_without_model_requirement(self):
        cfg = load_config(EXAMPLE_CONFIG_PATH, require_models=False)
        self.assertEqual(cfg.provider_order, ("gemini", "openai"))
        self.assertEqual(cfg.providers["gemini"].key_env, "GEMINI_API_KEY")
        self.assertEqual(cfg.providers["openai"].key_env, "OPENAI_API_KEY")
        self.assertTrue(all(m.id == "" for p in cfg.providers.values() for m in p.models))

    def test_empty_model_id_rejected_with_korean_message(self):
        with self.assertRaises(ConfigError) as cm:
            load_config(EXAMPLE_CONFIG_PATH)
        self.assertIn("providers.gemini.models[0].id", str(cm.exception))
        self.assertIn("비어", str(cm.exception))

    def test_no_models_rejected(self):
        with self.assertRaises(ConfigError) as cm:
            config_from_dict({"providers": {"gemini": {"models": []}, "openai": {"models": [{"id": "o1"}]}}})
        self.assertIn("providers.gemini.models", str(cm.exception))

    def test_sampling_params_rejected_everywhere(self):
        for name in ("temperature", "top_p", "top_k"):
            d = base()
            d["providers"]["gemini"]["models"][0][name] = 0
            with self.assertRaises(ConfigError, msg=name):
                config_from_dict(d)
            d = base()
            d[name] = 1
            with self.assertRaises(ConfigError, msg=name):
                config_from_dict(d)
        d = base()
        d["providers"]["openai"]["fields"] = {"thinking_path": "generationConfig.temperature"}
        with self.assertRaises(ConfigError):
            config_from_dict(d)

    def test_timeout_default_at_least_120_and_lower_rejected(self):
        cfg = config_from_dict(base())
        self.assertGreaterEqual(cfg.providers["gemini"].models[0].timeout_s, 120)
        d = base()
        d["providers"]["gemini"]["models"][0]["timeout_s"] = 30
        with self.assertRaises(ConfigError):
            config_from_dict(d)

    def test_defaults_retry_logdirs_thinking(self):
        cfg = config_from_dict(base())
        self.assertEqual((cfg.retry.max_retries, cfg.retry.base_delay_s, cfg.retry.max_delay_s), (4, 1.0, 60.0))
        self.assertEqual(cfg.providers["gemini"].models[0].thinking_level, "low")
        self.assertEqual(cfg.log_dir.name, "llm_logs")
        self.assertEqual(cfg.cache_dir.name, "llm_cache")
        self.assertTrue(cfg.try_next_provider_on_auth_error)

    def test_key_env_must_be_a_name_not_a_value(self):
        d = base()
        d["providers"]["gemini"]["key_env"] = "not-an-env-name"
        with self.assertRaises(ConfigError):
            config_from_dict(d)

    def test_chain_order_provider_then_model(self):
        with tempfile.TemporaryDirectory() as t:
            cfg = make_config(t)
            self.assertEqual([(p.name, m.id) for p, m in cfg.chain()], [("gemini", "g1"), ("gemini", "g2"), ("openai", "o1")])

    def test_fingerprint_differs_by_model_and_thinking(self):
        cfg = config_from_dict(base(({"id": "a"}, {"id": "b"})))
        p = cfg.providers["gemini"]
        self.assertNotEqual(model_fingerprint(p, p.models[0]), model_fingerprint(p, p.models[1]))

    def test_no_model_name_literals_in_new_code(self):
        pat = re.compile(r"gemini-\d|gpt-\d|gpt-[a-z]|\bo\d-")
        files = [p for p in (ROOT / "src" / "imaks_kg" / "extract").rglob("*.py") if p.name != "connectivity.py"]
        files += [ROOT / "config" / "extract.example.toml"]
        bad = [p.name for p in files if pat.search(p.read_text(encoding="utf-8"))]
        self.assertEqual(bad, [])


if __name__ == "__main__":
    unittest.main()
