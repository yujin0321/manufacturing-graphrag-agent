"""Deterministic rule extraction from preprocessed document chunks/tables.

The module also defines the JSONL shape expected from a later LLM extractor.
Evaluation labels are intentionally outside this package.
"""
import argparse
import json
import re
from pathlib import Path

from imaks_kg.common.io_utils import read_csv_rows, write_json, write_jsonl
from imaks_kg.kg_build.document_nodes import load_chunks, load_jsonl
from imaks_kg.kg_build.preprocessed_abox import PreprocessedLayout
from imaks_kg.kg_build.rule_schema import RuleRecord, validate_rule
from imaks_kg.settings import REPO_ROOT


SOP002_THRESHOLD_HEADING_RE = re.compile(r"\b([A-Z0-9_]+)\s+Thresholds\b")
TYPE_WORD = {
    "TMP": "Temperature", "PRS": "Pressure", "FLW": "Flow", "CUR": "Current",
    "SPD": "Speed", "TEN": "Tension", "CNT": "Count", "VIB": "Vibration", "HUM": "Humidity",
}
ZONE_CODE = {
    "Production Area": "PROD", "Server Room": "SRV", "General Warehouse": "WRH",
    "Chemical Storage": "CHM", "R&D Lab": "RND", "Cafeteria": "CAFETERIA",
}


def split_condition_action(text):
    body = re.sub(r"^[A-Z0-9_-]+:\s*", "", text).strip()
    body = re.sub(r"^If\s+", "", body, flags=re.I)
    for sep in (" — ", " - "):
        if sep in body:
            left, right = body.split(sep, 1)
            return left.strip(" ."), right.strip(" .")
    if "," in body:
        left, right = body.split(",", 1)
        return left.strip(" ."), right.strip(" .")
    return body.strip(" ."), ""


def rule_sev(text):
    upper = text.upper()
    if "CRITICAL" in upper or "E-STOP" in upper or "EMERGENCY" in upper:
        return "CRITICAL"
    if "WARNING" in upper or "WARN" in upper:
        return "WARNING"
    if "MUST" in upper:
        return "MANDATORY"
    return ""


def station_from_section(section):
    m = re.search(r"([A-Z]{2,4}\d{2}_[A-Z]+)", section or "")
    return m.group(1) if m else ""


def sensor_type_from_text(text):
    for stype in TYPE_WORD:
        if re.search(rf"\b{stype}\b", text):
            return stype
    return ""


def sensor_id(station, stype):
    return f"{station}_{stype}" if station and stype else ""


def extract_rule_chunks(chunks):
    rules = []
    for c in chunks:
        if c.get("kind") != "rule":
            continue
        rid = c.get("rule_id") or c["chunk_id"].rsplit(":", 1)[-1]
        doc = c.get("document_id") or c.get("doc_id")
        text = c.get("text", "")
        klass = "AccessRule" if doc == "SOP-004" or rid == "RULE-CHM01-03" else "OperationalRule"
        station = station_from_section(c.get("section", ""))
        if rid == "RULE-CHM01-03":
            station = "Chemical Storage"
        stype = sensor_type_from_text(text)
        condition, action = split_condition_action(text)
        rules.append(RuleRecord(
            ruleId=rid, class_=klass, station=station, sensor=sensor_id(station, stype),
            sensorType=stype, condition=condition, action=action, ruleSeverity=rule_sev(text),
            source=doc, sourceDocument=doc, provenanceId=f"prov:{c['chunk_id']}",
        ))
    return rules


def table_header(rows):
    return rows[0] if rows else []


def row_dict(header, row):
    return {h: row[i] if i < len(row) else "" for i, h in enumerate(header)}


def station_sensor_sets(layout):
    _, rows = read_csv_rows(layout.sensor_input)
    stations = {r["station_id"] for r in rows if r.get("station_id")}
    sensors = {r["sensor_id"] for r in rows if r.get("sensor_id")}
    return stations, sensors


def _doc_id(record):
    return record.get("document_id") or record.get("doc_id")


def _page_no(record):
    return record.get("page") or record.get("page_number") or record.get("page_no")


