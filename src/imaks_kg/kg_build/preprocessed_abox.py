"""Build Station/Sensor ABox artifacts from preprocessing outputs only.

Seed reference files belong to evaluation/audit code, not KG construction.
"""
import argparse
import json
import re
from pathlib import Path

from imaks_kg.common.io_utils import read_csv_rows, write_json, write_jsonl
from imaks_kg.settings import PREPROCESSED, REPO_ROOT, rel


STATION_TYPES = {
    "FILLING", "SEALING", "LABELLING", "PACKAGING", "SERVERROOM",
    "WAREHOUSE", "CHEMICALSTORAGE", "RDLAB", "CAFETERIA",
}


class PreprocessedLayout:
    def __init__(self, root: Path):
        self.root = Path(root)
        if (self.root / "final_v1").exists():
            self.root = self.root / "final_v1"

    @classmethod
    def detect(cls, root=None):
        if root:
            return cls(Path(root))
        candidates = [
            PREPROCESSED / "final_v1",
            PREPROCESSED,
            REPO_ROOT / "processed",
        ]
        for candidate in candidates:
            if candidate.exists():
                return cls(candidate)
        return cls(PREPROCESSED)

    @property
    def sensor_input(self):
        candidates = [
            self.root / "inputs" / "sensors" / "timeseries_rule_input.csv",
            self.root / "sensors" / "input" / "ts_input.csv",
            self.root / "sensors" / "timeseries_rule_reference.csv",
            self.root / "sensors" / "timeseries_input_clean.csv",
        ]
        return _first_existing(candidates)

    @property
    def sensor_thresholds(self):
        candidates = [
            self.root / "sensors" / "rules" / "sensor_thresholds.csv",
        ]
        return next((p for p in candidates if p.exists()), None)

    @property
    def documents_dir(self):
        return self.root / "documents"

    @property
    def doc_manifest(self):
        candidates = [
            self.documents_dir / "doc_manifest.csv",
            self.documents_dir / "document_index.csv",
        ]
        return _first_existing(candidates)

    @property
    def chunks_jsonl(self):
        candidates = [
            self.documents_dir / "chunks.jsonl",
            self.documents_dir / "document_extraction_preview.jsonl",
        ]
        return _first_existing(candidates)

    @property
    def pages_jsonl(self):
        path = self.documents_dir / "pages.jsonl"
        return path if path.exists() else None

    @property
    def tables_jsonl(self):
        path = self.documents_dir / "tables.jsonl"
        return path if path.exists() else None


def _first_existing(paths):
    for p in paths:
        if p.exists():
            return p
    raise FileNotFoundError("none of these preprocessing inputs exist: " + ", ".join(str(p) for p in paths))


def station_type(station_id):
    suffix = station_id.split("_", 1)[1] if "_" in station_id else station_id
    return suffix if suffix in STATION_TYPES else suffix.replace(" ", "").upper()


