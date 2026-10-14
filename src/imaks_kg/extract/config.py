"""4단계 호출 계층 설정 로더(TOML, 표준 라이브러리 tomllib). 키 값과 모델명 기본값은 코드에 없다."""
from __future__ import annotations

import hashlib
import json
import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from imaks_kg.settings import REPO_ROOT

DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "extract.toml"
EXAMPLE_CONFIG_PATH = REPO_ROOT / "config" / "extract.example.toml"
MIN_TIMEOUT_S = 120.0
SAMPLING_KEYS = ("temperature", "top_p", "top_k")  # 보내지 않는다. 설정에 있으면 거부.
RUN_MODES = ("scoring", "production")
_ENV_NAME = re.compile(r"^[A-Z][A-Z0-9_]*$")

# 공급자별 기본값: 모델명이 아니라 주소, 환경변수 이름, API 종류, 필드 위치만.
# 필드 위치 중 gemini max_tokens_path(generation_config.max_output_tokens)는 공식 문서에서 확인하지 못했다(추정). 설정으로 변경.
THINKING_LEVELS = {"gemini": ("low", "medium", "high"), "openai": ("low", "medium", "high", "xhigh", "max")}  # none/minimal 불가
API_CHOICES = {"gemini": ("interactions", "generate_content"), "openai": ("chat_completions",)}
GEMINI_FIELDS = {
    "interactions": {   # 요청 본문: model, input, response_format{type,mime_type,schema}, generation_config, store
        "thinking_path": "generation_config.thinking_level",
        "max_tokens_path": "generation_config.max_output_tokens",   # 미확인(추정)
        "store_path": "store",                                       # 값은 항상 false
        "system_path": "",   # 비면 system 문구를 input 앞에 이어 붙인다(system 전용 필드는 미확인)
    },
    "generate_content": {   # 레거시 경로(계속 지원)
        "thinking_path": "generationConfig.thinkingConfig.thinkingLevel",
        "max_tokens_path": "generationConfig.maxOutputTokens",
        "mime_path": "generationConfig.responseMimeType",
        "schema_path": "generationConfig.responseJsonSchema",
    },
}
PROVIDER_DEFAULTS = {
    "gemini": {
        "key_env": "GEMINI_API_KEY",
        "base_url": "https://generativelanguage.googleapis.com/v1beta",
        "api": "interactions",
    },
    "openai": {
        "key_env": "OPENAI_API_KEY",
        "base_url": "https://api.openai.com/v1",
        "api": "chat_completions",
        "fields": {
            "thinking_path": "reasoning_effort",
            "max_tokens_path": "max_completion_tokens",
            "schema_mode": "json_schema",   # json_schema | json_object | none
        },
    },
}


class ConfigError(ValueError):
    """설정 오류. 메시지는 한국어로 어떤 설정이 문제인지 알린다."""


@dataclass(frozen=True)
class ModelSpec:
    provider: str
    id: str
    thinking_level: str = "low"
    max_output_tokens: int = 16384  # 자리표시 기본값. 스모크에서 실측해 정한다.
    timeout_s: float = 120.0


@dataclass(frozen=True)
class ProviderSpec:
    name: str
    key_env: str
    base_url: str
    fields: dict = field(default_factory=dict)
    models: tuple = ()
    api: str = ""   # gemini: interactions | generate_content, openai: chat_completions


@dataclass(frozen=True)
class RetryPolicy:
    """max_retries = 같은 모델에 대한 재시도 횟수(첫 시도 제외). 기본 4회 -> 총 5회 시도, 대기 1, 2, 4, 8초."""
    max_retries: int = 4
    base_delay_s: float = 1.0
    max_delay_s: float = 60.0
    jitter_ratio: float = 0.25

    @property
    def total_attempts(self) -> int:
        return self.max_retries + 1