def _table_order_key(table):
    page = _page_no(table) or 0
    bbox = table.get("bbox") or []
    top = bbox[1] if len(bbox) > 1 else 0
    return page, top, table.get("table_id", "")


def _page_text(page):
    return page.get("text") or page.get("text_normalized") or page.get("text_raw") or ""


def _is_threshold_header(header):
    return "Sensor" in header and "CRIT_LO" in header and "CRIT_HI" in header


def _is_threshold_continuation(rows):
    if not rows:
        return False
    first = rows[0]
    return bool(first and first[0] in TYPE_WORD and not _is_threshold_header(first))


def sop002_station_headings_by_page(pages):
    headings = {}
    for page in pages:
        if _doc_id(page) != "SOP-002":
            continue
        page_no = _page_no(page)
        station_ids = [m.group(1) for m in SOP002_THRESHOLD_HEADING_RE.finditer(_page_text(page))]
        if station_ids:
            headings[page_no] = station_ids
    return headings


def sop002_threshold_table_contexts(tables, pages, valid_stations):
    headings_by_page = sop002_station_headings_by_page(pages)
    heading_offsets = {page: 0 for page in headings_by_page}
    contexts = []
    last_station = ""
    last_header = []

    for table in sorted((t for t in tables if _doc_id(t) == "SOP-002"), key=_table_order_key):
        rows = table.get("rows") or table.get("rows_normalized") or []
        if not rows:
            continue
        header = table_header(rows)
        page_no = _page_no(table)
        table_id = table.get("table_id", "<unknown-table>")

        if _is_threshold_header(header):
            headings = headings_by_page.get(page_no, [])
            offset = heading_offsets.get(page_no, 0)
            if offset >= len(headings):
                raise ValueError(
                    f"SOP-002 threshold table {table_id} on page {page_no} has no document heading"
                )
            station = headings[offset]
            heading_offsets[page_no] = offset + 1
            continuation = False
            data_rows = rows[1:]
            last_station = station
            last_header = header
        elif _is_threshold_continuation(rows):
            if not last_station or not last_header:
                raise ValueError(
                    f"SOP-002 continuation table {table_id} on page {page_no} has no previous station heading"
                )
            station = last_station
            header = last_header
            continuation = True
            data_rows = rows
        else:
            continue

        if station not in valid_stations:
            raise ValueError(
                f"SOP-002 station heading {station} for table {table_id} is not in built Station set"
            )
        contexts.append({
            "table_id": table_id,
            "page": page_no,
            "station": station,
            "header": header,
            "rows": data_rows,
            "continuation": continuation,
        })

    return contexts


def extract_threshold_rules(tables, pages, valid_stations=None, valid_sensors=None, return_audit=False):
    rules = []
    valid_stations = valid_stations or set()
    valid_sensors = valid_sensors or set()
    threshold_contexts = sop002_threshold_table_contexts(tables, pages, valid_stations)

    for context in threshold_contexts:
        station = context["station"]
        header = context["header"]
        for row in context["rows"]:
            d = row_dict(header, row)
            stype = d.get("Sensor", "")
            unit = d.get("Unit", "")
            sid = sensor_id(station, stype)
            if valid_sensors and sid not in valid_sensors:
                raise ValueError(
                    f"SOP-002 threshold row {context['table_id']} maps to missing Sensor {sid}"
                )
            word = TYPE_WORD.get(stype, stype)
            condition = (
                f"{word} critical thresholds: {d.get('CRIT_LO')} {unit} (CRIT_LO), "
                f"{d.get('WARN_LO')} {unit} (WARN_LO), {d.get('Nominal')} {unit} (NOMINAL), "
                f"{d.get('WARN_HI')} {unit} (WARN_HI), {d.get('CRIT_HI')} {unit} (CRIT_HI)"
            )
            short = station.split("_", 1)[0]
            rules.append(RuleRecord(
                ruleId=f"RULE-THR-{short}-{stype}-CRIT", class_="ThresholdRule",
                station=station, sensor=sid, sensorType=stype,
                condition=condition, action=d.get("CRITICAL Response", ""), ruleSeverity="CRITICAL",
                critHi=d.get("CRIT_HI", ""), warnHi=d.get("WARN_HI", ""),
                critLo=d.get("CRIT_LO", ""), warnLo=d.get("WARN_LO", ""), unit=unit,
                source="SOP-002", sourceDocument="SOP-002",
                provenanceId=f"prov:{context['table_id']}:chunk",
            ))

    for t in tables:
        if _doc_id(t) != "SOP-002":
            continue
        rows = t.get("rows") or t.get("rows_normalized") or []
        header = table_header(rows)
        if "Ontology Class" in header:
            for row in rows[1:]:
                d = row_dict(header, row)
                typ = d.get("Type", "")
                rules.append(RuleRecord(
                    ruleId=f"RULE-ANOM-{typ}", class_="ThresholdRule",
                    condition=f"{d.get('Definition')}; {d.get('Detection Criterion')}",
                    action=d.get("Ontology Class", ""), ruleSeverity="CRITICAL",
                    source="SOP-002", sourceDocument="SOP-002", provenanceId=f"prov:{t['table_id']}:chunk",
                ))

    audit = [{
        "table_id": c["table_id"],
        "page": c["page"],
        "station": c["station"],
        "continuation": c["continuation"],
        "row_count": len(c["rows"]),
    } for c in threshold_contexts]
    if return_audit:
        return rules, audit
    return rules


