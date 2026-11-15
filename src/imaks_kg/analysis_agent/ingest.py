"""업로드 센서 CSV → 룰 엔진 입력(7개 컬럼) 정규화.

* 필수 컬럼: timestamp, sensor_id, value. 나머지 허용 컬럼(zone, station_id, sensor_type, unit)은
  있으면 기준 메타데이터와 대조하고, 없으면 기준 메타데이터로 채운다.
* 그 밖의 컬럼은 읽지 않고 버린다. 정답 라벨(anomaly_label, severity, alarm_flag), quality,
  임계값 컬럼(nominal, warn_*, crit_*), day/shift/batch_id가 여기에 해당하며 보고서에 이름만 남긴다.
  임계값은 업로드 파일이 아니라 저장소의 고정 메타데이터와 KG에서만 가져온다.
* 이상값을 지우거나 보정하지 않는다. 숫자가 아니거나 비어 있는 값만 평가 불가로 제외하고 개수를 남긴다.
* 룰의 지속 시간은 표본 수로 계산되므로 30초 간격 데이터만 받는다.
"""
from __future__ import annotations

import csv
import io
import math
import statistics
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from imaks_kg.detection import rules as v1
from imaks_kg.rag import vector as v

REQUIRED = ("timestamp", "sensor_id", "value")
META = ("zone", "station_id", "sensor_type", "unit")
LABEL_LIKE = {"anomaly_label", "severity", "alarm_flag", "quality", "nominal", "warn_hi", "warn_lo",
              "crit_hi", "crit_lo", "day", "shift", "batch_id", "status", "alarms", "gt_id", "event_id"}
SAMPLE_SECONDS = 30
MAX_BYTES = 60 * 1024 * 1024
MAX_ROWS = 600_000
REFERENCE_CACHE = v.REPO_ROOT / "kg_build/analysis_agent/reference_metadata.json"


class IngestError(ValueError):
    """사용자에게 그대로 보여줄 수 있는 입력 오류."""

    def __init__(self, message: str, details: dict | None = None):
        super().__init__(message)
        self.details = details or {}


def reference_metadata() -> dict:
    """센서별 zone/station/type/unit/임계값. 고정 기준 입력에서 한 번 만들고 해시로 캐시한다."""
    profile = v.read(v.REPO_ROOT / "preprocessed/sensors/profile.json")
    key = {p: profile["output_sha256"][p] for p in (v1.INPUT, v1.THRESHOLDS)}
    if REFERENCE_CACHE.exists():
        cached = v.read(REFERENCE_CACHE)
        if cached.get("source_sha256") == key:
            return cached
    groups, thresholds, _ = v1.read_inputs()
    sensors = {}
    for sid, rows in groups.items():
        first, t = rows[0], thresholds[sid]
        sensors[sid] = {k: first[k] for k in META} | {
            "nominal": float(t["nominalValue"]), "warn_lo": float(t["warnLo"]), "warn_hi": float(t["warnHi"]),
            "crit_lo": float(t["critLo"]), "crit_hi": float(t["critHi"])}
    data = {"source_sha256": key, "sensors": sensors}
    v.write(REFERENCE_CACHE, data)
    return data


def _timestamp(raw: str) -> str:
    text = raw.strip().replace(" ", "T")
    ts = datetime.fromisoformat(text)
    if ts.tzinfo is not None:
        raise ValueError("timezone")
    return ts.strftime("%Y-%m-%dT%H:%M:%S")


