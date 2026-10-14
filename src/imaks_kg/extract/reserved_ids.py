"""접미사 후보가 피해야 할 ③ 산출물 identifier 목록. identifier 열만 읽는다(정비 규칙 문구 열은 읽지 않는다).
요청 빌더·docdata와 분리했다: 요청 쪽 코드는 seed 정비 규칙 파일을 열지 않는다는 시험(소스 문자열 검사)을 유지하기 위해서다."""
from __future__ import annotations

from pathlib import Path

from imaks_kg.extract.docdata import _identifier_column
from imaks_kg.settings import KG_BUILD


def load_reserved_identifiers(instances_dir: Path | None = None) -> tuple:
    """③ 산출물(Station·Sensor·정비 규칙·문서)의 identifier. 접미사 후보가 겹치지 않게 피할 때만 쓴다."""
    d = Path(instances_dir) if instances_dir else KG_BUILD / "instances"
    out: list = []
    for name in ("stations.csv", "sensors.csv", "maintenance_rules.csv", "documents.csv"):
        if (d / name).is_file():
            try:
                out += _identifier_column(d / name)
            except ValueError:
                pass
    return tuple(out)