def extract_maintenance_rules(tables):
    rules = []
    corr_no = 1
    for t in tables:
        if (t.get("document_id") or t.get("doc_id")) != "SOP-003":
            continue
        rows = t.get("rows") or t.get("rows_normalized") or []
        header = table_header(rows)
        if "Rule ID" in header and "Priority" in header:
            for row in rows[1:]:
                d = row_dict(header, row)
                station = d.get("Station", "")
                stype = d.get("Sensor", "")
                rules.append(RuleRecord(
                    ruleId=d.get("Rule ID", ""), class_="MaintenanceRule",
                    station=station, sensor=sensor_id(station, stype), sensorType=stype,
                    condition=d.get("Trigger", ""), action=d.get("Action", ""), ruleSeverity=d.get("Priority", ""),
                    unit=_unit_for(stype), source="SOP-003", sourceDocument="SOP-003",
                    provenanceId=f"prov:{t['table_id']}:chunk",
                ))
        elif "Pattern" in header and "Resolution" in header:
            for row in rows[1:]:
                d = row_dict(header, row)
                pattern = d.get("Pattern", "")
                station, stype = _station_sensor_from_pattern(pattern)
                rules.append(RuleRecord(
                    ruleId=f"RULE-CORR-{corr_no:02d}", class_="MaintenanceRule",
                    station=station, sensor=sensor_id(station, stype), sensorType=stype,
                    condition=f"{pattern}: {d.get('Primary Fault')} -> {d.get('Secondary Effect')}",
                    action=d.get("Resolution", ""), ruleSeverity="WARNING",
                    unit=_unit_for(stype), source="SOP-003", sourceDocument="SOP-003",
                    provenanceId=f"prov:{t['table_id']}:chunk",
                ))
                corr_no += 1
    return rules


def _unit_for(stype):
    return {"TMP": "°C", "PRS": "bar", "FLW": "L/min", "CUR": "A", "SPD": "m/s",
            "TEN": "N", "CNT": "pcs/min", "VIB": "mm/s", "HUM": "%RH"}.get(stype, "")


def _station_sensor_from_pattern(pattern):
    m = re.match(r"([A-Z]{2,4}\d{2}_[A-Z]+)-([A-Z]+)", pattern)
    if m:
        return m.group(1), m.group(2)
    m = re.match(r"([A-Z]{3}\d{2})-([A-Z]+)", pattern)
    if m and m.group(1) == "SRV01":
        return "SRV01_SERVERROOM", m.group(2)
    if m and m.group(1) == "WRH01":
        return "WRH01_WAREHOUSE", m.group(2)
    return "", ""