def parse(data: bytes, filename: str = "upload.csv") -> tuple[dict, dict]:
    """Return (groups, report). groups: sensor_id -> 시간순 정렬된 7개 컬럼 행 목록."""
    if not data:
        raise IngestError("빈 파일입니다.")
    if len(data) > MAX_BYTES:
        raise IngestError(f"파일이 너무 큽니다(최대 {MAX_BYTES // (1024 * 1024)}MB).")
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise IngestError("UTF-8 CSV 파일만 지원합니다.") from None
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = [h.strip() for h in (reader.fieldnames or [])]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise IngestError(f"필수 컬럼이 없습니다: {', '.join(missing)}", {"columns": header})
    reader.fieldnames = header
    used = set(REQUIRED) | (set(META) & set(header))
    dropped = [h for h in header if h not in used]

    meta = reference_metadata()["sensors"]
    grouped: dict[str, list[dict]] = defaultdict(list)
    seen: set[tuple[str, str]] = set()
    unknown: dict[str, int] = defaultdict(int)
    invalid_values = 0
    errors: list[str] = []
    rows = 0
    for line_no, row in enumerate(reader, start=2):
        rows += 1
        if rows > MAX_ROWS:
            raise IngestError(f"행이 너무 많습니다(최대 {MAX_ROWS:,}행).")
        sid = (row.get("sensor_id") or "").strip()
        if sid not in meta:
            unknown[sid] += 1
            continue
        try:
            ts = _timestamp(row.get("timestamp") or "")
        except ValueError:
            if len(errors) < 5:
                errors.append(f"{line_no}행: timestamp 형식 오류")
            continue
        value = (row.get("value") or "").strip()
        try:
            ok = math.isfinite(float(value))
        except ValueError:
            ok = False
        if not ok:
            invalid_values += 1
            continue
        ref = meta[sid]
        for col in META:
            given = (row.get(col) or "").strip()
            if col in header and given and given != ref[col]:
                if len(errors) < 5:
                    errors.append(f"{line_no}행: {sid}의 {col} 값({given})이 기준({ref[col]})과 다름")
                break
        else:
            if (sid, ts) in seen:
                raise IngestError(f"같은 센서·시각이 중복됩니다: {sid} {ts}")
            seen.add((sid, ts))
            grouped[sid].append({"timestamp": ts, "zone": ref["zone"], "station_id": ref["station_id"],
                                 "sensor_id": sid, "sensor_type": ref["sensor_type"], "value": value,
                                 "unit": ref["unit"]})
    if errors:
        raise IngestError("입력 행에 오류가 있습니다.", {"errors": errors})
    if not grouped:
        raise IngestError("분석 가능한 센서 행이 없습니다. sensor_id가 기준 센서 22개 중 하나인지 확인해 주세요.",
                          {"unknown_sensor_ids": sorted(unknown)[:20]})
    spacing = {}
    for sid, items in grouped.items():
        items.sort(key=lambda r: r["timestamp"])
        if len(items) < 2:
            raise IngestError(f"{sid}: 표본이 2개 미만입니다.")
        stamps = [datetime.fromisoformat(r["timestamp"]) for r in items]
        diffs = [(b - a).total_seconds() for a, b in zip(stamps, stamps[1:])]
        spacing[sid] = statistics.median(diffs)
        if spacing[sid] != SAMPLE_SECONDS:
            raise IngestError(f"{sid}: 표본 간격 중앙값이 {spacing[sid]:g}초입니다. {SAMPLE_SECONDS}초 간격 데이터만 지원합니다.")
    starts = [items[0]["timestamp"] for items in grouped.values()]
    ends = [items[-1]["timestamp"] for items in grouped.values()]
    report = {"file_name": Path(filename).name, "file_sha256": v.digest(data), "rows_read": rows,
              "rows_used": sum(len(x) for x in grouped.values()), "sensors": sorted(grouped),
              "sensors_missing": sorted(set(meta) - set(grouped)),
              "period": {"start": min(starts), "end": max(ends)},
              "dropped_columns": dropped, "dropped_label_like_columns": sorted(set(dropped) & LABEL_LIKE),
              "unknown_sensor_rows": dict(sorted(unknown.items())), "invalid_value_rows": invalid_values,
              "sample_seconds": SAMPLE_SECONDS, "labels_read": False}
    return dict(grouped), report


def write_normalized(groups: dict, path: Path) -> str:
    """정규화 입력을 기준 입력과 같은 7개 컬럼 CSV로 저장하고 SHA-256을 반환한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = sorted((r for items in groups.values() for r in items), key=lambda r: (r["sensor_id"], r["timestamp"]))
    buf = io.StringIO(newline="")
    writer = csv.DictWriter(buf, fieldnames=v1.FIELDS, lineterminator="\n")
    writer.writeheader()
    writer.writerows(rows)
    data = buf.getvalue().encode("utf-8")
    path.write_bytes(data)
    return v.digest(data)
