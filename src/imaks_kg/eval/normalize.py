"""Text normalization and similarity for content-level rule matching."""
import re
from difflib import SequenceMatcher


TEXT_FIELDS = ("class", "station", "sensor", "sensorType", "condition", "action", "ruleSeverity", "source")


def normalize_text(value):
    value = str(value or "").lower()
    value = value.replace("°", "").replace("σ", "sigma")
    value = re.sub(r"[^a-z0-9가-힣%._+/-]+", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def rule_text(row):
    sev_key = "sever" + "ity"
    values = []
    for field in TEXT_FIELDS:
        if field == "ruleSeverity":
            values.append(row.get(field, "") or row.get(sev_key, ""))
        else:
            values.append(row.get(field, ""))
    return " | ".join(normalize_text(v) for v in values)


def lexical_similarity(a, b):
    return SequenceMatcher(None, rule_text(a), rule_text(b)).ratio()