def extract_access_table_rules(tables):
    rules = []
    for t in tables:
        if (t.get("document_id") or t.get("doc_id")) != "SOP-004":
            continue
        rows = t.get("rows") or t.get("rows_normalized") or []
        header = table_header(rows)
        if header[:3] == ["Zone", "Max Persons", "Enforcement"]:
            for row in rows[1:]:
                d = row_dict(header, row)
                zone = d.get("Zone", "")
                if zone == "Main Entrance":
                    continue
                code = ZONE_CODE.get(zone, zone.upper().replace(" ", "_"))
                enforcement = d.get("Enforcement", "")
                ruleSeverity = rule_sev(enforcement)
                rules.append(RuleRecord(
                    ruleId=f"RULE-OCC-{code}", class_="AccessRule", station=zone,
                    condition=f"Occupancy {enforcement} (max {d.get('Max Persons')})",
                    action=_occupancy_action(zone, ruleSeverity), ruleSeverity=ruleSeverity, unit="persons",
                    source="SOP-004", sourceDocument="SOP-004", provenanceId=f"prov:{t['table_id']}:chunk",
                ))
        elif header[:3] == ["Role", "Max Ack — WARNING (min)", "Max Ack — CRITICAL (min)"]:
            for row in rows[1:]:
                d = row_dict(header, row)
                role = d.get("Role", "")
                role_code = {"operator": "OP", "technician": "TECH", "supervisor": "SUP",
                             "manager": "MAN", "security": "SEC"}.get(role, role.upper())
                for sev, col, suffix in (("WARNING", "Max Ack — WARNING (min)", "WARN"),
                                         ("CRITICAL", "Max Ack — CRITICAL (min)", "CRIT")):
                    minutes = d.get(col, "")
                    if not minutes:
                        continue
                    rules.append(RuleRecord(
                        ruleId=f"RULE-ACK-{role_code}-{suffix}", class_="AccessRule",
                        condition=f"{role} role — {sev} alarm acknowledgment",
                        action=f"Must acknowledge within {minutes} minutes", ruleSeverity="MANDATORY", unit="min",
                        source="SOP-004", sourceDocument="SOP-004", provenanceId=f"prov:{t['table_id']}:chunk",
                    ))
    return rules


def _occupancy_action(zone, ruleSeverity):
    if zone == "Chemical Storage":
        return "Alert safety officer; enforce hazmat policy"
    if ruleSeverity == "CRITICAL":
        return "Alert security immediately"
    if ruleSeverity == "WARNING":
        return "Alert supervisor"
    return ""


def extract(preprocessed_root=None, return_audit=False):
    layout = PreprocessedLayout.detect(preprocessed_root)
    chunks = load_chunks(layout)
    tables = load_jsonl(layout.tables_jsonl) if layout.tables_jsonl else []
    pages = load_jsonl(layout.pages_jsonl) if layout.pages_jsonl else []
    stations, sensors = station_sensor_sets(layout)
    rules = []
    rules.extend(extract_rule_chunks(chunks))
    threshold_rules, threshold_audit = extract_threshold_rules(
        tables, pages, stations, sensors, return_audit=True
    )
    rules.extend(threshold_rules)
    rules.extend(extract_maintenance_rules(tables))
    rules.extend(extract_access_table_rules(tables))

    deduped = {}
    for rule in rules:
        if rule.ruleId not in deduped:
            deduped[rule.ruleId] = validate_rule(rule)
    extracted = list(deduped.values())
    if return_audit:
        return extracted, {"sop002_threshold_station_mapping": threshold_audit}
    return extracted


def build(preprocessed_root=None, out_dir=None):
    out = Path(out_dir or (REPO_ROOT / "kg_build" / "latest"))
    rules, audit = extract(preprocessed_root, return_audit=True)
    records = [r.to_dict() for r in rules]
    write_jsonl(out / "rules_extracted.jsonl", records)
    by_class = {}
    for r in records:
        by_class[r["class"]] = by_class.get(r["class"], 0) + 1
    write_json(out / "rule_extract_summary.json", {
        "rule_count": len(records),
        "by_class": by_class,
        "evaluation_labels_used_for_extraction": False,
        "seed_reference_used_for_extraction": False,
        **audit,
    })
    return {"rules": records, "out_dir": out}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--preprocessed", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    result = build(args.preprocessed, args.out)
    print(f"extracted {len(result['rules'])} rules")
    print(f"output: {result['out_dir']}")


if __name__ == "__main__":
    main()