@dataclass(frozen=True)
class ExtractConfig:
    provider_order: tuple
    providers: dict
    retry: RetryPolicy
    log_dir: Path
    cache_dir: Path
    try_next_provider_on_auth_error: bool = True
    run_mode: str = "production"          # scoring | production
    example_file: str = ""                # 저장소 기준 상대 경로(2단계 요청 빌더가 읽음). 비어 있으면 실행 거부
    max_input_tokens_est: int = 200000    # 요청 입력 토큰 추정 상한(문자 수 / chars_per_token)
    chars_per_token: float = 3.0

    def assert_run_mode(self) -> None:
        """scoring 모드는 체인의 모델이 정확히 하나일 때만 실행한다(점수 기준선을 한 모델로 고정하기 위해)."""
        n = len(self.chain())
        if self.run_mode == "scoring" and n != 1:
            raise ConfigError(
                f"run_mode가 scoring이면 전체 체인의 모델이 정확히 하나여야 합니다(현재 {n}개). "
                "점수를 내는 실행에서 fallback으로 다른 모델 응답이 섞이면 기준선 정책이 깨집니다. "
                "공급자와 모델을 하나만 남기거나, 운영 실행이면 run_mode를 production으로 바꾸세요.")

    def chain(self) -> list:
        """[(ProviderSpec, ModelSpec)] 시도 순서: 공급자 순서 -> 공급자 안의 모델 순서."""
        return [(self.providers[p], m) for p in self.provider_order for m in self.providers[p].models]

    def key_env_names(self) -> list:
        return [self.providers[p].key_env for p in self.provider_order]


def _find_forbidden(obj, where="") -> list:
    found = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            here = f"{where}.{k}" if where else str(k)
            if str(k).lower() in SAMPLING_KEYS:
                found.append(here)
            found += _find_forbidden(v, here)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            found += _find_forbidden(v, f"{where}[{i}]")
    return found


def _resolve_dir(value, name) -> Path:
    if not isinstance(value, str) or not value:
        raise ConfigError(f"paths.{name}는 비어 있지 않은 문자열이어야 합니다.")
    p = Path(value)
    return p if p.is_absolute() else REPO_ROOT / p


