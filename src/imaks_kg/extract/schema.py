"""LLM 출력 스키마: 구조화 출력용 JSON Schema와 같은 내용의 pydantic 모델.

최상위 {"rules": [...]}. 항목마다 class(4분류), conditionText, responseText, ruleSeverity(문자열|null),
sensors(seed 센서 22개 enum), targetStations(seed 공정 9개 enum), sourceQuote, ruleIdInText(문자열|null),
actionSteps(문자열 배열, 빈 배열 가능). additionalProperties=false, 모든 항목 required.

enum 값은 코드에 적지 않고 seed.ttl에서 읽은 목록으로 만든다(build_schema 인자).
pydantic 모델은 형식(타입·필수·추가 키 금지)만 검사하고, 목록 밖 ID는 validate.py가 사유를 따로 남기며 거부한다.
"""
from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

RULE_CLASSES = ("OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule")
ITEM_FIELDS = ("class", "conditionText", "responseText", "ruleSeverity", "sensors", "targetStations",
               "sourceQuote", "ruleIdInText", "actionSteps")


def build_schema(sensor_ids, station_ids) -> dict:
    sensor_ids, station_ids = sorted(sensor_ids), sorted(station_ids)
    item = {
        "type": "object",
        "properties": {
            "class": {"type": "string", "enum": list(RULE_CLASSES)},
            "conditionText": {"type": "string"},
            "responseText": {"type": "string"},
            "ruleSeverity": {"type": ["string", "null"]},
            "sensors": {"type": "array", "items": {"type": "string", "enum": sensor_ids}},
            "targetStations": {"type": "array", "items": {"type": "string", "enum": station_ids}},
            "sourceQuote": {"type": "string"},
            "ruleIdInText": {"type": ["string", "null"]},
            "actionSteps": {"type": "array", "items": {"type": "string"}},
        },
        "required": list(ITEM_FIELDS),
        "additionalProperties": False,
    }
    return {
        "type": "object",
        "properties": {"rules": {"type": "array", "items": item}},
        "required": ["rules"],
        "additionalProperties": False,
    }


class RuleItem(BaseModel):
    """응답 항목 하나. strict: 문자열 자리에 숫자 등 다른 타입이 오면 거부."""
    model_config = ConfigDict(extra="forbid", strict=True, populate_by_name=True)

    rule_class: Literal["OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule"] = Field(alias="class")
    conditionText: str
    responseText: str
    ruleSeverity: Optional[str]
    sensors: List[str]
    targetStations: List[str]
    sourceQuote: str
    ruleIdInText: Optional[str]
    actionSteps: List[str]

    def as_dict(self) -> dict:
        return {
            "class": self.rule_class, "conditionText": self.conditionText, "responseText": self.responseText,
            "ruleSeverity": self.ruleSeverity, "sensors": list(self.sensors),
            "targetStations": list(self.targetStations), "sourceQuote": self.sourceQuote,
            "ruleIdInText": self.ruleIdInText, "actionSteps": list(self.actionSteps),
        }
