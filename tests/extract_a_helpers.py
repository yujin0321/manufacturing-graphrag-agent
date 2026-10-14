"""extract_a 테스트 공용 도구. gemini_ok_body는 레거시 generateContent 형식, gemini_interactions_body는 Interactions 형식. 실제 API는 호출하지 않는다. 가짜 키는 실행 중에 조합한다."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from imaks_kg.extract.config import config_from_dict  # noqa: E402
from imaks_kg.extract.providers.mock import MockProvider  # noqa: E402

FAKE_GEMINI = "AI" + "za" + "Zx9Yw8Vu7Ts6Rq5Po4Nm3Lk2Ji1Hg0FeDcBa"
FAKE_OPENAI = "s" + "k-" + "proj-" + "Qq1Ww2Ee3Rr4Tt5Yy6Uu7Ii8"


def make_config(tmp, gemini=("g1", "g2"), openai=("o1",), **run):
    """모델 id는 테스트용 가짜 이름. 로그·캐시는 tmp 아래."""
    def models(ids):
        return [{"id": i, "thinking_level": "low", "max_output_tokens": 1000, "timeout_s": 120} for i in ids]
    data = {"run": dict({"provider_order": ["gemini", "openai"]}, **run),
            "paths": {"log_dir": str(Path(tmp) / "llm_logs"), "cache_dir": str(Path(tmp) / "llm_cache")},
            "providers": {"gemini": {"models": models(gemini)}, "openai": {"models": models(openai)}}}
    return config_from_dict(data)


def mocks(g=("ok",), o=("ok",)):
    return {"gemini": MockProvider("gemini", g), "openai": MockProvider("openai", o)}


class Sleeper:
    def __init__(self):
        self.delays = []

    def __call__(self, s):
        self.delays.append(s)


def zero_rng():
    return 0.0


def read_log(cfg, run_id_logger=None):
    lines = []
    for p in sorted(Path(cfg.log_dir).glob("calls_*.jsonl")):
        lines += [json.loads(x) for x in p.read_text(encoding="utf-8").splitlines() if x.strip()]
    return lines


def gemini_interactions_body(text='{"rules": []}', status="completed", steps=None):
    """Interactions API 형식의 가짜 응답(2026-10-14 공식 문서 요약 기준)."""
    if steps is None:
        steps = [{"type": "model_output", "content": [{"type": "text", "text": text}]}]
    return json.dumps({"id": "i1", "model": "reported-g", "status": status, "steps": steps,
                       "usage": {"total_input_tokens": 7, "total_output_tokens": 3, "total_thought_tokens": 2,
                                 "total_cached_tokens": 1, "total_tokens": 12}})


def gemini_ok_body(text='{"rules": []}'):
    return json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}, "finishReason": "STOP"}],
                       "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 3,
                                         "thoughtsTokenCount": 2, "totalTokenCount": 12},
                       "modelVersion": "reported-g"})


def openai_ok_body(text='{"rules": []}'):
    return json.dumps({"model": "reported-o", "choices": [{"message": {"content": text}, "finish_reason": "stop"}],
                       "usage": {"prompt_tokens": 7, "completion_tokens": 3, "total_tokens": 10,
                                 "completion_tokens_details": {"reasoning_tokens": 2}}})
