"""Shared rule record schema for extraction and evaluation."""
from dataclasses import asdict, dataclass


RULE_CLASSES = {"OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule"}


@dataclass
class RuleRecord:
    ruleId: str
    class_: str
    station: str = ""
    sensor: str = ""
    sensorType: str = ""
    condition: str = ""
    action: str = ""
    ruleSeverity: str = ""
    critHi: str = ""
    warnHi: str = ""
    critLo: str = ""
    warnLo: str = ""
    unit: str = ""
    source: str = ""
    sourceDocument: str = ""
    provenanceId: str = ""
    extractionMethod: str = "deterministic"

    def to_dict(self):
        d = asdict(self)
        d["class"] = d.pop("class_")
        return d

    @classmethod
    def from_dict(cls, row):
        data = dict(row)
        if "class" in data:
            data["class_"] = data.pop("class")
        return cls(**{k: data.get(k, "") for k in cls.__dataclass_fields__})


def validate_rule(rule: RuleRecord):
    if not rule.ruleId:
        raise ValueError("ruleId is required")
    if rule.class_ not in RULE_CLASSES:
        raise ValueError(f"unknown rule class: {rule.class_}")
    if not rule.sourceDocument:
        raise ValueError(f"{rule.ruleId}: sourceDocument is required")
    if not rule.provenanceId:
        raise ValueError(f"{rule.ruleId}: provenanceId is required")
    return rule