def build_station_sensor(layout: PreprocessedLayout):
    header, rows = read_csv_rows(layout.sensor_input)
    required = {"station_id", "sensor_id", "sensor_type", "unit", "zone"}
    missing = required - set(header)
    if missing:
        raise ValueError(f"{layout.sensor_input} missing columns: {sorted(missing)}")

    threshold_by_sensor = {}
    if layout.sensor_thresholds:
        _, threshold_rows = read_csv_rows(layout.sensor_thresholds)
        for r in threshold_rows:
            threshold_by_sensor[r["sensor_id"]] = r

    stations, sensors = {}, {}
    for r in rows:
        sid = r["station_id"]
        sensor_id = r["sensor_id"]
        stations.setdefault(sid, {
            "id": sid,
            "labels": ["Station"],
            "properties": {
                "identifier": sid,
                "stationType": station_type(sid),
                "zone": r["zone"],
                "source": rel(layout.sensor_input) if layout.sensor_input.is_relative_to(REPO_ROOT) else str(layout.sensor_input),
            },
        })
        props = {
            "identifier": sensor_id,
            "sensorType": r["sensor_type"],
            "unit": r["unit"],
            "source": rel(layout.sensor_input) if layout.sensor_input.is_relative_to(REPO_ROOT) else str(layout.sensor_input),
        }
        for src, dst in (
            ("nominal", "nominal"), ("nominalValue", "nominal"),
            ("warn_hi", "warnHi"), ("warnHi", "warnHi"),
            ("warn_lo", "warnLo"), ("warnLo", "warnLo"),
            ("crit_hi", "critHi"), ("critHi", "critHi"),
            ("crit_lo", "critLo"), ("critLo", "critLo"),
        ):
            value = r.get(src) or threshold_by_sensor.get(sensor_id, {}).get(src)
            if value:
                props[dst] = value
        sensors.setdefault(sensor_id, {"id": sensor_id, "labels": ["Sensor"], "properties": props})

    rels = []
    seen = set()
    sensor_to_station = {}
    for r in rows:
        key = (r["station_id"], r["sensor_id"], "hasSensor")
        sensor_to_station.setdefault(r["sensor_id"], set()).add(r["station_id"])
        if key not in seen:
            seen.add(key)
            rels.append({
                "source": r["station_id"],
                "target": r["sensor_id"],
                "type": "hasSensor",
                "properties": {"source": rel(layout.sensor_input) if layout.sensor_input.is_relative_to(REPO_ROOT) else str(layout.sensor_input)},
            })

    multi = {k: sorted(v) for k, v in sensor_to_station.items() if len(v) != 1}
    if multi:
        raise ValueError(f"sensors must belong to exactly one station: {multi}")

    return sorted(stations.values(), key=lambda n: n["id"]), sorted(sensors.values(), key=lambda n: n["id"]), rels


def iri_name(value):
    return re.sub(r"[^A-Za-z0-9_\\-]", "_", value)


def export_station_sensor_ttl(nodes, rels):
    lines = [
        "@prefix im: <https://example.org/imaks/v1#> .",
        "@prefix inst: <https://example.org/imaks/instance/> .",
        "@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .",
        "",
    ]
    for n in nodes:
        props = n["properties"]
        klass = n["labels"][0]
        lines.append(f"inst:{iri_name(n['id'])} a im:{klass} ;")
        pred_lines = []
        for key in ("identifier", "stationType", "zone", "sensorType", "unit"):
            if key in props:
                pred_lines.append(f'    im:{key} "{_esc(props[key])}"')
        lines.append(" ;\n".join(pred_lines) + " .\n")
    for r in rels:
        lines.append(f"inst:{iri_name(r['source'])} im:{r['type']} inst:{iri_name(r['target'])} .")
    return "\n".join(lines) + "\n"


def _esc(value):
    return str(value).replace("\\", "\\\\").replace('"', '\\"')


def build(preprocessed_root=None, out_dir=None):
    layout = PreprocessedLayout.detect(preprocessed_root)
    out = Path(out_dir or (REPO_ROOT / "kg_build" / "latest"))
    stations, sensors, rels = build_station_sensor(layout)
    nodes = stations + sensors
    write_jsonl(out / "nodes.jsonl", nodes)
    write_jsonl(out / "relationships.jsonl", rels)
    write_json(out / "audit_summary.json", {
        "preprocessed_root": rel(layout.root) if layout.root.is_relative_to(REPO_ROOT) else str(layout.root),
        "sensor_input": rel(layout.sensor_input) if layout.sensor_input.is_relative_to(REPO_ROOT) else str(layout.sensor_input),
        "station_count": len(stations),
        "sensor_count": len(sensors),
        "has_sensor_count": len(rels),
        "seed_reference_used_for_build": False,
    })
    ttl = export_station_sensor_ttl(nodes, rels)
    (out / "station_sensor.ttl").parent.mkdir(parents=True, exist_ok=True)
    (out / "station_sensor.ttl").write_text(ttl, encoding="utf-8", newline="\n")
    return {"nodes": nodes, "relationships": rels, "out_dir": out}


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("--preprocessed", default=None)
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)
    result = build(args.preprocessed, args.out)
    print(f"built {len(result['nodes'])} nodes and {len(result['relationships'])} relationships")
    print(f"output: {result['out_dir']}")


if __name__ == "__main__":
    main()
