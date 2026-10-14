"""공급자에 보낼 JSON Schema 변환과 정적 린트.

원본 prompts/response_schema_v1.json은 사람이 읽는 원본이라 고치지 않는다. 보낼 때만 복사본을 변환한다.
로컬 검증기(validator.py)는 항상 원본 스키마로 응답을 다시 검사하므로, 공급자용 복사본에서 뺀 제약
(minimum, minItems 등)도 로컬에서는 그대로 적용된다.

규칙은 2026-10-14 공식 문서 요약에 따른다. 키워드별 수용 여부의 실제 확인은 스모크에서 한다(미확인).
- OpenAI strict: 모든 속성 required, additionalProperties false, 지원하지 않는 키워드 제거,
  type에 null이 있으면 enum에도 null.
- Gemini: JSON Schema 부분집합. 허용 목록 밖의 키워드는 경고(수용 여부 미확인).

변환 종류:
  자동 수정(의미 유지 또는 공급자 쪽 제약만 완화): 지원하지 않는 키워드 제거, additionalProperties false 추가,
    type에 null이 있는데 enum에 null이 없을 때 null 추가.
  자동 수정 안 함(의미가 바뀜): 선택 속성(required에 없는 속성)을 필수로 바꾸기. 린트가 오류로 보고하고
    to_provider_schema는 SchemaIncompatible을 낸다.
"""
from __future__ import annotations

import copy
from typing import NamedTuple

# OpenAI strict 모드에서 지원하지 않는 것으로 알려진 키워드(공식 문서 요약 기준, 실제 수용 여부 미확인).
OPENAI_UNSUPPORTED = (
    "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum", "multipleOf",
    "minItems", "maxItems", "uniqueItems", "minLength", "maxLength", "pattern", "format",
    "minProperties", "maxProperties", "default", "examples", "patternProperties",
    "unevaluatedProperties", "propertyNames", "contains", "not", "if", "then", "else", "allOf",
)
OPENAI_MAX_DEPTH = 10

# Gemini 부분집합에서 쓸 수 있다고 보는 키워드(보수적 허용 목록, 미확인).
GEMINI_ALLOWED = (
    "type", "properties", "required", "items", "enum", "description", "title", "format",
    "minimum", "maximum", "minItems", "maxItems", "additionalProperties", "anyOf", "oneOf",
    "prefixItems", "propertyOrdering", "nullable", "$ref", "$defs",
)

PROVIDERS = ("openai", "gemini")


class SchemaIssue(NamedTuple):
    path: str
    code: str           # unsupported_keyword | missing_additional_properties | optional_property | null_not_in_enum
    #                     | unknown_keyword | too_deep | root_not_object
    message: str
    auto_fix: bool      # to_provider_schema가 안전하게 고치는지
    changes_meaning: bool = False


class SchemaIncompatible(ValueError):
    """자동 수정으로 해결되지 않는 호환성 문제."""

    def __init__(self, issues):
        self.issues = list(issues)
        super().__init__("스키마를 공급자 규칙에 맞게 바꿀 수 없습니다: "
                         + "; ".join(f"{i.path}: {i.message}" for i in self.issues))


def _is_object(node) -> bool:
    t = node.get("type")
    return t == "object" or (isinstance(t, list) and "object" in t) or "properties" in node


def _has_null(node) -> bool:
    t = node.get("type")
    return t == "null" or (isinstance(t, list) and "null" in t)


def _children(node, path):
    """(하위 경로, 하위 스키마) 목록. 스키마 키워드 안의 스키마만 훑는다."""
    for k, v in (node.get("properties") or {}).items():
        if isinstance(v, dict):
            yield f"{path}.properties.{k}", v
    if isinstance(node.get("items"), dict):
        yield f"{path}.items", node["items"]
    for key in ("anyOf", "oneOf", "allOf", "prefixItems"):
        for i, v in enumerate(node.get(key) or []):
            if isinstance(v, dict):
                yield f"{path}.{key}[{i}]", v
    for key in ("$defs", "definitions"):
        for k, v in (node.get(key) or {}).items():
            if isinstance(v, dict):
                yield f"{path}.{key}.{k}", v


