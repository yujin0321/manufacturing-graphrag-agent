"""센서 시계열 전처리.

실행: PYTHONPATH=src .venv/Scripts/python.exe -m imaks_kg.preprocess.sensors

- 입력(읽기 전용): imaks_data/sensors/timeseries_raw.csv, timeseries_annotated.csv
- ts_input.csv에는 허용목록 7개 컬럼만 넣는다. 허용목록에 없는 컬럼은 이름과 상관없이 다른 폴더로 분리한다.
- 정답 라벨 컬럼 = (annotated 컬럼 집합) - (raw 컬럼 집합). 이름을 코드에 적지 않는다.
- value는 원본 문자열 그대로(float 변환 없음). 이상값 삭제·보간·평활화 없음.
"""
import csv
import sys
from collections import defaultdict

from imaks_kg.common.io_utils import read_csv_rows, write_csv, write_json
from imaks_kg.common.provenance import sha256_file
from imaks_kg.settings import (
    EVALUATION_DIR, FORBIDDEN_COLUMNS_FILE, FORBIDDEN_HEADER_ONLY_FILE,
    RAW_SENSORS_DIR, REPO_ROOT, SENSORS_OUT, rel,
)

ALLOW = ["timestamp", "zone", "station_id", "sensor_id", "sensor_type", "value", "unit"]
TIME_LABELS = ["day", "shift", "batch_id"]
THRESH_SRC = ["nominal", "warn_lo", "warn_hi", "crit_lo", "crit_hi"]
QUALITY_COL = "quality"
# 출력 컬럼명은 온톨로지 속성 이름에 맞춘다(THRESH_SRC 순서와 1:1 대응)
THR_OUT_COLS = ["sensor_id", "unit", "nominalValue", "warnLo", "warnHi", "critLo", "critHi"]

EXPECTED_ROWS = 211_200
EXPECTED_SENSORS = 22
EXPECTED_TIMESTAMPS = 9_600

RAW_FILE = RAW_SENSORS_DIR / "timeseries_raw.csv"
ANN_FILE = RAW_SENSORS_DIR / "timeseries_annotated.csv"
OUT_INPUT = SENSORS_OUT / "input" / "ts_input.csv"
OUT_TIME = SENSORS_OUT / "metadata" / "original_time_labels.csv"
OUT_THR = SENSORS_OUT / "rules" / "sensor_thresholds.csv"
OUT_LABELS = EVALUATION_DIR / "row_labels.csv"
OUT_PROFILE = SENSORS_OUT / "profile.json"


def load_words(path):
    if not path.exists():
        return []
    return [l.strip() for l in path.read_text(encoding="utf-8").splitlines()
            if l.strip() and not l.startswith("#")]


def key_of(r):
    return (r["sensor_id"], r["timestamp"])


