"""예측 JSONL 로더. 한 줄 = 규칙 하나. 형식 오류는 줄 번호와 이유로 예외."""
import json
from dataclasses import dataclass
from pathlib import Path

CLASSES = ("OperationalRule", "ThresholdRule", "MaintenanceRule", "AccessRule")


class PredictionError(ValueError):
    pass


@dataclass(frozen=True)
class Prediction:
    key: str  # 줄 번호 기반 고유 키
    doc: str
    cls: str
    condition: str
    action: str
    identifier: str | None = None
    sensors: tuple | None = None
    model: str | None = None


def load_predictions(path: Path, known_docs: set[str]) -> list[Prediction]:
    out = []
    name = Path(path).name
    with Path(path).open(encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if not line.strip():
                continue

            def bad(msg, n=n):
                return PredictionError(f"{name} {n}번째 줄: {msg}")

            try:
                rec = json.loads(line)
            except json.JSONDecodeError as e:
                raise bad(f"JSON 파싱 실패 ({e.msg})")
            if not isinstance(rec, dict):
                raise bad("JSON 객체가 아닙니다")
            for k in ("document_id", "class", "condition", "action"):
                if not isinstance(rec.get(k), str):
                    raise bad(f"'{k}'가 없거나 문자열이 아닙니다")
            if rec["document_id"] not in known_docs:
                raise bad(f"알 수 없는 document_id: {rec['document_id']!r}")
            if rec["class"] not in CLASSES:
                raise bad(f"class가 4분류 중 하나가 아닙니다: {rec['class']!r}")
            if not (rec["condition"].strip() or rec["action"].strip()):
                raise bad("condition과 action이 모두 비어 있습니다")
            ident = rec.get("identifier")
            if ident is not None and not isinstance(ident, str):
                raise bad("'identifier'는 문자열 또는 null이어야 합니다")
            sensors = rec.get("sensors")
            if sensors is not None:
                if not isinstance(sensors, list) or not all(isinstance(s, str) for s in sensors):
                    raise bad("'sensors'는 문자열 배열 또는 null이어야 합니다")
                sensors = tuple(sensors)
            if rec.get("model") is not None and not isinstance(rec["model"], str):
                raise bad("'model'은 문자열 또는 null이어야 합니다")
            out.append(Prediction(f"L{n}", rec["document_id"], rec["class"], rec["condition"], rec["action"],
                                  ident, sensors, rec.get("model")))
    return out