def schema_lint(provider: str, schema: dict) -> list:
    """정적 린트. 공급자 규칙에 어긋나는 곳의 SchemaIssue 목록(없으면 빈 목록)."""
    if provider not in PROVIDERS:
        raise ValueError(f"알 수 없는 공급자: {provider}")
    issues = []

    def walk(node, path, depth):
        if provider == "openai":
            if depth > OPENAI_MAX_DEPTH:
                issues.append(SchemaIssue(path, "too_deep", f"중첩 깊이가 {OPENAI_MAX_DEPTH}를 넘습니다.", False))
            for kw in OPENAI_UNSUPPORTED:
                if kw in node:
                    issues.append(SchemaIssue(path, "unsupported_keyword",
                                              f"strict 모드에서 지원하지 않는 키워드 {kw}", True))
            if _is_object(node):
                props = node.get("properties") or {}
                if node.get("additionalProperties") is not False:
                    issues.append(SchemaIssue(path, "missing_additional_properties",
                                              "additionalProperties: false가 없습니다.", True))
                req = set(node.get("required") or [])
                for name in props:
                    if name not in req:
                        issues.append(SchemaIssue(f"{path}.properties.{name}", "optional_property",
                                                  "required에 없는 선택 속성(strict는 모든 속성을 required로 요구)",
                                                  False, True))
            if _has_null(node) and isinstance(node.get("enum"), list) and None not in node["enum"]:
                issues.append(SchemaIssue(path, "null_not_in_enum", "type에 null이 있는데 enum에 null이 없습니다.", True))
        else:
            for kw in node:
                if kw not in GEMINI_ALLOWED:
                    issues.append(SchemaIssue(path, "unknown_keyword",
                                              f"허용 목록 밖 키워드 {kw}(Gemini 수용 여부 미확인)", False))
            if _has_null(node) and isinstance(node.get("enum"), list) and None not in node["enum"]:
                issues.append(SchemaIssue(path, "null_not_in_enum", "type에 null이 있는데 enum에 null이 없습니다.", True))
        for p, child in _children(node, path):
            walk(child, p, depth + 1)

    if schema.get("type") != "object":
        issues.append(SchemaIssue("$", "root_not_object", "최상위 type이 object가 아닙니다.", False))
    walk(schema, "$", 1)
    return issues


def to_provider_schema(provider: str, schema: dict):
    """(변환된 복사본, 적용한 변환 메모 목록). 원본은 바꾸지 않는다.

    OpenAI: 지원하지 않는 키워드 제거, additionalProperties false 추가, enum에 null 추가.
    선택 속성이 있으면 SchemaIncompatible(의미가 바뀌는 변환은 하지 않음).
    Gemini: 현재는 변환 없이 복사(enum에 null 누락만 보정).
    """
    issues = schema_lint(provider, schema)
    blocking = [i for i in issues if not i.auto_fix and i.code in ("optional_property", "too_deep", "root_not_object")]
    if blocking:
        raise SchemaIncompatible(blocking)
    out = copy.deepcopy(schema)
    notes = []

    def fix(node, path):
        if provider == "openai":
            for kw in OPENAI_UNSUPPORTED:
                if kw in node:
                    notes.append(f"{path}: {kw} 제거")
                    del node[kw]
            if _is_object(node) and node.get("additionalProperties") is not False:
                node["additionalProperties"] = False
                notes.append(f"{path}: additionalProperties false 추가")
        if _has_null(node) and isinstance(node.get("enum"), list) and None not in node["enum"]:
            node["enum"].append(None)
            notes.append(f"{path}: enum에 null 추가")
        for p, child in _children(node, path):
            fix(child, p)

    fix(out, "$")
    return out, notes