def config_from_dict(data: dict, require_models: bool = True) -> ExtractConfig:
    bad = _find_forbidden(data)
    if bad:
        raise ConfigError("설정에 샘플링 매개변수가 있습니다(보내지 않는 항목이라 거부합니다): " + ", ".join(bad))
    run = data.get("run", {})
    order = tuple(run.get("provider_order", ("gemini", "openai")))
    if not order:
        raise ConfigError("run.provider_order가 비어 있습니다.")
    prov_data = data.get("providers", {})
    providers = {}
    for name in order:
        raw = prov_data.get(name)
        if raw is None:
            raise ConfigError(f"providers.{name} 설정이 없습니다(run.provider_order에 있는 공급자).")
        d = PROVIDER_DEFAULTS.get(name, {})
        key_env = raw.get("key_env", d.get("key_env", ""))
        if not _ENV_NAME.match(str(key_env)):
            raise ConfigError(f"providers.{name}.key_env는 환경변수 이름(예: GEMINI_API_KEY)이어야 합니다. 키 값을 넣지 마세요.")
        api = raw.get("api", d.get("api", ""))
        if name in API_CHOICES and api not in API_CHOICES[name]:
            raise ConfigError(f"providers.{name}.api는 {' 또는 '.join(API_CHOICES[name])} 중 하나여야 합니다(현재 {api!r}).")
        fields = dict(GEMINI_FIELDS[api]) if name == "gemini" else dict(d.get("fields", {}))
        fields.update(raw.get("fields", {}))
        for fk, fv in fields.items():
            if isinstance(fv, str) and fv.split(".")[-1].lower() in SAMPLING_KEYS:
                raise ConfigError(f"providers.{name}.fields.{fk}가 샘플링 매개변수를 가리킵니다.")
        models = []
        for i, m in enumerate(raw.get("models", [])):
            mid = m.get("id", "")
            if not isinstance(mid, str):
                raise ConfigError(f"providers.{name}.models[{i}].id는 문자열이어야 합니다.")
            if require_models and not mid.strip():
                raise ConfigError(f"providers.{name}.models[{i}].id가 비어 있습니다. 모델 id를 설정 파일에 채우세요(코드에 기본값 없음).")
            timeout = float(m.get("timeout_s", 120))
            if timeout < MIN_TIMEOUT_S:
                raise ConfigError(f"providers.{name}.models[{i}].timeout_s={timeout:g}는 {MIN_TIMEOUT_S:g}초 미만입니다(생각 켜진 모델은 느릴 수 있음).")
            mot = m.get("max_output_tokens", 16384)
            if not isinstance(mot, int) or isinstance(mot, bool) or mot <= 0:
                raise ConfigError(f"providers.{name}.models[{i}].max_output_tokens는 양의 정수여야 합니다.")
            level = m.get("thinking_level", "low")
            if not isinstance(level, str):
                raise ConfigError(f"providers.{name}.models[{i}].thinking_level은 문자열이어야 합니다.")
            if name in THINKING_LEVELS and level not in THINKING_LEVELS[name]:
                raise ConfigError(f"providers.{name}.models[{i}].thinking_level={level!r}은 지원하지 않습니다"
                                  f"({'/'.join(THINKING_LEVELS[name])} 중 하나, 생각을 끄는 값은 불가).")
            models.append(ModelSpec(name, mid.strip(), level, mot, timeout))
        if require_models and not models:
            raise ConfigError(f"providers.{name}.models가 비어 있습니다. 최소 1개 모델을 설정하세요.")
        providers[name] = ProviderSpec(name, key_env, raw.get("base_url", d.get("base_url", "")), fields, tuple(models), api)
    r = data.get("retry", {})
    if "max_attempts" in r:
        raise ConfigError("retry.max_attempts는 더 이상 쓰지 않습니다. 의미가 바뀌어 이름도 retry.max_retries로 바꿨습니다"
                          "(재시도 횟수, 첫 시도 제외; 기본 4 = 총 5회 시도).")
    policy = RetryPolicy(int(r.get("max_retries", 4)), float(r.get("base_delay_s", 1.0)),
                         float(r.get("max_delay_s", 60.0)), float(r.get("jitter_ratio", 0.25)))
    if policy.max_retries < 0 or policy.base_delay_s < 0 or policy.max_delay_s < policy.base_delay_s \
            or not 0 <= policy.jitter_ratio <= 1:
        raise ConfigError("retry 설정 값이 올바르지 않습니다(max_retries>=0, 0<=base<=max, 0<=jitter_ratio<=1).")
    run_mode = run.get("run_mode", "production")
    if run_mode not in RUN_MODES:
        raise ConfigError(f"run.run_mode는 {' 또는 '.join(RUN_MODES)} 중 하나여야 합니다(현재 {run_mode!r}).")
    paths = data.get("paths", {})
    ex = data.get("extract", {})
    example_file = ex.get("example_file", "")
    if not isinstance(example_file, str):
        raise ConfigError("extract.example_file은 문자열(저장소 기준 상대 경로)이어야 합니다.")
    max_in = ex.get("max_input_tokens_est", 200000)
    cpt = ex.get("chars_per_token", 3.0)
    if not isinstance(max_in, int) or isinstance(max_in, bool) or max_in <= 0 \
            or not isinstance(cpt, (int, float)) or isinstance(cpt, bool) or cpt <= 0:
        raise ConfigError("extract.max_input_tokens_est는 양의 정수, extract.chars_per_token은 양수여야 합니다.")
    cfg = ExtractConfig(order, providers, policy,
                        _resolve_dir(paths.get("log_dir", "llm_logs"), "log_dir"),
                        _resolve_dir(paths.get("cache_dir", "llm_cache"), "cache_dir"),
                        bool(run.get("try_next_provider_on_auth_error", True)),
                        run_mode, example_file, max_in, float(cpt))
    if require_models:
        cfg.assert_run_mode()
    return cfg


def load_config(path=None, require_models: bool = True) -> ExtractConfig:
    p = Path(path) if path else DEFAULT_CONFIG_PATH
    if not p.is_file():
        raise ConfigError(f"설정 파일이 없습니다: {p.name}. config/extract.example.toml을 복사해 모델 id를 채우세요.")
    try:
        with p.open("rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"설정 파일 TOML 문법 오류: {e}") from e
    return config_from_dict(data, require_models)


def model_fingerprint(pspec: ProviderSpec, mspec: ModelSpec) -> str:
    """캐시 키에 들어가는 설정 해시: 응답 내용에 영향을 주는 값만(타임아웃, 키 이름 제외)."""
    payload = {"provider": pspec.name, "api": pspec.api, "model": mspec.id, "thinking_level": mspec.thinking_level,
               "max_output_tokens": mspec.max_output_tokens, "fields": pspec.fields, "base_url": pspec.base_url}
    return hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()
