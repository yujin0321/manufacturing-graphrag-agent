#!/usr/bin/env python3
"""Final-candidate preprocessing for the iMAKS manufacturing dataset.

This script combines the strongest parts of the team branches:

- common_v1-style separation of detector inputs, rule references, evaluation
  truth, static KG reference, and audit records.
- strict allowlist sensor input similar to the Jihoon branch.
- document extraction that preserves page/table/chunk structure and records
  glyph/table normalization decisions.

The script never edits raw data. Generated files are reproducible under
``preprocessed/final_v1`` by default.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import pdfplumber
from pdfplumber.utils import cluster_objects
from pdfplumber.utils.text import WordExtractor, get_line_cluster_key


RAW_FILES = {
    "timeseries_raw": Path("sensors/timeseries_raw.csv"),
    "timeseries_annotated": Path("sensors/timeseries_annotated.csv"),
    "mqtt_payloads": Path("sensors/mqtt_payloads.json"),
    "nodes": Path("kg_seed/nodes.csv"),
    "edges": Path("kg_seed/edges.csv"),
    "ground_truth": Path("kg_seed/ground_truth.csv"),
    "nodes_factory": Path("kg_seed/nodes_factory.csv"),
    "access_events": Path("human/access_events.csv"),
    "alarm_response_log": Path("human/alarm_response_log.csv"),
    "occupancy_timeseries": Path("human/occupancy_timeseries.csv"),
    "person_registry": Path("human/person_registry.csv"),
}

DOCUMENT_PATTERNS = ("rules/*.pdf", "datasheets/*.pdf")

KEYS = ["sensor_id", "timestamp"]
OBSERVATION_COLUMNS = ["timestamp", "zone", "station_id", "sensor_id", "sensor_type", "value", "unit"]
TIME_LABEL_COLUMNS = ["day", "shift", "batch_id"]
THRESHOLD_COLUMNS = ["nominal", "warn_hi", "crit_hi", "warn_lo", "crit_lo"]
QUALITY_COLUMN = "quality"
ANNOTATED_LABEL_COLUMNS = ["anomaly_label", "severity", "alarm_flag"]
FORBIDDEN_INPUT_COLUMNS = set(THRESHOLD_COLUMNS + [QUALITY_COLUMN] + ANNOTATED_LABEL_COLUMNS)
EXPECTED_SENSOR_ROWS = 211_200
EXPECTED_SENSOR_COUNT = 22
EXPECTED_NODE_COUNT = 115
EXPECTED_EDGE_COUNT = 341

STATIC_KG_LABELS = {"System", "Zone", "Component", "Sensor", "Person"}
EVALUATION_KG_LABELS = {"AnomalyEvent", "SafetyEvent", "Maintenance"}
LEAKAGE_NODE_FIELDS = {
    "gtId",
    "severity",
    "causedBy",
    "sourceRule",
    "startTs",
    "endTs",
    "nominalValue",
    "warnHi",
    "critHi",
    "warnLo",
    "critLo",
}

SYMBOL_FONT_KEYS = ("symbol", "zapfdingbats")
STD_TEXT_TO_CODE = {"ﬁ": 0xAE, "ﬂ": 0xAF, "›": 0xAD, "‡": 0xB3, "s": 0x73}
SYMBOL_CODE_TO_GLYPH = {0xAE: "->", 0xAD: "^", 0xAF: "v", 0xB3: ">=", 0x73: "sigma", 0xB1: "+/-"}
DOC_ID_RE = re.compile(r"Document:\s*([A-Za-z0-9\-]+)\s*\|")
RULE_RE = re.compile(r"^(RULE-[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*):")
HEADING_RE = re.compile(r"^(\d+(?:\.\d+)*)\.?\s+\S")


@dataclass
class Issue:
    issue_id: str
    area: str
    severity: str
    status: str
    description: str
    evidence: str
    policy_or_action: str


@dataclass
class AuditRow:
    area: str
    check: str
    status: str
    observed: str
    details: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build final-candidate preprocessing outputs.")
    parser.add_argument("--dataset-root", type=Path, default=Path("../iMAKS_dataset"))
    parser.add_argument("--output-root", type=Path, default=Path("preprocessed/final_v1"))
    parser.add_argument("--validate-only", action="store_true")
    return parser.parse_args()


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = [dict(row) for row in reader]
        return list(reader.fieldnames or []), rows


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> int:
    ensure_dir(path.parent)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({key: row.get(key, "") for key in fieldnames})
            count += 1
    return count


def write_json(path: Path, payload: Any) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


def write_jsonl(path: Path, rows: Iterable[dict[str, Any]]) -> int:
    ensure_dir(path.parent)
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")
            count += 1
    return count


def add_audit(audit: list[AuditRow], area: str, check: str, status: str, observed: Any, details: Any = "") -> None:
    audit.append(AuditRow(area, check, status, str(observed), json.dumps(details, ensure_ascii=False, default=str) if not isinstance(details, str) else details))


def add_issue(
    issues: list[Issue],
    issue_id: str,
    area: str,
    severity: str,
    description: str,
    evidence: Any,
    policy_or_action: str,
    status: str = "OPEN",
) -> None:
    issues.append(
        Issue(
            issue_id=issue_id,
            area=area,
            severity=severity,
            status=status,
            description=description,
            evidence=json.dumps(evidence, ensure_ascii=False, default=str) if not isinstance(evidence, str) else evidence,
            policy_or_action=policy_or_action,
        )
    )


def validate_raw_files(dataset_root: Path) -> dict[str, Path]:
    paths = {name: dataset_root / relative for name, relative in RAW_FILES.items()}
    for pattern in DOCUMENT_PATTERNS:
        for path in sorted(dataset_root.glob(pattern)):
            paths[path.stem] = path
    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError(f"Missing dataset files: {missing}")
    return paths


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_float(value: str) -> float | None:
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(x):
        return None
    return x


def sensor_key(row: dict[str, str]) -> tuple[str, str]:
    return row["sensor_id"], row["timestamp"]


def station_from_sensor(sensor_id: str, sensor_type: str) -> str:
    suffix = "_" + sensor_type
    return sensor_id[: -len(suffix)] if sensor_id.endswith(suffix) else ""


def split_name(timestamp: str) -> str:
    ts = parse_time(timestamp)
    if ts < datetime.fromisoformat("2026-01-07T00:00:00"):
        return "train"
    if ts < datetime.fromisoformat("2026-01-08T00:00:00"):
        return "validation"
    return "test"


def prepare_sensors(dataset_root: Path, output_root: Path, audit: list[AuditRow], issues: list[Issue]) -> dict[str, Any]:
    raw_header, raw_rows = read_csv_rows(dataset_root / RAW_FILES["timeseries_raw"])
    ann_header, ann_rows = read_csv_rows(dataset_root / RAW_FILES["timeseries_annotated"])

    expected_raw = set(OBSERVATION_COLUMNS + TIME_LABEL_COLUMNS + THRESHOLD_COLUMNS + [QUALITY_COLUMN])
    add_audit(audit, "sensors", "raw_schema_exact", "PASS" if set(raw_header) == expected_raw else "FAIL", raw_header)
    add_audit(audit, "sensors", "annotated_extra_columns", "PASS", sorted(set(ann_header) - set(raw_header)))
    if set(raw_header) != expected_raw:
        raise ValueError(f"Unexpected raw schema: {raw_header}")
    if set(raw_header) | set(ANNOTATED_LABEL_COLUMNS) != set(ann_header):
        raise ValueError(f"Unexpected annotated schema: {ann_header}")

    if len(raw_rows) != len(ann_rows):
        raise ValueError("raw and annotated row counts differ")
    add_audit(audit, "sensors", "row_count", "PASS" if len(raw_rows) == EXPECTED_SENSOR_ROWS else "WARN", len(raw_rows))

    ann_by_key: dict[tuple[str, str], dict[str, str]] = {}
    for row in ann_rows:
        key = sensor_key(row)
        if key in ann_by_key:
            raise ValueError(f"Duplicate annotated key: {key}")
        ann_by_key[key] = row

    raw_keys: set[tuple[str, str]] = set()
    common_mismatches = 0
    duplicate_keys = 0
    missing_by_column: Counter[str] = Counter()
    bad_numeric: Counter[str] = Counter()
    bad_timestamps = 0
    station_mismatches = 0
    sensor_type_units: dict[str, set[str]] = defaultdict(set)
    sensor_thresholds: dict[str, tuple[str, ...]] = {}
    quality_label_counts: Counter[tuple[str, str]] = Counter()

    for row in raw_rows:
        key = sensor_key(row)
        if key in raw_keys:
            duplicate_keys += 1
        raw_keys.add(key)
        ann = ann_by_key.get(key)
        if ann is None:
            common_mismatches += 1
        else:
            for column in raw_header:
                if ann[column] != row[column]:
                    common_mismatches += 1
                    break
            quality_label_counts[(row[QUALITY_COLUMN], ann["anomaly_label"])] += 1
        for column in OBSERVATION_COLUMNS + THRESHOLD_COLUMNS:
            if row[column] == "":
                missing_by_column[column] += 1
        try:
            parse_time(row["timestamp"])
        except ValueError:
            bad_timestamps += 1
        for column in ["value"] + THRESHOLD_COLUMNS:
            if to_float(row[column]) is None:
                bad_numeric[column] += 1
        expected_station = station_from_sensor(row["sensor_id"], row["sensor_type"])
        if expected_station != row["station_id"]:
            station_mismatches += 1
        sensor_type_units[row["sensor_type"]].add(row["unit"])
        packed_threshold = tuple(row[col] for col in ["unit"] + THRESHOLD_COLUMNS)
        if row["sensor_id"] in sensor_thresholds and sensor_thresholds[row["sensor_id"]] != packed_threshold:
            add_issue(
                issues,
                "SENSOR-THRESHOLD-VARIES",
                "sensors",
                "HIGH",
                "A sensor has non-constant unit/threshold metadata.",
                {"sensor_id": row["sensor_id"], "previous": sensor_thresholds[row["sensor_id"]], "current": packed_threshold},
                "Do not choose one silently; review source metadata.",
            )
        sensor_thresholds[row["sensor_id"]] = packed_threshold

    raw_sensor_ids = sorted({row["sensor_id"] for row in raw_rows})
    add_audit(audit, "sensors", "sensor_count", "PASS" if len(raw_sensor_ids) == EXPECTED_SENSOR_COUNT else "WARN", len(raw_sensor_ids))
    add_audit(audit, "sensors", "duplicate_sensor_timestamp", "PASS" if duplicate_keys == 0 else "FAIL", duplicate_keys)
    add_audit(audit, "sensors", "raw_annotated_common_columns_equal", "PASS" if common_mismatches == 0 else "FAIL", common_mismatches)
    add_audit(audit, "sensors", "timestamp_parse_errors", "PASS" if bad_timestamps == 0 else "FAIL", bad_timestamps)
    add_audit(audit, "sensors", "missing_values", "PASS" if not missing_by_column else "WARN", dict(missing_by_column))
    add_audit(audit, "sensors", "numeric_parse_errors", "PASS" if not bad_numeric else "FAIL", dict(bad_numeric))
    add_audit(audit, "sensors", "sensor_id_structure", "PASS" if station_mismatches == 0 else "FAIL", station_mismatches)
    add_audit(audit, "sensors", "sensor_type_unit_sets", "PASS", {k: sorted(v) for k, v in sensor_type_units.items()})

    sorted_rows = sorted(raw_rows, key=sensor_key)
    intervals: Counter[tuple[str, float]] = Counter()
    sampling_gaps: list[dict[str, Any]] = []
    previous_by_sensor: dict[str, datetime] = {}
    for row in sorted_rows:
        ts = parse_time(row["timestamp"])
        sensor = row["sensor_id"]
        if sensor in previous_by_sensor:
            delta = (ts - previous_by_sensor[sensor]).total_seconds()
            intervals[(sensor, delta)] += 1
            if delta != 30:
                sampling_gaps.append({"sensor_id": sensor, "timestamp": row["timestamp"], "interval_seconds": delta})
        previous_by_sensor[sensor] = ts
    add_audit(audit, "sensors", "sampling_interval", "PASS" if not sampling_gaps else "WARN", len(sampling_gaps))

    uncertain_stuck = quality_label_counts.get(("UNCERTAIN", "STUCK"), 0)
    uncertain_total = sum(v for (quality, _label), v in quality_label_counts.items() if quality == "UNCERTAIN")
    if uncertain_total:
        add_issue(
            issues,
            "LEAK-SENSOR-QUALITY",
            "sensors",
            "HIGH",
            "`quality` is label-like and aligns with STUCK rows.",
            {"UNCERTAIN_total": uncertain_total, "UNCERTAIN_STUCK": uncertain_stuck},
            "Exclude `quality` from detector inputs; preserve it only in evaluation/audit metadata.",
            status="POLICY_APPLIED",
        )

    threshold_hits: dict[str, dict[str, int]] = {}
    for label in sorted({row["anomaly_label"] for row in ann_rows}):
        if label == "NORMAL":
            continue
        total = 0
        hits = 0
        for row in ann_rows:
            if row["anomaly_label"] != label:
                continue
            value = to_float(row["value"])
            warn_hi = to_float(row["warn_hi"])
            crit_hi = to_float(row["crit_hi"])
            warn_lo = to_float(row["warn_lo"])
            crit_lo = to_float(row["crit_lo"])
            if None in {value, warn_hi, crit_hi, warn_lo, crit_lo}:
                continue
            total += 1
            if value > warn_hi or value > crit_hi or value < warn_lo or value < crit_lo:
                hits += 1
        threshold_hits[label] = {"rows": total, "threshold_hits": hits}
    add_issue(
        issues,
        "LEAK-SENSOR-THRESHOLDS",
        "sensors",
        "MEDIUM",
        "Threshold columns are operational prior knowledge, not labels, but can make rule-based detection incomparable to pattern-only ML.",
        threshold_hits,
        "Keep thresholds in rule reference only; exclude them from ML/pattern input.",
        status="POLICY_APPLIED",
    )

    sensor_dir = output_root / "inputs" / "sensors"
    metadata_dir = output_root / "metadata"
    evaluation_dir = output_root / "evaluation"
    audit_dir = output_root / "audit"

    ml_rows = [{column: row[column] for column in OBSERVATION_COLUMNS} for row in sorted_rows]
    rule_rows = [{column: row[column] for column in OBSERVATION_COLUMNS + THRESHOLD_COLUMNS} for row in sorted_rows]
    label_by_key = {sensor_key(row): row for row in ann_rows}
    label_rows = []
    metadata_rows = []
    for row in sorted_rows:
        key = sensor_key(row)
        ann = label_by_key[key]
        label_rows.append(
            {
                "sensor_id": row["sensor_id"],
                "timestamp": row["timestamp"],
                "anomaly_label": ann["anomaly_label"],
                "dataset_severity": ann["severity"],
                "alarm_flag": ann["alarm_flag"],
                "quality": row["quality"],
                "split": split_name(row["timestamp"]),
            }
        )
        metadata_rows.append(
            {
                "sensor_id": row["sensor_id"],
                "timestamp": row["timestamp"],
                "source_day": row["day"],
                "source_shift": row["shift"],
                "source_batch_id": row["batch_id"],
                "split": split_name(row["timestamp"]),
            }
        )

    write_csv(sensor_dir / "timeseries_ml_input.csv", ml_rows, OBSERVATION_COLUMNS)
    write_csv(sensor_dir / "timeseries_rule_input.csv", rule_rows, OBSERVATION_COLUMNS + THRESHOLD_COLUMNS)
    write_csv(evaluation_dir / "row_labels.csv", label_rows, ["sensor_id", "timestamp", "anomaly_label", "dataset_severity", "alarm_flag", "quality", "split"])
    write_csv(metadata_dir / "sensor_time_metadata.csv", metadata_rows, ["sensor_id", "timestamp", "source_day", "source_shift", "source_batch_id", "split"])
    write_csv(audit_dir / "sampling_intervals.csv", ({"sensor_id": s, "interval_seconds": d, "count": c} for (s, d), c in sorted(intervals.items())), ["sensor_id", "interval_seconds", "count"])
    write_csv(audit_dir / "sampling_gaps.csv", sampling_gaps, ["sensor_id", "timestamp", "interval_seconds"])
    write_json(metadata_dir / "input_policy.json", {
        "ml_input": "timeseries_ml_input.csv contains only timestamp/zone/station_id/sensor_id/sensor_type/value/unit.",
        "rule_input": "timeseries_rule_input.csv adds nominal/warn/crit thresholds for rule baselines and GraphRAG reference.",
        "forbidden_ml_columns": sorted(FORBIDDEN_INPUT_COLUMNS),
        "label_join": "Evaluation labels are joined by sensor_id + timestamp only.",
        "imputation": "None",
        "smoothing": "None",
        "normalization": "Not performed in preprocessing.",
    })

    return {
        "rows": len(raw_rows),
        "sensors": len(raw_sensor_ids),
        "timestamp_count": len({row["timestamp"] for row in raw_rows}),
        "sampling_gaps": len(sampling_gaps),
        "quality_label_counts": {f"{a}|{b}": c for (a, b), c in quality_label_counts.items()},
        "threshold_hits_by_label": threshold_hits,
    }


def sanitize_mqtt(dataset_root: Path, output_root: Path, audit: list[AuditRow], issues: list[Issue]) -> dict[str, Any]:
    payloads = json.loads((dataset_root / RAW_FILES["mqtt_payloads"]).read_text(encoding="utf-8"))
    if not isinstance(payloads, list):
        raise ValueError("MQTT payload source must be a JSON list.")

    status_counts: Counter[str] = Counter()
    alarm_payloads = 0
    reading_quality_counts: Counter[str] = Counter()
    sanitized_rows: list[dict[str, Any]] = []

    for payload in payloads:
        clean = json.loads(json.dumps(payload, ensure_ascii=False))
        status_counts[str(clean.get("status", ""))] += 1
        if clean.get("alarms"):
            alarm_payloads += 1
        clean.pop("status", None)
        clean.pop("alarms", None)
        for reading in clean.get("readings", {}).values():
            if isinstance(reading, dict) and "quality" in reading:
                reading_quality_counts[str(reading.get("quality", ""))] += 1
                reading.pop("quality", None)
        sanitized_rows.append(clean)

    write_jsonl(output_root / "inputs" / "sensors" / "mqtt_stream_input.jsonl", sanitized_rows)
    add_audit(audit, "mqtt", "payload_count", "PASS", len(payloads))
    add_audit(audit, "mqtt", "source_status_counts", "WARN", dict(status_counts))
    add_audit(audit, "mqtt", "source_alarm_payloads", "WARN", alarm_payloads)
    add_audit(audit, "mqtt", "nested_quality_removed", "WARN", dict(reading_quality_counts))
    add_issue(
        issues,
        "LEAK-MQTT-STATUS-ALARMS",
        "mqtt",
        "HIGH",
        "MQTT status, alarms, and nested reading quality expose label-like operational state.",
        {"status_counts": dict(status_counts), "alarm_payloads": alarm_payloads, "reading_quality": dict(reading_quality_counts)},
        "Write sanitized stream without status, alarms, or reading quality; preserve original raw file.",
        status="POLICY_APPLIED",
    )
    return {"messages": len(payloads), "alarm_payloads": alarm_payloads, "status_counts": dict(status_counts)}


def build_lines(chars: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if not chars:
        return []
    extractor = WordExtractor()
    words = extractor.extract_words(chars)
    clusters = cluster_objects(words, get_line_cluster_key(extractor.line_dir), 3)
    return [
        {
            "text": " ".join(word["text"] for word in cluster),
            "x0": min(word["x0"] for word in cluster),
            "x1": max(word["x1"] for word in cluster),
            "top": min(word["top"] for word in cluster),
            "bottom": max(word["bottom"] for word in cluster),
        }
        for cluster in clusters
    ]


def is_symbol_char(char: dict[str, Any]) -> bool:
    font = str(char.get("fontname", "")).lower()
    return any(key in font for key in SYMBOL_FONT_KEYS)


def fix_symbol_chars(chars: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    fixed: list[dict[str, Any]] = []
    fixes: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = []
    for index, char in enumerate(chars):
        if is_symbol_char(char):
            code = STD_TEXT_TO_CODE.get(char.get("text", ""))
            glyph = SYMBOL_CODE_TO_GLYPH.get(code) if code is not None else None
            if glyph is not None:
                new_char = dict(char)
                new_char["text"] = glyph
                fixed.append(new_char)
                fixes.append({"char_index": index, "before": char.get("text", ""), "after": glyph, "code": code, "font": char.get("fontname", "")})
                continue
            unresolved.append({"char_index": index, "text": char.get("text", ""), "font": char.get("fontname", "")})
        fixed.append(char)
    return fixed, fixes, unresolved


def cell_text(chars: list[dict[str, Any]], bbox: tuple[float, float, float, float] | None) -> str:
    if bbox is None:
        return ""
    selected = []
    for char in chars:
        cx = (char["x0"] + char["x1"]) / 2
        cy = (char["top"] + char["bottom"]) / 2
        if bbox[0] <= cx <= bbox[2] and bbox[1] <= cy <= bbox[3]:
            selected.append(char)
    return "\n".join(line["text"] for line in build_lines(selected))


def normalize_cell(text: str, header_cell: bool, id_like_cell: bool) -> tuple[str, bool]:
    parts = [part.strip() for part in text.split("\n")]
    if not parts:
        return "", False
    merged = parts[0]
    joined_no_space = False
    for part in parts[1:]:
        if header_cell or id_like_cell or merged.endswith(("-", "_")) or part.startswith("_"):
            merged += part
            joined_no_space = True
        else:
            merged += " " + part
    return merged.replace("R&D;", "R&D"), joined_no_space


def document_id_from_pdf(path: Path, first_text: str) -> str:
    match = DOC_ID_RE.search(first_text)
    if match:
        return match.group(1)
    if path.name.startswith("SOP_"):
        return "SOP-" + path.stem.split("_")[1]
    return path.stem.upper().replace("_", "-")


def extract_documents(dataset_root: Path, output_root: Path, audit: list[AuditRow], issues: list[Issue]) -> dict[str, Any]:
    pdfs: list[Path] = []
    for pattern in DOCUMENT_PATTERNS:
        pdfs.extend(sorted(dataset_root.glob(pattern)))
    if not pdfs:
        raise FileNotFoundError("No SOP/Datasheet PDFs found.")

    manifest: list[dict[str, Any]] = []
    pages: list[dict[str, Any]] = []
    tables: list[dict[str, Any]] = []
    chunks: list[dict[str, Any]] = []
    glyph_fixes: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_doc_ids: set[str] = set()

    for pdf_path in pdfs:
        file_sha = sha256_file(pdf_path)
        with pdfplumber.open(pdf_path) as pdf:
            first_text = pdf.pages[0].extract_text() or ""
            doc_id = document_id_from_pdf(pdf_path, first_text)
            if doc_id in seen_doc_ids:
                raise ValueError(f"Duplicate document_id: {doc_id}")
            seen_doc_ids.add(doc_id)
            manifest.append({"document_id": doc_id, "source_file": str(pdf_path.relative_to(dataset_root)), "page_count": len(pdf.pages), "file_sha256": file_sha})

            section = ""
            for page_no, page in enumerate(pdf.pages, 1):
                raw_chars = list(page.chars)
                fixed_chars, fixes, unresolved = fix_symbol_chars(raw_chars)
                for fix in fixes:
                    glyph_fixes.append({"document_id": doc_id, "page": page_no, "scope": "page", **fix})
                for item in unresolved:
                    warnings.append(f"{doc_id} p{page_no}: unresolved symbol char {item}")

                raw_lines = build_lines(raw_chars)
                fixed_lines = build_lines(fixed_chars)
                raw_text = "\n".join(line["text"] for line in raw_lines)
                normalized_text = "\n".join(line["text"].replace("R&D;", "R&D") for line in fixed_lines)
                pages.append(
                    {
                        "document_id": doc_id,
                        "source_file": str(pdf_path.relative_to(dataset_root)),
                        "page": page_no,
                        "text_raw": raw_text,
                        "text": normalized_text,
                        "char_count": len(normalized_text),
                        "file_sha256": file_sha,
                    }
                )

                table_records_for_page: list[dict[str, Any]] = []
                for table_no, table in enumerate(sorted(page.find_tables(), key=lambda t: (t.bbox[1], t.bbox[0])), 1):
                    table_id = f"{doc_id}:p{page_no}:table{table_no}"
                    raw_rows: list[list[str]] = []
                    normalized_rows: list[list[str]] = []
                    cells: list[dict[str, Any]] = []
                    table_rows = table.rows
                    headers = []
                    if table_rows:
                        headers = [cell_text(fixed_chars, bbox).replace("\n", "") for bbox in table_rows[0].cells]
                    for row_index, table_row in enumerate(table_rows):
                        raw_row: list[str] = []
                        normalized_row: list[str] = []
                        for col_index, bbox in enumerate(table_row.cells):
                            raw_cell = cell_text(raw_chars, bbox)
                            fixed_cell = cell_text(fixed_chars, bbox)
                            header_cell = row_index == 0
                            header = headers[col_index] if col_index < len(headers) else ""
                            id_like = header in {"Station", "Station ID", "Sensor", "Type", "Unit"}
                            normalized_cell, joined_no_space = normalize_cell(fixed_cell, header_cell, id_like)
                            raw_row.append(raw_cell)
                            normalized_row.append(normalized_cell)
                            if raw_cell != fixed_cell or joined_no_space or "R&D;" in fixed_cell:
                                glyph_fixes.append(
                                    {
                                        "document_id": doc_id,
                                        "page": page_no,
                                        "scope": "table_cell",
                                        "table_id": table_id,
                                        "row": row_index,
                                        "col": col_index,
                                        "before": raw_cell,
                                        "after": normalized_cell,
                                        "reason": "symbol/font normalization or split-cell merge",
                                    }
                                )
                            cells.append(
                                {
                                    "row": row_index,
                                    "col": col_index,
                                    "bbox": [round(x, 2) for x in bbox] if bbox else None,
                                    "text_raw": raw_cell,
                                    "text": normalized_cell,
                                }
                            )
                        raw_rows.append(raw_row)
                        normalized_rows.append(normalized_row)
                    record = {
                        "table_id": table_id,
                        "document_id": doc_id,
                        "source_file": str(pdf_path.relative_to(dataset_root)),
                        "page": page_no,
                        "bbox": [round(x, 2) for x in table.bbox],
                        "rows_raw": raw_rows,
                        "rows": normalized_rows,
                        "cells": cells,
                    }
                    tables.append(record)
                    table_records_for_page.append(record)

                # Chunk-level preview: multi-line rules, table chunks, and page text by section.
                lines = normalized_text.splitlines()
                i = 0
                while i < len(lines):
                    line = lines[i]
                    if HEADING_RE.match(line):
                        section = line
                        chunks.append({"chunk_id": f"{doc_id}:p{page_no}:text{len(chunks)+1}", "document_id": doc_id, "page": page_no, "kind": "text", "section": section, "text": line, "text_sha256": sha256_text(line), "source_file_sha256": file_sha})
                        i += 1
                        continue
                    rule_match = RULE_RE.match(line)
                    if rule_match:
                        rule_lines = [line]
                        j = i + 1
                        while j < len(lines) and not RULE_RE.match(lines[j]) and not HEADING_RE.match(lines[j]):
                            if lines[j].strip():
                                rule_lines.append(lines[j])
                            j += 1
                        text = " ".join(part.strip() for part in rule_lines if part.strip())
                        chunks.append({"chunk_id": f"{doc_id}:p{page_no}:{rule_match.group(1)}", "document_id": doc_id, "page": page_no, "kind": "rule", "section": section, "rule_id": rule_match.group(1), "text": text, "text_sha256": sha256_text(text), "source_file_sha256": file_sha})
                        i = j
                        continue
                    text_lines = [line]
                    j = i + 1
                    while j < len(lines) and not RULE_RE.match(lines[j]) and not HEADING_RE.match(lines[j]):
                        text_lines.append(lines[j])
                        j += 1
                    text = "\n".join(part for part in text_lines if part.strip()).strip()
                    if text:
                        chunks.append({"chunk_id": f"{doc_id}:p{page_no}:text{len(chunks)+1}", "document_id": doc_id, "page": page_no, "kind": "text", "section": section, "text": text, "text_sha256": sha256_text(text), "source_file_sha256": file_sha})
                    i = j
                for table_record in table_records_for_page:
                    table_text_lines = [f"[{table_record['table_id']}]", *["; ".join(row) for row in table_record["rows"]]]
                    table_text = "\n".join(table_text_lines)
                    chunks.append({"chunk_id": f"{table_record['table_id']}:chunk", "document_id": doc_id, "page": page_no, "kind": "table", "section": section, "table_id": table_record["table_id"], "bbox": table_record["bbox"], "text": table_text, "text_sha256": sha256_text(table_text), "source_file_sha256": file_sha})

    doc_dir = output_root / "documents"
    write_csv(doc_dir / "doc_manifest.csv", manifest, ["document_id", "source_file", "page_count", "file_sha256"])
    write_jsonl(doc_dir / "pages.jsonl", pages)
    write_jsonl(doc_dir / "tables.jsonl", tables)
    write_jsonl(doc_dir / "chunks.jsonl", chunks)
    write_csv(
        doc_dir / "glyph_fixes.csv",
        glyph_fixes,
        ["document_id", "page", "scope", "table_id", "row", "col", "char_index", "before", "after", "code", "font", "reason"],
    )
    write_json(doc_dir / "doc_profile.json", {"documents": len(manifest), "pages": len(pages), "tables": len(tables), "chunks": len(chunks), "glyph_fix_records": len(glyph_fixes), "warnings": warnings})
    add_audit(audit, "documents", "document_count", "PASS" if len(manifest) == 7 else "WARN", len(manifest))
    add_audit(audit, "documents", "page_count", "PASS" if len(pages) == 10 else "WARN", len(pages))
    add_audit(audit, "documents", "table_count", "PASS" if len(tables) == 24 else "WARN", len(tables))
    add_audit(audit, "documents", "glyph_fix_records", "WARN" if glyph_fixes else "PASS", len(glyph_fixes))
    return {"documents": len(manifest), "pages": len(pages), "tables": len(tables), "chunks": len(chunks), "glyph_fixes": len(glyph_fixes)}


def prepare_kg(dataset_root: Path, output_root: Path, audit: list[AuditRow], issues: list[Issue]) -> dict[str, Any]:
    _node_header, nodes = read_csv_rows(dataset_root / RAW_FILES["nodes"])
    _edge_header, edges = read_csv_rows(dataset_root / RAW_FILES["edges"])
    _factory_header, factory = read_csv_rows(dataset_root / RAW_FILES["nodes_factory"])
    _gt_header, ground_truth = read_csv_rows(dataset_root / RAW_FILES["ground_truth"])
    _raw_header, raw = read_csv_rows(dataset_root / RAW_FILES["timeseries_raw"])

    node_ids = [row["nodeId"] for row in nodes]
    node_by_id = {row["nodeId"]: row for row in nodes}
    duplicated_node_ids = sorted([node_id for node_id, count in Counter(node_ids).items() if count > 1])
    dangling_edges = [row for row in edges if row["fromId"] not in node_by_id or row["toId"] not in node_by_id]
    duplicate_edges = [row for row, count in Counter((e["fromId"], e["toId"], e["type"], e.get("ruleRef", "")) for e in edges).items() if count > 1]
    bidirectional = []
    edge_keys = {(row["fromId"], row["toId"], row["type"]) for row in edges}
    for row in edges:
        if (row["toId"], row["fromId"], row["type"]) in edge_keys and row["fromId"] < row["toId"]:
            bidirectional.append(row)

    raw_sensor_ids = {row["sensor_id"] for row in raw}
    sensor_nodes = [row for row in nodes if row["label"] == "Sensor"]
    sensor_node_names = {row["name"] for row in sensor_nodes}
    sensor_nodes_not_in_raw = sorted(sensor_node_names - raw_sensor_ids)
    raw_sensors_not_in_nodes = sorted(raw_sensor_ids - sensor_node_names)

    factory_sensor_names = {row["name"] for row in factory if row.get("label") == "Sensor"}
    factory_component_names = {row["name"] for row in factory if row.get("label") == "Component"}
    full_component_names = {row["name"] for row in nodes if row.get("label") == "Component"}
    factory_phantom_sensors = sorted(factory_sensor_names - raw_sensor_ids)
    factory_missing_sensors = sorted(raw_sensor_ids - factory_sensor_names)
    factory_missing_components = sorted(full_component_names - factory_component_names)
    factory_conflicts = []
    for row in factory:
        node_id = row.get("nodeId")
        if node_id in node_by_id and row.get("name") != node_by_id[node_id].get("name"):
            factory_conflicts.append({"nodeId": node_id, "nodes_name": node_by_id[node_id].get("name"), "factory_name": row.get("name")})

    static_nodes = [{key: value for key, value in row.items() if key not in LEAKAGE_NODE_FIELDS} for row in nodes if row["label"] in STATIC_KG_LABELS]
    static_ids = {row["nodeId"] for row in static_nodes}
    canonical_edges: list[dict[str, Any]] = []
    edge_lineage: list[dict[str, Any]] = []
    excluded_edges: list[dict[str, Any]] = []
    seen_canonical: dict[tuple[str, str, str, str], str] = {}
    for index, edge in enumerate(edges, start=2):
        if edge["fromId"] not in static_ids or edge["toId"] not in static_ids:
            excluded_edges.append({**edge, "source_row": index, "reason": "dynamic/evaluation endpoint"})
            continue
        from_id, to_id, edge_type = edge["fromId"], edge["toId"], edge["type"]
        if edge_type == "monitors":
            from_label = node_by_id[from_id]["label"]
            to_label = node_by_id[to_id]["label"]
            if from_label == "Sensor" and to_label == "Component":
                edge_type = "has_sensor"
            elif from_label == "Component" and to_label == "Sensor":
                from_id, to_id = to_id, from_id
                edge_type = "has_sensor"
        key = (from_id, to_id, edge_type, edge.get("ruleRef", ""))
        if key not in seen_canonical:
            seen_canonical[key] = f"E{len(canonical_edges)+1:04d}"
            canonical_edges.append({"edge_id": seen_canonical[key], "fromId": from_id, "toId": to_id, "type": edge_type, "ruleRef": edge.get("ruleRef", "")})
        edge_lineage.append({**edge, "source_row": index, "canonical_edge_id": seen_canonical[key]})

    anomaly_events = [row for row in nodes if row["label"] == "AnomalyEvent"]
    if anomaly_events:
        add_issue(
            issues,
            "LEAK-KG-ANOMALY-EVENTS",
            "kg",
            "HIGH",
            "Seed KG includes ground-truth AnomalyEvent nodes.",
            {"count": len(anomaly_events)},
            "Exclude from detection input static KG; preserve for event-level evaluation and final GraphRAG/Agent demos.",
            status="POLICY_APPLIED",
        )

    if factory_phantom_sensors or factory_missing_sensors or factory_missing_components or factory_conflicts:
        add_issue(
            issues,
            "KG-NODES-FACTORY-EXCLUDED",
            "kg",
            "HIGH",
            "`nodes_factory.csv` is an unreliable legacy draft.",
            {
                "phantom_sensors": factory_phantom_sensors,
                "missing_sensors_count": len(factory_missing_sensors),
                "missing_components": factory_missing_components,
                "node_id_conflicts": factory_conflicts,
            },
            "Exclude nodes_factory.csv from import paths; keep only as legacy/audit reference.",
            status="POLICY_APPLIED",
        )

    known_spd_review_rule_ids = {"RULE-ST04-03", "RULE-THR-ST03-SPD-CRIT", "RULE-THR-ST04-SPD-CRIT"}
    spd_rows = [row for row in ground_truth if row.get("ruleId") in known_spd_review_rule_ids]
    if spd_rows:
        add_issue(issues, "GT-SPD-ROWS-REVIEW", "ground_truth", "MEDIUM", "SPD-related ground_truth rows require review against SOP/raw threshold values.", {"rows": len(spd_rows)}, "Do not overwrite original; keep review in issue log.")

    add_audit(audit, "kg", "nodes_row_count", "PASS" if len(nodes) == EXPECTED_NODE_COUNT else "WARN", len(nodes))
    add_audit(audit, "kg", "edges_row_count", "PASS" if len(edges) == EXPECTED_EDGE_COUNT else "WARN", len(edges))
    add_audit(audit, "kg", "node_id_duplicates", "PASS" if not duplicated_node_ids else "FAIL", duplicated_node_ids)
    add_audit(audit, "kg", "dangling_edges", "PASS" if not dangling_edges else "FAIL", len(dangling_edges))
    add_audit(audit, "kg", "duplicate_edges", "PASS" if not duplicate_edges else "WARN", len(duplicate_edges))
    add_audit(audit, "kg", "bidirectional_edges", "WARN" if bidirectional else "PASS", len(bidirectional))
    add_audit(audit, "kg", "sensor_nodes_not_in_raw", "PASS" if not sensor_nodes_not_in_raw else "WARN", sensor_nodes_not_in_raw)
    add_audit(audit, "kg", "raw_sensors_not_in_nodes", "PASS" if not raw_sensors_not_in_nodes else "WARN", raw_sensors_not_in_nodes)

    kg_dir = output_root / "inputs" / "kg"
    audit_dir = output_root / "audit"
    evaluation_dir = output_root / "evaluation" / "kg"
    node_fields = sorted({key for row in static_nodes for key in row})
    write_csv(kg_dir / "nodes_static.csv", static_nodes, node_fields)
    write_csv(kg_dir / "edges_static.csv", canonical_edges, ["edge_id", "fromId", "toId", "type", "ruleRef"])
    write_csv(audit_dir / "edge_lineage.csv", edge_lineage, ["source_row", "fromId", "toId", "type", "ruleRef", "canonical_edge_id"])
    write_csv(audit_dir / "excluded_dynamic_edges.csv", excluded_edges, ["source_row", "fromId", "toId", "type", "ruleRef", "reason"])
    write_csv(evaluation_dir / "nodes_original.csv", nodes, list(nodes[0].keys()))
    write_csv(evaluation_dir / "edges_original.csv", edges, list(edges[0].keys()))
    write_csv(evaluation_dir / "excluded_dynamic_nodes.csv", [row for row in nodes if row["label"] not in STATIC_KG_LABELS], list(nodes[0].keys()))
    write_json(output_root / "metadata" / "graph_policy.json", {
        "nodes_source": "kg_seed/nodes.csv",
        "excluded_source": "kg_seed/nodes_factory.csv",
        "static_input_labels": sorted(STATIC_KG_LABELS),
        "evaluation_labels": sorted(EVALUATION_KG_LABELS),
        "anomaly_events": "Excluded from detection input; may be intentionally inserted for final GraphRAG/Agent demo.",
        "monitors_policy": "Canonical input edge is Sensor -> has_sensor -> Component.",
        "no_rdf_or_neo4j": "This preprocessing does not build RDF/TTL or load Neo4j.",
    })

    return {
        "nodes": len(nodes),
        "edges": len(edges),
        "static_nodes": len(static_nodes),
        "static_edges": len(canonical_edges),
        "dynamic_nodes": len(nodes) - len(static_nodes),
        "dynamic_edges": len(excluded_edges),
        "anomaly_events": len(anomaly_events),
        "nodes_factory_phantom_sensors": factory_phantom_sensors,
        "nodes_factory_missing_sensors_count": len(factory_missing_sensors),
        "nodes_factory_missing_components": factory_missing_components,
    }


def prepare_truth_and_human(dataset_root: Path, output_root: Path, audit: list[AuditRow], issues: list[Issue]) -> dict[str, Any]:
    _nodes_header, nodes = read_csv_rows(dataset_root / RAW_FILES["nodes"])
    _edges_header, edges = read_csv_rows(dataset_root / RAW_FILES["edges"])
    _raw_header, raw = read_csv_rows(dataset_root / RAW_FILES["timeseries_raw"])
    _ann_header, ann = read_csv_rows(dataset_root / RAW_FILES["timeseries_annotated"])
    _gt_header, ground_truth = read_csv_rows(dataset_root / RAW_FILES["ground_truth"])
    _access_header, access = read_csv_rows(dataset_root / RAW_FILES["access_events"])
    _response_header, responses = read_csv_rows(dataset_root / RAW_FILES["alarm_response_log"])
    _occupancy_header, occupancy = read_csv_rows(dataset_root / RAW_FILES["occupancy_timeseries"])
    _registry_header, registry = read_csv_rows(dataset_root / RAW_FILES["person_registry"])

    node_by_id = {row["nodeId"]: row for row in nodes}
    sensor_by_event_node = {}
    for edge in edges:
        if edge["type"] == "triggers" and edge["toId"] in node_by_id and node_by_id[edge["toId"]]["label"] == "AnomalyEvent":
            sensor_by_event_node[edge["toId"]] = node_by_id[edge["fromId"]]["name"]

    ann_by_key = {sensor_key(row): row for row in ann}
    event_rows = []
    for event in [row for row in nodes if row["label"] == "AnomalyEvent"]:
        sensor_id = sensor_by_event_node.get(event["nodeId"], "")
        start = event.get("startTs", "")
        end = event.get("endTs", "")
        matching = [
            row for row in raw
            if row["sensor_id"] == sensor_id and start <= row["timestamp"] <= end
        ]
        labelled = [ann_by_key[sensor_key(row)] for row in matching if sensor_key(row) in ann_by_key]
        severe = 0
        warning = 0
        for row in matching:
            value = to_float(row["value"])
            crit_hi = to_float(row["crit_hi"])
            crit_lo = to_float(row["crit_lo"])
            warn_hi = to_float(row["warn_hi"])
            warn_lo = to_float(row["warn_lo"])
            if None in {value, crit_hi, crit_lo, warn_hi, warn_lo}:
                continue
            if value > crit_hi or value < crit_lo:
                severe += 1
            elif value > warn_hi or value < warn_lo:
                warning += 1
        rule_severity = "CRITICAL" if severe else ("WARNING" if warning else "NORMAL")
        event_rows.append({
            "event_id": event.get("gtId", ""),
            "node_id": event["nodeId"],
            "sensor_id": sensor_id,
            "start": start,
            "end": end,
            "anomaly_type": event.get("anomalyType", ""),
            "dataset_severity": event.get("severity", ""),
            "rule_severity": rule_severity,
            "severity_conflict": str(event.get("severity", "") != rule_severity),
            "critical_rows": severe,
            "warning_rows": warning,
            "event_rows": len(matching),
            "label_rows": len(labelled),
            "split": split_name(start) if start else "",
        })

    evaluation_dir = output_root / "evaluation"
    audit_dir = output_root / "audit"
    write_csv(evaluation_dir / "anomaly_events.csv", event_rows, ["event_id", "node_id", "sensor_id", "start", "end", "anomaly_type", "dataset_severity", "rule_severity", "severity_conflict", "critical_rows", "warning_rows", "event_rows", "label_rows", "split"])
    write_csv(evaluation_dir / "rules_ground_truth_original.csv", ground_truth, list(ground_truth[0].keys()))
    write_csv(audit_dir / "severity_conflicts.csv", [row for row in event_rows if row["severity_conflict"] == "True"], ["event_id", "sensor_id", "dataset_severity", "rule_severity", "critical_rows", "warning_rows"])

    raw_times = [parse_time(row["timestamp"]) for row in raw]
    start_time, end_time = min(raw_times), max(raw_times)
    access_in_range = []
    access_outside_range = []
    unknown_access = []
    registry_people = {row["person_id"] for row in registry}
    for row in access:
        ts = parse_time(row["timestamp"])
        out = dict(row)
        out["in_sensor_range"] = str(start_time <= ts <= end_time)
        out["person_resolution"] = "unknown" if row["person_id"] == "UNKNOWN" else ("registered" if row["person_id"] in registry_people else "missing_registry")
        if row["person_id"] == "UNKNOWN":
            unknown_access.append(out)
        if start_time <= ts <= end_time:
            access_in_range.append(out)
        else:
            access_outside_range.append(out)
    write_csv(evaluation_dir / "human" / "access_in_sensor_range.csv", access_in_range, list(access_in_range[0].keys()) if access_in_range else list(access[0].keys()) + ["in_sensor_range", "person_resolution"])
    write_csv(evaluation_dir / "human" / "access_outside_sensor_range.csv", access_outside_range, list(access_outside_range[0].keys()) if access_outside_range else list(access[0].keys()) + ["in_sensor_range", "person_resolution"])
    write_csv(audit_dir / "unknown_access_events.csv", unknown_access, list(unknown_access[0].keys()) if unknown_access else list(access[0].keys()) + ["in_sensor_range", "person_resolution"])

    invalid_sop = [row for row in responses if "SOP-001 §5" in row.get("action_taken", "")]
    reviewed_responses = []
    for row in responses:
        reviewed = dict(row)
        reviewed["action_taken_policy"] = "not_corrective_action_ground_truth"
        reviewed["sop_reference_status"] = "invalid_section" if "SOP-001 §5" in row.get("action_taken", "") else "unverified_free_text"
        reviewed_responses.append(reviewed)
    write_csv(evaluation_dir / "human" / "alarm_response_log_reviewed.csv", reviewed_responses, list(reviewed_responses[0].keys()))
    write_csv(audit_dir / "invalid_sop_references.csv", invalid_sop, list(responses[0].keys()))

    if invalid_sop:
        add_issue(issues, "HUMAN-INVALID-SOP-REFERENCE", "human", "MEDIUM", "alarm_response_log contains invalid SOP section references.", {"count": len(invalid_sop)}, "Do not use action_taken as corrective-action ground truth.")
    if unknown_access:
        add_issue(issues, "HUMAN-UNKNOWN-ACCESS", "human", "LOW", "access_events contains UNKNOWN person IDs.", {"count": len(unknown_access)}, "Preserve as unresolved actor; do not invent identity.")

    occupancy_labels = Counter(row.get("occupancy_anomaly", "") for row in occupancy)
    csi_gestures = Counter(row.get("csi_gesture", "") for row in occupancy)
    add_audit(audit, "human", "access_outside_sensor_range", "WARN" if access_outside_range else "PASS", len(access_outside_range))
    add_audit(audit, "human", "unknown_access_events", "WARN" if unknown_access else "PASS", len(unknown_access))
    add_audit(audit, "human", "occupancy_anomaly_counts", "WARN", dict(occupancy_labels))
    add_audit(audit, "human", "csi_gesture_counts", "WARN", dict(csi_gestures))
    add_issue(
        issues,
        "HUMAN-LABEL-LIKE-COLUMNS",
        "human",
        "MEDIUM",
        "occupancy_anomaly, oc_severity, and csi_gesture are label-like for safety/CSI work.",
        {"occupancy_anomaly": dict(occupancy_labels), "csi_gesture": dict(csi_gestures)},
        "Exclude from safety/CSI detector input unless used as explicit evaluation labels.",
        status="POLICY_APPLIED",
    )

    csi_files = sorted((dataset_root / "csi").rglob("*.csv"))
    subjects = sorted({path.parent.name for path in csi_files})
    write_csv(output_root / "metadata" / "csi_manifest.csv", ({"path": str(path.relative_to(dataset_root)), "subject": path.parent.name, "file": path.name} for path in csi_files), ["path", "subject", "file"])
    add_audit(audit, "human", "csi_file_count", "PASS" if csi_files else "WARN", len(csi_files))

    return {
        "anomaly_events": len(event_rows),
        "ground_truth_rules": len(ground_truth),
        "severity_conflicts": len([row for row in event_rows if row["severity_conflict"] == "True"]),
        "access_in_range": len(access_in_range),
        "access_outside_range": len(access_outside_range),
        "unknown_access": len(unknown_access),
        "invalid_sop_references": len(invalid_sop),
        "csi_files": len(csi_files),
        "csi_subjects": len(subjects),
    }


def write_audit_files(output_root: Path, audit: list[AuditRow], issues: list[Issue]) -> None:
    write_csv(output_root / "audit" / "preprocessing_audit.csv", (asdict(row) for row in audit), ["area", "check", "status", "observed", "details"])
    write_csv(output_root / "audit" / "preprocessing_issues.csv", (asdict(issue) for issue in issues), ["issue_id", "area", "severity", "status", "description", "evidence", "policy_or_action"])


def input_file_metadata(dataset_root: Path) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for path in sorted(dataset_root.rglob("*")):
        if path.is_file() and path.name != ".DS_Store":
            rel = str(path.relative_to(dataset_root))
            metadata[rel] = {"bytes": path.stat().st_size, "sha256": sha256_file(path)}
    return metadata


def validate_outputs(output_root: Path) -> list[str]:
    errors: list[str] = []
    required = [
        output_root / "inputs" / "sensors" / "timeseries_ml_input.csv",
        output_root / "inputs" / "sensors" / "timeseries_rule_input.csv",
        output_root / "inputs" / "sensors" / "mqtt_stream_input.jsonl",
        output_root / "inputs" / "kg" / "nodes_static.csv",
        output_root / "inputs" / "kg" / "edges_static.csv",
        output_root / "evaluation" / "row_labels.csv",
        output_root / "evaluation" / "anomaly_events.csv",
        output_root / "documents" / "doc_manifest.csv",
        output_root / "documents" / "pages.jsonl",
        output_root / "documents" / "tables.jsonl",
        output_root / "documents" / "chunks.jsonl",
        output_root / "audit" / "preprocessing_issues.csv",
    ]
    for path in required:
        if not path.exists():
            errors.append(f"Missing output: {path}")

    ml_path = output_root / "inputs" / "sensors" / "timeseries_ml_input.csv"
    if ml_path.exists():
        header, rows = read_csv_rows(ml_path)
        if header != OBSERVATION_COLUMNS:
            errors.append(f"ML input header differs from allowlist: {header}")
        forbidden = FORBIDDEN_INPUT_COLUMNS & set(header)
        if forbidden:
            errors.append(f"Forbidden leakage columns in ML input: {sorted(forbidden)}")
        if len(rows) != EXPECTED_SENSOR_ROWS:
            errors.append(f"ML row count differs: {len(rows)}")

    rule_path = output_root / "inputs" / "sensors" / "timeseries_rule_input.csv"
    if rule_path.exists():
        header, rows = read_csv_rows(rule_path)
        if header != OBSERVATION_COLUMNS + THRESHOLD_COLUMNS:
            errors.append(f"Rule input header differs: {header}")
        if QUALITY_COLUMN in header or set(ANNOTATED_LABEL_COLUMNS) & set(header):
            errors.append("Rule input contains quality or annotated labels.")
        if len(rows) != EXPECTED_SENSOR_ROWS:
            errors.append(f"Rule row count differs: {len(rows)}")

    mqtt_path = output_root / "inputs" / "sensors" / "mqtt_stream_input.jsonl"
    if mqtt_path.exists():
        with mqtt_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                payload = json.loads(line)
                if "status" in payload or "alarms" in payload:
                    errors.append(f"MQTT forbidden top-level key at line {line_no}")
                    break
                for reading in payload.get("readings", {}).values():
                    if isinstance(reading, dict) and "quality" in reading:
                        errors.append(f"MQTT nested quality at line {line_no}")
                        break

    nodes_path = output_root / "inputs" / "kg" / "nodes_static.csv"
    if nodes_path.exists():
        _header, rows = read_csv_rows(nodes_path)
        bad_labels = [row["label"] for row in rows if row.get("label") not in STATIC_KG_LABELS]
        if bad_labels:
            errors.append(f"Static KG contains dynamic labels: {sorted(set(bad_labels))}")
        forbidden_fields = LEAKAGE_NODE_FIELDS & set(_header)
        if forbidden_fields:
            errors.append(f"Static KG node header contains leakage fields: {sorted(forbidden_fields)}")

    return errors


def run_preprocessing(dataset_root: Path, output_root: Path) -> dict[str, Any]:
    validate_raw_files(dataset_root)
    audit: list[AuditRow] = []
    issues: list[Issue] = []

    sensor_summary = prepare_sensors(dataset_root, output_root, audit, issues)
    mqtt_summary = sanitize_mqtt(dataset_root, output_root, audit, issues)
    document_summary = extract_documents(dataset_root, output_root, audit, issues)
    kg_summary = prepare_kg(dataset_root, output_root, audit, issues)
    truth_human_summary = prepare_truth_and_human(dataset_root, output_root, audit, issues)
    write_audit_files(output_root, audit, issues)

    validation_errors = validate_outputs(output_root)
    summary = {
        "status": "PASS" if not validation_errors else "FAIL",
        "sensor_summary": sensor_summary,
        "mqtt_summary": mqtt_summary,
        "document_summary": document_summary,
        "kg_summary": kg_summary,
        "truth_human_summary": truth_human_summary,
        "validation_errors": validation_errors,
        "issue_count": len(issues),
        "audit_count": len(audit),
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "preprocessing final candidate; no normalization, windowing, embedding, RDF/Neo4j load, GraphRAG, or Agent implementation",
    }
    write_json(output_root / "summary.json", summary)
    output_hashes = {
        str(path.relative_to(output_root)): sha256_file(path)
        for path in sorted(output_root.rglob("*"))
        if path.is_file() and path.name != "manifest.json"
    }
    write_json(output_root / "manifest.json", {"source_files": input_file_metadata(dataset_root), "output_files_sha256": output_hashes})
    if validation_errors:
        raise RuntimeError(f"Validation failed: {validation_errors}")
    return summary


def main() -> int:
    args = parse_args()
    dataset_root = args.dataset_root.resolve()
    output_root = args.output_root.resolve()
    if args.validate_only:
        errors = validate_outputs(output_root)
        if errors:
            print(json.dumps({"status": "FAIL", "errors": errors}, ensure_ascii=False, indent=2))
            return 1
        print(json.dumps({"status": "PASS", "output_root": str(output_root)}, ensure_ascii=False, indent=2))
        return 0
    ensure_dir(output_root)
    summary = run_preprocessing(dataset_root, output_root)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
