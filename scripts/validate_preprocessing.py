#!/usr/bin/env python3
"""Preprocess and validate the iMAKS manufacturing dataset.

This script intentionally stays within the preprocessing scope:
- verify raw data structure and known leakage paths
- create clean detection inputs and separated evaluation labels
- preserve SOP/datasheet source/page/table-like text for later ontology work
- audit the provided KG seed as reference data, not as the final KG

It does not perform feature engineering, windowing, embedding, triple extraction,
RDF/Neo4j conversion, or GraphRAG work.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import re
import shutil
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


LOGGER = logging.getLogger("preprocessing")

SENSOR_LEAKAGE_COLUMNS = {
    "quality",
    "nominal",
    "warn_hi",
    "crit_hi",
    "warn_lo",
    "crit_lo",
    "anomaly_label",
    "severity",
    "alarm_flag",
}

RAW_LEAKAGE_COLUMNS = {
    "quality",
    "nominal",
    "warn_hi",
    "crit_hi",
    "warn_lo",
    "crit_lo",
}

ANNOTATED_LABEL_COLUMNS = {"anomaly_label", "severity", "alarm_flag"}
THRESHOLD_COLUMNS = ["nominal", "warn_hi", "crit_hi", "warn_lo", "crit_lo"]
EXPECTED_NODE_COUNT = 115
EXPECTED_EDGE_COUNT = 341

REQUIRED_DATASET_FILES = {
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

DOCUMENT_FILES = [
    Path("rules/SOP_001_OperatingProcedures.pdf"),
    Path("rules/SOP_002_AlarmThresholds.pdf"),
    Path("rules/SOP_003_MaintenanceRules.pdf"),
    Path("rules/SOP_004_PersonnelZoneAccess.pdf"),
    Path("datasheets/DS_Electrical_Sensors.pdf"),
    Path("datasheets/DS_Mechanical_Sensors.pdf"),
    Path("datasheets/DS_Thermal_Sensors.pdf"),
]


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
    parser = argparse.ArgumentParser(
        description="Run scoped preprocessing for the manufacturing GraphRAG dataset."
    )
    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=Path("../iMAKS_dataset"),
        help="Path to the raw iMAKS_dataset directory. Default: ../iMAKS_dataset",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("processed"),
        help="Directory for generated preprocessing outputs. Default: processed",
    )
    parser.add_argument(
        "--validate-only",
        action="store_true",
        help="Validate existing outputs without regenerating them.",
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level.",
    )
    return parser.parse_args()


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=getattr(logging, level),
        format="%(levelname)s: %(message)s",
    )


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        return list(csv.DictReader(handle))


def read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        return next(reader)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str]) -> int:
    ensure_dir(path.parent)
    count = 0
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
            count += 1
    return count


def write_json(path: Path, payload: dict[str, Any]) -> None:
    ensure_dir(path.parent)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
        handle.write("\n")


def append_issue(
    issues: list[Issue],
    issue_id: str,
    area: str,
    severity: str,
    status: str,
    description: str,
    evidence: str,
    policy_or_action: str,
) -> None:
    issues.append(
        Issue(
            issue_id=issue_id,
            area=area,
            severity=severity,
            status=status,
            description=description,
            evidence=evidence,
            policy_or_action=policy_or_action,
        )
    )


def add_audit(
    audit_rows: list[AuditRow],
    area: str,
    check: str,
    status: str,
    observed: Any,
    details: str = "",
) -> None:
    audit_rows.append(
        AuditRow(
            area=area,
            check=check,
            status=status,
            observed=str(observed),
            details=details,
        )
    )


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def to_float(value: str) -> float | None:
    if value == "" or value is None:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def validate_dataset_files(dataset_root: Path) -> dict[str, Path]:
    paths = {name: dataset_root / rel for name, rel in REQUIRED_DATASET_FILES.items()}
    for document in DOCUMENT_FILES:
        paths[document.stem] = dataset_root / document

    missing = [str(path) for path in paths.values() if not path.exists()]
    if missing:
        raise FileNotFoundError("Missing required dataset files:\n" + "\n".join(missing))
    return paths


def split_station_from_sensor(sensor_id: str, sensor_type: str) -> str:
    suffix = f"_{sensor_type}"
    if sensor_id.endswith(suffix):
        return sensor_id[: -len(suffix)]
    return ""


def analyze_sensor_timeseries(
    raw_rows: list[dict[str, str]],
    annotated_rows: list[dict[str, str]],
    issues: list[Issue],
    audit_rows: list[AuditRow],
) -> dict[str, Any]:
    raw_header = set(raw_rows[0]) if raw_rows else set()
    annotated_header = set(annotated_rows[0]) if annotated_rows else set()

    add_audit(audit_rows, "sensors", "raw_row_count", "PASS", len(raw_rows))
    add_audit(audit_rows, "sensors", "annotated_row_count", "PASS", len(annotated_rows))

    duplicate_keys = 0
    seen_keys: set[tuple[str, str]] = set()
    bad_timestamps = 0
    parsed_timestamps: list[datetime] = []
    missing_by_column: Counter[str] = Counter()
    sensor_units: dict[str, set[str]] = defaultdict(set)
    sensor_types: dict[str, set[str]] = defaultdict(set)
    sensor_station_mismatch = 0
    numeric_columns = ["value", "nominal", "warn_hi", "crit_hi", "warn_lo", "crit_lo"]
    bad_numeric: Counter[str] = Counter()

    for row in raw_rows:
        key = (row.get("timestamp", ""), row.get("sensor_id", ""))
        if key in seen_keys:
            duplicate_keys += 1
        seen_keys.add(key)

        try:
            parsed_timestamps.append(parse_timestamp(row.get("timestamp", "")))
        except ValueError:
            bad_timestamps += 1

        for column, value in row.items():
            if value == "":
                missing_by_column[column] += 1

        sensor_type = row.get("sensor_type", "")
        sensor_units[sensor_type].add(row.get("unit", ""))
        sensor_types[row.get("sensor_id", "")].add(sensor_type)
        expected_station = split_station_from_sensor(row.get("sensor_id", ""), sensor_type)
        if expected_station and expected_station != row.get("station_id", ""):
            sensor_station_mismatch += 1
        if not expected_station:
            sensor_station_mismatch += 1

        for column in numeric_columns:
            if to_float(row.get(column, "")) is None:
                bad_numeric[column] += 1

    globally_sorted = all(
        parsed_timestamps[idx] <= parsed_timestamps[idx + 1]
        for idx in range(len(parsed_timestamps) - 1)
    )
    add_audit(audit_rows, "sensors", "timestamp_parse_errors", "PASS" if bad_timestamps == 0 else "FAIL", bad_timestamps)
    add_audit(audit_rows, "sensors", "timestamp_global_order", "PASS" if globally_sorted else "FAIL", globally_sorted)
    add_audit(audit_rows, "sensors", "timestamp_sensor_id_duplicates", "PASS" if duplicate_keys == 0 else "FAIL", duplicate_keys)
    add_audit(audit_rows, "sensors", "missing_values", "PASS" if not missing_by_column else "WARN", dict(missing_by_column))
    add_audit(audit_rows, "sensors", "numeric_parse_errors", "PASS" if not bad_numeric else "FAIL", dict(bad_numeric))
    add_audit(audit_rows, "sensors", "sensor_id_structure", "PASS" if sensor_station_mismatch == 0 else "FAIL", sensor_station_mismatch)

    inconsistent_units = {
        sensor_type: sorted(units)
        for sensor_type, units in sensor_units.items()
        if len(units) != 1
    }
    add_audit(
        audit_rows,
        "sensors",
        "sensor_type_unit_consistency",
        "PASS" if not inconsistent_units else "FAIL",
        {key: sorted(value) for key, value in sensor_units.items()},
        json.dumps(inconsistent_units, ensure_ascii=False),
    )

    sampling_gaps: Counter[float] = Counter()
    timestamps_by_sensor: dict[str, list[datetime]] = defaultdict(list)
    for row in raw_rows:
        try:
            timestamps_by_sensor[row["sensor_id"]].append(parse_timestamp(row["timestamp"]))
        except ValueError:
            continue
    sensors_with_bad_interval: dict[str, dict[str, int]] = {}
    for sensor_id, values in timestamps_by_sensor.items():
        values.sort()
        sensor_gaps = Counter(
            (values[idx] - values[idx - 1]).total_seconds()
            for idx in range(1, len(values))
        )
        sampling_gaps.update(sensor_gaps)
        if set(sensor_gaps) != {30.0}:
            sensors_with_bad_interval[sensor_id] = {
                str(gap): count for gap, count in sorted(sensor_gaps.items())
            }
    add_audit(
        audit_rows,
        "sensors",
        "sensor_sampling_interval_seconds",
        "PASS" if not sensors_with_bad_interval else "FAIL",
        dict(sorted(sampling_gaps.items())),
        json.dumps(sensors_with_bad_interval, ensure_ascii=False),
    )

    raw_sensor_ids = sorted(timestamps_by_sensor)
    label_counts = Counter(row.get("anomaly_label", "") for row in annotated_rows)
    severity_counts = Counter(row.get("severity", "") for row in annotated_rows)
    alarm_flag_counts = Counter(row.get("alarm_flag", "") for row in annotated_rows)
    quality_vs_label: Counter[tuple[str, str]] = Counter()
    for row in annotated_rows:
        quality_vs_label[(row.get("quality", ""), row.get("anomaly_label", ""))] += 1

    uncertain_stuck = quality_vs_label.get(("UNCERTAIN", "STUCK"), 0)
    uncertain_total = sum(count for (quality, _), count in quality_vs_label.items() if quality == "UNCERTAIN")
    if uncertain_total:
        append_issue(
            issues,
            "ISSUE-LEAK-QUALITY",
            "sensors",
            "high",
            "recorded",
            "`quality=UNCERTAIN` aligns with STUCK labels and must not be used as detection input.",
            f"UNCERTAIN total={uncertain_total}, UNCERTAIN/STUCK={uncertain_stuck}",
            "Drop `quality` from clean detection input; preserve raw data.",
        )

    threshold_detection: dict[str, dict[str, Any]] = {}
    for label in ["OUT_OF_RANGE", "SPIKE", "DRIFT", "STUCK", "CORRELATED"]:
        label_rows = [row for row in annotated_rows if row.get("anomaly_label") == label]
        caught = 0
        for row in label_rows:
            value = to_float(row.get("value", ""))
            warn_hi = to_float(row.get("warn_hi", ""))
            crit_hi = to_float(row.get("crit_hi", ""))
            warn_lo = to_float(row.get("warn_lo", ""))
            crit_lo = to_float(row.get("crit_lo", ""))
            if None in {value, warn_hi, crit_hi, warn_lo, crit_lo}:
                continue
            if value > crit_hi or value > warn_hi or value < crit_lo or value < warn_lo:
                caught += 1
        threshold_detection[label] = {
            "caught": caught,
            "total": len(label_rows),
            "ratio": round(caught / len(label_rows), 4) if label_rows else None,
        }
    append_issue(
        issues,
        "ISSUE-LEAK-THRESHOLD",
        "sensors",
        "medium",
        "recorded",
        "Threshold columns are operational prior knowledge, not labels, but are separated from clean ML input to compare pattern-based detection with rule-based detection.",
        json.dumps(threshold_detection, ensure_ascii=False),
        "Drop threshold columns from clean detection input; preserve them in rule reference output.",
    )

    forbidden_in_raw = sorted(RAW_LEAKAGE_COLUMNS & raw_header)
    forbidden_in_annotated = sorted(ANNOTATED_LABEL_COLUMNS & annotated_header)
    add_audit(audit_rows, "sensors", "raw_leakage_columns_present", "WARN", forbidden_in_raw)
    add_audit(audit_rows, "sensors", "annotated_label_columns_present", "WARN", forbidden_in_annotated)

    return {
        "raw_row_count": len(raw_rows),
        "annotated_row_count": len(annotated_rows),
        "raw_sensor_ids": raw_sensor_ids,
        "label_counts": dict(label_counts),
        "severity_counts": dict(severity_counts),
        "alarm_flag_counts": dict(alarm_flag_counts),
        "quality_vs_label": {f"{quality}|{label}": count for (quality, label), count in quality_vs_label.items()},
        "threshold_detection": threshold_detection,
    }


def write_sensor_outputs(
    raw_rows: list[dict[str, str]],
    annotated_rows: list[dict[str, str]],
    output_root: Path,
) -> dict[str, int]:
    sensor_dir = output_root / "sensors"
    clean_columns = [column for column in raw_rows[0].keys() if column not in RAW_LEAKAGE_COLUMNS]
    clean_count = write_csv(
        sensor_dir / "timeseries_input_clean.csv",
        ({column: row.get(column, "") for column in clean_columns} for row in raw_rows),
        clean_columns,
    )

    eval_columns = [
        "timestamp",
        "sensor_id",
        "station_id",
        "sensor_type",
        "anomaly_label",
        "severity",
        "alarm_flag",
    ]
    eval_count = write_csv(
        sensor_dir / "timeseries_eval_labels.csv",
        ({column: row.get(column, "") for column in eval_columns} for row in annotated_rows),
        eval_columns,
    )

    rule_columns = [
        "timestamp",
        "day",
        "shift",
        "batch_id",
        "zone",
        "station_id",
        "sensor_id",
        "sensor_type",
        "value",
        "unit",
        *THRESHOLD_COLUMNS,
    ]
    rule_count = write_csv(
        sensor_dir / "timeseries_rule_reference.csv",
        ({column: row.get(column, "") for column in rule_columns} for row in raw_rows),
        rule_columns,
    )

    return {
        "timeseries_input_clean": clean_count,
        "timeseries_eval_labels": eval_count,
        "timeseries_rule_reference": rule_count,
    }


def sanitize_mqtt_payloads(
    mqtt_path: Path,
    output_root: Path,
    issues: list[Issue],
    audit_rows: list[AuditRow],
) -> dict[str, Any]:
    with mqtt_path.open("r", encoding="utf-8") as handle:
        payloads = json.load(handle)
    if not isinstance(payloads, list):
        raise ValueError(f"Expected MQTT payload list in {mqtt_path}")

    output_path = output_root / "sensors" / "mqtt_input_stream.jsonl"
    ensure_dir(output_path.parent)
    status_counts: Counter[str] = Counter()
    alarm_payloads = 0
    reading_quality_counts: Counter[str] = Counter()

    with output_path.open("w", encoding="utf-8") as handle:
        for payload in payloads:
            status_counts[str(payload.get("status", ""))] += 1
            if payload.get("alarms"):
                alarm_payloads += 1

            sanitized = dict(payload)
            sanitized.pop("status", None)
            sanitized.pop("alarms", None)
            for reading in sanitized.get("readings", {}).values():
                if isinstance(reading, dict) and "quality" in reading:
                    reading_quality_counts[str(reading.get("quality", ""))] += 1
                    reading.pop("quality", None)
            handle.write(json.dumps(sanitized, ensure_ascii=False, sort_keys=True) + "\n")

    add_audit(audit_rows, "mqtt", "payload_count", "PASS", len(payloads))
    add_audit(audit_rows, "mqtt", "status_counts_original", "WARN", dict(status_counts))
    add_audit(audit_rows, "mqtt", "alarm_payloads_original", "WARN", alarm_payloads)
    add_audit(audit_rows, "mqtt", "nested_reading_quality_removed", "WARN", dict(reading_quality_counts))
    append_issue(
        issues,
        "ISSUE-LEAK-MQTT",
        "mqtt",
        "high",
        "recorded",
        "MQTT `status` and `alarms` expose alarm state/type/severity; nested reading `quality` is also removed from input stream.",
        f"status_counts={dict(status_counts)}, alarm_payloads={alarm_payloads}, reading_quality={dict(reading_quality_counts)}",
        "Write sanitized JSONL without `status`, `alarms`, alarm messages, or nested reading `quality`.",
    )

    return {
        "mqtt_payload_count": len(payloads),
        "status_counts_original": dict(status_counts),
        "alarm_payloads_original": alarm_payloads,
        "nested_reading_quality_counts_original": dict(reading_quality_counts),
    }


def run_command(command: list[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return result.stdout


def pdf_page_count(path: Path) -> int:
    if shutil.which("pdfinfo"):
        output = run_command(["pdfinfo", str(path)])
        for line in output.splitlines():
            if line.startswith("Pages:"):
                return int(line.split(":", 1)[1].strip())
    try:
        from pypdf import PdfReader  # type: ignore

        return len(PdfReader(str(path)).pages)
    except Exception as exc:  # pragma: no cover - only used without poppler/pypdf
        raise RuntimeError(f"Cannot determine page count for {path}: {exc}") from exc


def extract_pdf_page_text(path: Path, page: int) -> str:
    if shutil.which("pdftotext"):
        return run_command(["pdftotext", "-layout", "-f", str(page), "-l", str(page), str(path), "-"])
    try:
        from pypdf import PdfReader  # type: ignore

        text = PdfReader(str(path)).pages[page - 1].extract_text() or ""
        return text
    except Exception as exc:  # pragma: no cover - only used without poppler/pypdf
        raise RuntimeError(f"Cannot extract text from {path} page {page}: {exc}") from exc


def document_id_from_path(path: Path) -> str:
    name = path.stem
    if name.startswith("SOP_"):
        return name.replace("_", "-", 1).split("_", 1)[0]
    if name.startswith("DS_"):
        parts = name.split("_")
        return f"DS-{parts[1].upper()}" if len(parts) > 1 else name
    return name


def guess_section_title(text: str) -> str:
    for line in text.splitlines():
        clean = line.strip()
        if not clean:
            continue
        if len(clean) <= 120:
            return clean
    return ""


def extract_table_like_rows(text: str) -> list[str]:
    table_rows: list[str] = []
    for line in text.splitlines():
        stripped = line.rstrip()
        if not stripped.strip():
            continue
        has_multi_space = bool(re.search(r"\S\s{2,}\S", stripped))
        has_threshold_or_unit = bool(re.search(r"(°C|%RH|bar|m/s|mm/s|L/min|pcs/min| A\b| min\b|>|<)", stripped))
        if has_multi_space and has_threshold_or_unit:
            table_rows.append(stripped)
    return table_rows[:80]


def document_token_checks(text: str) -> dict[str, bool]:
    return {
        "has_greater_than": ">" in text,
        "has_less_than": "<" in text,
        "has_celsius": "°C" in text,
        "has_ampere": bool(re.search(r"\bA\b", text)),
        "has_min": bool(re.search(r"\bmin\b", text, flags=re.IGNORECASE)),
        "has_numeric": bool(re.search(r"\d", text)),
    }


def extract_documents(
    dataset_root: Path,
    output_root: Path,
    audit_rows: list[AuditRow],
    issues: list[Issue],
) -> dict[str, Any]:
    document_index_path = output_root / "documents" / "document_index.csv"
    preview_path = output_root / "documents" / "document_extraction_preview.jsonl"
    ensure_dir(document_index_path.parent)

    index_rows: list[dict[str, Any]] = []
    preview_count = 0
    documents_with_text = 0
    extraction_tool = "pdftotext" if shutil.which("pdftotext") else "pypdf"

    with preview_path.open("w", encoding="utf-8") as preview:
        for relative_path in DOCUMENT_FILES:
            pdf_path = dataset_root / relative_path
            document_id = document_id_from_path(pdf_path)
            pages = pdf_page_count(pdf_path)
            index_rows.append(
                {
                    "document_id": document_id,
                    "source_file": str(relative_path),
                    "page_count": pages,
                    "file_sha256": sha256_file(pdf_path),
                }
            )
            for page in range(1, pages + 1):
                text = extract_pdf_page_text(pdf_path, page)
                if text.strip():
                    documents_with_text += 1
                record = {
                    "document_id": document_id,
                    "source_file": str(relative_path),
                    "page": page,
                    "extraction_order": preview_count + 1,
                    "section_title": guess_section_title(text),
                    "text": text.strip(),
                    "table_rows": extract_table_like_rows(text),
                    "token_checks": document_token_checks(text),
                }
                preview.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
                preview_count += 1

    write_csv(
        document_index_path,
        index_rows,
        ["document_id", "source_file", "page_count", "file_sha256"],
    )
    add_audit(audit_rows, "documents", "document_count", "PASS", len(index_rows))
    add_audit(audit_rows, "documents", "page_records_extracted", "PASS", preview_count)
    add_audit(audit_rows, "documents", "pdf_extraction_tool", "PASS", extraction_tool)
    if documents_with_text != preview_count:
        append_issue(
            issues,
            "ISSUE-DOC-EXTRACT",
            "documents",
            "medium",
            "recorded",
            "Some PDF pages produced empty text during extraction.",
            f"text_pages={documents_with_text}, total_pages={preview_count}",
            "Preserve source/page records and review extraction before LLM extraction.",
        )
    return {
        "document_count": len(index_rows),
        "page_records": preview_count,
        "extraction_tool": extraction_tool,
    }


def analyze_kg_reference(
    dataset_root: Path,
    raw_sensor_ids: set[str],
    issues: list[Issue],
    audit_rows: list[AuditRow],
) -> dict[str, Any]:
    nodes = read_csv_rows(dataset_root / REQUIRED_DATASET_FILES["nodes"])
    edges = read_csv_rows(dataset_root / REQUIRED_DATASET_FILES["edges"])
    ground_truth = read_csv_rows(dataset_root / REQUIRED_DATASET_FILES["ground_truth"])
    nodes_factory = read_csv_rows(dataset_root / REQUIRED_DATASET_FILES["nodes_factory"])

    node_ids = [row.get("nodeId", "") for row in nodes]
    node_id_counts = Counter(node_ids)
    duplicated_node_ids = sorted(node_id for node_id, count in node_id_counts.items() if count > 1)
    node_id_set = set(node_ids)

    label_counts = Counter(row.get("label", "") for row in nodes)
    edge_type_counts = Counter(row.get("type", "") for row in edges)
    edge_tuples = [
        (row.get("fromId", ""), row.get("toId", ""), row.get("type", ""), row.get("ruleRef", ""))
        for row in edges
    ]
    duplicate_edges = [edge for edge, count in Counter(edge_tuples).items() if count > 1]
    dangling_edges = [
        edge
        for edge in edges
        if edge.get("fromId", "") not in node_id_set or edge.get("toId", "") not in node_id_set
    ]

    by_type_pairs: dict[str, set[tuple[str, str]]] = defaultdict(set)
    bidirectional_edges: list[tuple[str, str, str]] = []
    for row in edges:
        edge_type = row.get("type", "")
        source = row.get("fromId", "")
        target = row.get("toId", "")
        if (target, source) in by_type_pairs[edge_type]:
            bidirectional_edges.append((target, source, edge_type))
        by_type_pairs[edge_type].add((source, target))

    sensor_nodes = [row for row in nodes if row.get("label") == "Sensor"]
    sensor_node_names = {row.get("name", "") for row in sensor_nodes}
    sensor_nodes_not_in_raw = sorted(sensor_node_names - raw_sensor_ids)
    raw_sensors_not_in_nodes = sorted(raw_sensor_ids - sensor_node_names)

    factory_sensor_names = {
        row.get("name", "")
        for row in nodes_factory
        if row.get("label") == "Sensor"
    }
    factory_component_names = {
        row.get("name", "")
        for row in nodes_factory
        if row.get("label") == "Component"
    }
    factory_phantom_sensors = sorted(factory_sensor_names - raw_sensor_ids)
    factory_missing_sensors = sorted(raw_sensor_ids - factory_sensor_names)
    component_names = {row.get("name", "") for row in nodes if row.get("label") == "Component"}
    factory_missing_components = sorted(component_names - factory_component_names)
    nodes_by_id = {row.get("nodeId", ""): row for row in nodes}
    factory_node_id_conflicts: list[str] = []
    for row in nodes_factory:
        node_id = row.get("nodeId", "")
        if node_id in nodes_by_id and row.get("name", "") != nodes_by_id[node_id].get("name", ""):
            factory_node_id_conflicts.append(
                f"{node_id}: nodes.csv={nodes_by_id[node_id].get('name', '')}, nodes_factory.csv={row.get('name', '')}"
            )

    add_audit(audit_rows, "kg", "nodes_row_count", "PASS" if len(nodes) == EXPECTED_NODE_COUNT else "WARN", len(nodes))
    add_audit(audit_rows, "kg", "edges_row_count", "PASS" if len(edges) == EXPECTED_EDGE_COUNT else "WARN", len(edges))
    add_audit(audit_rows, "kg", "node_id_duplicates", "PASS" if not duplicated_node_ids else "FAIL", duplicated_node_ids)
    add_audit(audit_rows, "kg", "node_label_distribution", "PASS", dict(label_counts))
    add_audit(audit_rows, "kg", "edge_type_distribution", "PASS", dict(edge_type_counts))
    add_audit(audit_rows, "kg", "dangling_edges", "PASS" if not dangling_edges else "FAIL", len(dangling_edges))
    add_audit(audit_rows, "kg", "duplicate_edges", "PASS" if not duplicate_edges else "WARN", len(duplicate_edges))
    add_audit(audit_rows, "kg", "bidirectional_edges", "WARN" if bidirectional_edges else "PASS", len(bidirectional_edges))
    add_audit(audit_rows, "kg", "sensor_nodes_not_in_raw", "PASS" if not sensor_nodes_not_in_raw else "WARN", sensor_nodes_not_in_raw)
    add_audit(audit_rows, "kg", "raw_sensors_not_in_nodes", "PASS" if not raw_sensors_not_in_nodes else "WARN", raw_sensors_not_in_nodes)

    if factory_phantom_sensors or factory_missing_sensors or factory_node_id_conflicts:
        append_issue(
            issues,
            "ISSUE-KG-NODES-FACTORY",
            "kg",
            "high",
            "recorded",
            "`nodes_factory.csv` is an early draft and is not a reliable equipment/sensor catalog.",
            json.dumps(
                {
                    "phantom_sensors": factory_phantom_sensors,
                    "missing_sensors_count": len(factory_missing_sensors),
                    "missing_components": factory_missing_components,
                    "node_id_conflicts": factory_node_id_conflicts,
                },
                ensure_ascii=False,
            ),
            "Exclude `nodes_factory.csv` from import paths; keep only as legacy reference.",
        )
    if bidirectional_edges:
        append_issue(
            issues,
            "ISSUE-KG-BIDIRECTIONAL-MONITORS",
            "kg",
            "medium",
            "recorded",
            "KG seed contains bidirectional relationship pairs, especially `monitors`.",
            f"bidirectional_edge_rows={len(bidirectional_edges)}",
            "Record only; do not redesign relationships in preprocessing.",
        )

    anomaly_events = [row for row in nodes if row.get("label") == "AnomalyEvent"]
    if anomaly_events:
        append_issue(
            issues,
            "ISSUE-KG-ANOMALY-EVENTS",
            "kg",
            "high",
            "recorded",
            "Seed KG includes 14 AnomalyEvent truth nodes.",
            f"anomaly_event_count={len(anomaly_events)}",
            "Exclude from detection evaluation inputs; may be intentionally inserted later for GraphRAG Agent demos/explanations.",
        )

    spd_gt_rows = [
        row
        for row in ground_truth
        if "SPD" in row.get("sensor", "") or "SPD" in row.get("sensorType", "")
    ]
    if spd_gt_rows:
        append_issue(
            issues,
            "ISSUE-GT-SPD-THRESHOLDS",
            "ground_truth",
            "medium",
            "recorded",
            "SPD-related ground truth rows need review against SOP/raw threshold values.",
            json.dumps(
                [
                    {
                        "ruleId": row.get("ruleId", ""),
                        "sensor": row.get("sensor", ""),
                        "critHi": row.get("critHi", ""),
                        "warnHi": row.get("warnHi", ""),
                        "critLo": row.get("critLo", ""),
                        "warnLo": row.get("warnLo", ""),
                    }
                    for row in spd_gt_rows
                ],
                ensure_ascii=False,
            ),
            "Do not modify ground truth during preprocessing; record for later evaluation policy.",
        )

    gt0007 = [row for row in anomaly_events if row.get("gtId") == "GT-0007"]
    if gt0007:
        append_issue(
            issues,
            "ISSUE-GT-0007-SEVERITY",
            "ground_truth",
            "medium",
            "recorded",
            "GT-0007 is recorded as WARNING despite being an FLW SPIKE candidate requiring later policy review.",
            json.dumps(gt0007, ensure_ascii=False),
            "Do not alter original labels; record as issue.",
        )

    return {
        "nodes_count": len(nodes),
        "edges_count": len(edges),
        "node_label_distribution": dict(label_counts),
        "edge_type_distribution": dict(edge_type_counts),
        "dangling_edges": len(dangling_edges),
        "duplicate_edges": len(duplicate_edges),
        "bidirectional_edges": len(bidirectional_edges),
        "sensor_nodes_not_in_raw": sensor_nodes_not_in_raw,
        "raw_sensors_not_in_nodes": raw_sensors_not_in_nodes,
        "nodes_factory_phantom_sensors": factory_phantom_sensors,
        "nodes_factory_missing_sensors_count": len(factory_missing_sensors),
        "nodes_factory_missing_components": factory_missing_components,
        "nodes_factory_node_id_conflicts": factory_node_id_conflicts,
    }


def analyze_human_access_csi(
    dataset_root: Path,
    issues: list[Issue],
    audit_rows: list[AuditRow],
    sensor_min_ts: datetime,
    sensor_max_ts: datetime,
) -> dict[str, Any]:
    access = read_csv_rows(dataset_root / REQUIRED_DATASET_FILES["access_events"])
    occupancy = read_csv_rows(dataset_root / REQUIRED_DATASET_FILES["occupancy_timeseries"])
    alarm_response = read_csv_rows(dataset_root / REQUIRED_DATASET_FILES["alarm_response_log"])
    people = read_csv_rows(dataset_root / REQUIRED_DATASET_FILES["person_registry"])

    access_times = [parse_timestamp(row["timestamp"]) for row in access]
    outside_range = [
        row
        for row in access
        if parse_timestamp(row["timestamp"]) < sensor_min_ts
        or parse_timestamp(row["timestamp"]) > sensor_max_ts
    ]
    unknown_people = [row for row in access if row.get("person_id") == "UNKNOWN"]
    occupancy_anomaly_counts = Counter(row.get("occupancy_anomaly", "") for row in occupancy)
    occupancy_severity_counts = Counter(row.get("oc_severity", "") for row in occupancy)
    csi_gesture_counts = Counter(row.get("csi_gesture", "") for row in occupancy)
    sla_counts = Counter(row.get("sla_met", "") for row in alarm_response)
    registered_people = {row.get("person_id", "") for row in people}
    access_people_not_in_registry = sorted(
        {row.get("person_id", "") for row in access} - registered_people - {"UNKNOWN"}
    )

    add_audit(audit_rows, "human", "access_row_count", "PASS", len(access))
    add_audit(audit_rows, "human", "access_time_range", "PASS", f"{min(access_times)} to {max(access_times)}")
    add_audit(audit_rows, "human", "access_outside_sensor_range", "WARN" if outside_range else "PASS", len(outside_range))
    add_audit(audit_rows, "human", "access_unknown_people", "WARN" if unknown_people else "PASS", len(unknown_people))
    add_audit(audit_rows, "human", "access_people_not_in_registry", "PASS" if not access_people_not_in_registry else "WARN", access_people_not_in_registry)
    add_audit(audit_rows, "human", "occupancy_anomaly_counts", "WARN", dict(occupancy_anomaly_counts))
    add_audit(audit_rows, "human", "occupancy_severity_counts", "WARN", dict(occupancy_severity_counts))
    add_audit(audit_rows, "human", "csi_gesture_counts", "WARN", dict(csi_gesture_counts))
    add_audit(audit_rows, "human", "alarm_response_sla_counts", "WARN", dict(sla_counts))

    if outside_range:
        append_issue(
            issues,
            "ISSUE-HUMAN-ACCESS-RANGE",
            "human",
            "low",
            "recorded",
            "Some access events fall outside the sensor/occupancy time range.",
            f"outside_range_count={len(outside_range)}",
            "Do not drop raw events; flag range mismatch for downstream joins.",
        )
    if unknown_people:
        append_issue(
            issues,
            "ISSUE-HUMAN-UNKNOWN",
            "human",
            "low",
            "recorded",
            "Access events include UNKNOWN person_id values.",
            f"unknown_count={len(unknown_people)}",
            "Preserve as unauthorized/visitor-like records; do not impute identities.",
        )
    if occupancy_anomaly_counts or occupancy_severity_counts:
        append_issue(
            issues,
            "ISSUE-LEAK-OCCUPANCY-LABELS",
            "human",
            "medium",
            "recorded",
            "`occupancy_anomaly`, `oc_severity`, and `csi_gesture` are label-like for safety/CSI work.",
            json.dumps(
                {
                    "occupancy_anomaly": dict(occupancy_anomaly_counts),
                    "oc_severity": dict(occupancy_severity_counts),
                    "csi_gesture": dict(csi_gesture_counts),
                },
                ensure_ascii=False,
            ),
            "Do not use as sensor anomaly detection features; exclude from Safety/CSI model inputs.",
        )
    append_issue(
        issues,
        "ISSUE-ALARM-ACTION-TAKEN",
        "human",
        "medium",
        "recorded",
        "`alarm_response_log.action_taken` is free-text operational response, not a trusted corrective-action ground truth.",
        f"unique_action_taken={len({row.get('action_taken', '') for row in alarm_response})}, sla_counts={dict(sla_counts)}",
        "Use alarm response log for SLA timing only; source corrective actions from SOP tables in later KG work.",
    )

    csi_dir = dataset_root / "csi"
    csi_files = list(csi_dir.glob("*/*.csv")) if csi_dir.exists() else []
    csi_subjects = {path.parent.name for path in csi_files}
    add_audit(audit_rows, "human", "csi_file_count", "PASS" if csi_files else "WARN", len(csi_files))
    add_audit(audit_rows, "human", "csi_subject_count", "PASS" if csi_subjects else "WARN", len(csi_subjects))

    return {
        "access_rows": len(access),
        "access_time_range": [min(access_times).isoformat(), max(access_times).isoformat()],
        "access_outside_sensor_range_count": len(outside_range),
        "unknown_person_count": len(unknown_people),
        "occupancy_anomaly_counts": dict(occupancy_anomaly_counts),
        "occupancy_severity_counts": dict(occupancy_severity_counts),
        "csi_gesture_counts": dict(csi_gesture_counts),
        "alarm_response_sla_counts": dict(sla_counts),
        "csi_file_count": len(csi_files),
        "csi_subject_count": len(csi_subjects),
    }


def write_audit_and_issues(
    output_root: Path,
    audit_rows: list[AuditRow],
    issues: list[Issue],
) -> dict[str, int]:
    audit_count = write_csv(
        output_root / "kg" / "kg_reference_audit.csv",
        (row.__dict__ for row in audit_rows),
        ["area", "check", "status", "observed", "details"],
    )
    issue_count = write_csv(
        output_root / "issues" / "preprocessing_issues.csv",
        (issue.__dict__ for issue in issues),
        ["issue_id", "area", "severity", "status", "description", "evidence", "policy_or_action"],
    )
    return {"audit_rows": audit_count, "issue_rows": issue_count}


def input_file_metadata(dataset_root: Path) -> dict[str, dict[str, Any]]:
    metadata: dict[str, dict[str, Any]] = {}
    for name, relative_path in REQUIRED_DATASET_FILES.items():
        path = dataset_root / relative_path
        metadata[name] = {
            "relative_path": str(relative_path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        if path.suffix == ".csv":
            metadata[name]["columns"] = read_csv_header(path)
    for relative_path in DOCUMENT_FILES:
        path = dataset_root / relative_path
        metadata[relative_path.stem] = {
            "relative_path": str(relative_path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
    return metadata


def validate_outputs(output_root: Path) -> list[str]:
    errors: list[str] = []
    required_outputs = [
        output_root / "sensors" / "timeseries_input_clean.csv",
        output_root / "sensors" / "timeseries_eval_labels.csv",
        output_root / "sensors" / "timeseries_rule_reference.csv",
        output_root / "sensors" / "mqtt_input_stream.jsonl",
        output_root / "documents" / "document_index.csv",
        output_root / "documents" / "document_extraction_preview.jsonl",
        output_root / "kg" / "kg_reference_audit.csv",
        output_root / "issues" / "preprocessing_issues.csv",
        output_root / "preprocessing_log.json",
    ]
    for path in required_outputs:
        if not path.exists():
            errors.append(f"Missing output: {path}")

    clean_path = output_root / "sensors" / "timeseries_input_clean.csv"
    if clean_path.exists():
        clean_header = set(read_csv_header(clean_path))
        forbidden = clean_header & SENSOR_LEAKAGE_COLUMNS
        if forbidden:
            errors.append(f"Forbidden leakage columns in clean input: {sorted(forbidden)}")

    mqtt_path = output_root / "sensors" / "mqtt_input_stream.jsonl"
    if mqtt_path.exists():
        with mqtt_path.open("r", encoding="utf-8") as handle:
            for line_no, line in enumerate(handle, start=1):
                payload = json.loads(line)
                if "status" in payload or "alarms" in payload:
                    errors.append(f"MQTT leakage field found at line {line_no}")
                    break
                for reading in payload.get("readings", {}).values():
                    if isinstance(reading, dict) and "quality" in reading:
                        errors.append(f"MQTT nested quality field found at line {line_no}")
                        break
                if errors:
                    break

    preview_path = output_root / "documents" / "document_extraction_preview.jsonl"
    if preview_path.exists():
        with preview_path.open("r", encoding="utf-8") as handle:
            first_line = handle.readline()
        if not first_line:
            errors.append("Document extraction preview is empty.")
        else:
            first_record = json.loads(first_line)
            for required_field in ["document_id", "source_file", "page", "text"]:
                if required_field not in first_record:
                    errors.append(f"Document preview missing field: {required_field}")
    return errors


def run_preprocessing(dataset_root: Path, output_root: Path) -> dict[str, Any]:
    dataset_root = dataset_root.resolve()
    output_root = output_root.resolve()
    validate_dataset_files(dataset_root)

    LOGGER.info("Reading sensor CSV files...")
    raw_rows = read_csv_rows(dataset_root / REQUIRED_DATASET_FILES["timeseries_raw"])
    annotated_rows = read_csv_rows(dataset_root / REQUIRED_DATASET_FILES["timeseries_annotated"])

    issues: list[Issue] = []
    audit_rows: list[AuditRow] = []

    sensor_summary = analyze_sensor_timeseries(raw_rows, annotated_rows, issues, audit_rows)
    sensor_output_counts = write_sensor_outputs(raw_rows, annotated_rows, output_root)

    sensor_timestamps = [parse_timestamp(row["timestamp"]) for row in raw_rows]
    sensor_min_ts = min(sensor_timestamps)
    sensor_max_ts = max(sensor_timestamps)

    LOGGER.info("Sanitizing MQTT payloads...")
    mqtt_summary = sanitize_mqtt_payloads(
        dataset_root / REQUIRED_DATASET_FILES["mqtt_payloads"],
        output_root,
        issues,
        audit_rows,
    )

    LOGGER.info("Extracting PDF document previews...")
    document_summary = extract_documents(dataset_root, output_root, audit_rows, issues)

    LOGGER.info("Auditing KG reference files...")
    kg_summary = analyze_kg_reference(
        dataset_root,
        set(sensor_summary["raw_sensor_ids"]),
        issues,
        audit_rows,
    )

    LOGGER.info("Running minimal human/access/CSI checks...")
    human_summary = analyze_human_access_csi(
        dataset_root,
        issues,
        audit_rows,
        sensor_min_ts,
        sensor_max_ts,
    )

    counts = write_audit_and_issues(output_root, audit_rows, issues)

    log_payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "dataset_root": str(dataset_root),
        "output_root": str(output_root),
        "scope_exclusions": [
            "normalization",
            "z-score",
            "delta_features",
            "rolling_features",
            "smoothing",
            "interpolation",
            "sliding_windows",
            "embedding",
            "vector_db",
            "llm_triple_extraction",
            "ontology_mapping",
            "rdf_ttl_conversion",
            "neo4j_import",
            "relation_expansion",
            "graphrag_agent",
        ],
        "input_files": input_file_metadata(dataset_root),
        "policies": {
            "clean_input_excluded_columns": sorted(SENSOR_LEAKAGE_COLUMNS),
            "threshold_policy": "Operational prior knowledge preserved separately for rule baseline and GraphRAG reference; excluded from clean ML/pattern input.",
            "anomaly_event_policy": "Exclude from detection evaluation inputs; may be intentionally inserted later for final GraphRAG Agent demos/explanations.",
            "nodes_factory_policy": "Exclude from import paths; unreliable legacy draft.",
            "raw_data_policy": "Never modify source files; record issues instead of editing labels.",
        },
        "sensor_summary": sensor_summary,
        "sensor_output_counts": sensor_output_counts,
        "mqtt_summary": mqtt_summary,
        "document_summary": document_summary,
        "kg_summary": kg_summary,
        "human_summary": human_summary,
        "audit_issue_counts": counts,
    }
    write_json(output_root / "preprocessing_log.json", log_payload)

    validation_errors = validate_outputs(output_root)
    if validation_errors:
        raise RuntimeError("Output validation failed:\n" + "\n".join(validation_errors))

    return log_payload


def main() -> int:
    args = parse_args()
    configure_logging(args.log_level)

    try:
        if args.validate_only:
            errors = validate_outputs(args.output_root.resolve())
            if errors:
                for error in errors:
                    LOGGER.error(error)
                return 1
            LOGGER.info("Existing preprocessing outputs passed validation.")
            return 0

        summary = run_preprocessing(args.dataset_root, args.output_root)
        LOGGER.info(
            "Preprocessing complete: %s sensor rows, %s issues recorded.",
            summary["sensor_summary"]["raw_row_count"],
            summary["audit_issue_counts"]["issue_rows"],
        )
        return 0
    except Exception as exc:
        LOGGER.error("%s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