def main():
    raw_header, raw = read_csv_rows(RAW_FILE)
    ann_header, ann = read_csv_rows(ANN_FILE)

    # 컬럼 구조 확인
    assert set(ALLOW) <= set(raw_header), "허용목록 컬럼이 raw에 없음"
    expected_raw = set(ALLOW) | set(TIME_LABELS) | set(THRESH_SRC) | {QUALITY_COL}
    assert set(raw_header) == expected_raw, f"raw 컬럼이 예상과 다름: {sorted(set(raw_header) ^ expected_raw)}"
    label_cols = [c for c in ann_header if c not in set(raw_header)]  # 집합 차로 정답 라벨 컬럼을 구한다
    assert label_cols, "annotated에 추가 컬럼이 없음"
    assert set(raw_header) <= set(ann_header)
    assert len(raw) == len(ann)

    # raw/annotated 행 대응과 공통 컬럼 동일성
    ann_by_key = {}
    for r in ann:
        ann_by_key[key_of(r)] = r
    assert len(ann_by_key) == len(ann), "annotated 키 중복"
    raw_keys = set()
    for r in raw:
        k = key_of(r)
        assert k not in raw_keys, f"raw 키 중복: {k}"
        raw_keys.add(k)
        a = ann_by_key[k]
        for c in raw_header:
            assert a[c] == r[c], f"raw/annotated 값 불일치 {k} {c}"

    # 결측(허용목록 컬럼) 수
    missing = {c: sum(1 for r in raw if r[c] == "") for c in ALLOW}

    # 1) ts_input
    srt = sorted(raw, key=key_of)
    write_csv(OUT_INPUT, ALLOW, ([r[c] for c in ALLOW] for r in srt))

    # 2) 원본 시간 라벨 보존
    write_csv(OUT_TIME, ["sensor_id", "timestamp", "original_day", "original_shift", "original_batch_id"],
              ([r["sensor_id"], r["timestamp"], r["day"], r["shift"], r["batch_id"]] for r in srt))

    # 3) 센서별 임계값(값이 센서마다 일정해야 함)
    per = defaultdict(set)
    for r in raw:
        per[r["sensor_id"]].add((r["unit"],) + tuple(r[c] for c in THRESH_SRC))
    for s, v in per.items():
        assert len(v) == 1, f"센서 {s}의 임계값/단위가 일정하지 않음: {v}"
    thr_rows = [[s] + list(next(iter(per[s]))) for s in sorted(per)]
    write_csv(OUT_THR, THR_OUT_COLS, thr_rows)

    # 4) 평가 전용 라벨
    ann_sorted = sorted(ann, key=key_of)
    write_csv(OUT_LABELS, ["sensor_id", "timestamp"] + label_cols + [QUALITY_COL],
              ([r["sensor_id"], r["timestamp"]] + [r[c] for c in label_cols] + [r[QUALITY_COL]] for r in ann_sorted))

    # ---- 검증(산출물을 다시 읽어서) ----
    h_in, rows_in = read_csv_rows(OUT_INPUT)
    assert h_in == ALLOW and len(h_in) == 7, "ts_input 헤더는 정확히 7개"
    assert len(rows_in) == EXPECTED_ROWS, len(rows_in)
    assert len({r["sensor_id"] for r in rows_in}) == EXPECTED_SENSORS
    assert len({r["timestamp"] for r in rows_in}) == EXPECTED_TIMESTAMPS
    keys_in = [key_of(r) for r in rows_in]
    assert len(set(keys_in)) == len(keys_in), "(sensor_id,timestamp) 중복"
    assert keys_in == sorted(keys_in), "정렬 위반"
    raw_val = {key_of(r): r["value"] for r in raw}
    assert all(raw_val[key_of(r)] == r["value"] for r in rows_in), "value가 원본 문자열과 다름"
    h_t, rows_t = read_csv_rows(OUT_TIME)
    assert len(rows_t) == EXPECTED_ROWS and [key_of(r) for r in rows_t] == keys_in
    assert len(thr_rows) == EXPECTED_SENSORS
    h_l, rows_l = read_csv_rows(OUT_LABELS)
    assert len(rows_l) == EXPECTED_ROWS and [key_of(r) for r in rows_l] == keys_in
    # 허용목록에 없는 컬럼이 ts_input에 없다
    assert set(h_in) == set(ALLOW)

    # 점검: ts_input 헤더가 금지어(두 목록)와 겹치지 않는다. 목록은 파일에서 읽는다.
    banned = {w.lower() for w in load_words(FORBIDDEN_COLUMNS_FILE) + load_words(FORBIDDEN_HEADER_ONLY_FILE)}
    assert not ({c.lower() for c in h_in} & banned), "ts_input 헤더에 금지 컬럼"

    profile = {
        "rows": len(rows_in),
        "sensors": len({r["sensor_id"] for r in rows_in}),
        "timestamps": len({r["timestamp"] for r in rows_in}),
        "missing_by_allowed_column": missing,
        "duplicate_sensor_timestamp_keys": len(keys_in) - len(set(keys_in)),
        "ts_input_columns": h_in,
        "separated_label_column_count": len(label_cols),
        "separated_time_label_columns": len(TIME_LABELS),
        "threshold_rows": len(thr_rows),
        "source_sha256": {rel(RAW_FILE): sha256_file(RAW_FILE), rel(ANN_FILE): sha256_file(ANN_FILE)},
        "output_sha256": {rel(p): sha256_file(p) for p in (OUT_INPUT, OUT_TIME, OUT_THR, OUT_LABELS)},
        "checks_passed": [
            "rows=211200", "sensors=22", "timestamps=9600", "no_duplicate_keys",
            "value_string_identical_to_source", "sorted_by_sensor_id_timestamp",
            "ts_input_header_exactly_7", "raw_and_annotated_common_columns_equal",
            "per_sensor_thresholds_constant", "ts_input_header_not_in_forbidden_lists",
        ],
    }
    write_json(OUT_PROFILE, profile)
    print(f"ts_input 행 {len(rows_in)}, 센서 {profile['sensors']}, timestamp {profile['timestamps']}, 임계값 행 {len(thr_rows)}")
    print("산출물:", ", ".join(rel(p) for p in (OUT_INPUT, OUT_TIME, OUT_THR, OUT_LABELS, OUT_PROFILE)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
